import threading

from dcim.models import DeviceRole
from django.db import connection
from django.test import TransactionTestCase

from netbox_naming.choices import KindChoices, TargetFieldChoices
from netbox_naming.engine import NamingContext, allocate
from netbox_naming.models import NamingConvention, NamingCounter


class ConcurrentAllocationTest(TransactionTestCase):
    def setUp(self):
        self.role = DeviceRole.objects.create(name="Access Point", slug="access-point")
        self.convention = NamingConvention.objects.create(
            name="aps",
            kind=KindChoices.NUMBERED,
            target_field=TargetFieldChoices.NAME,
            template="ap###",
            role=self.role,
        )

    def test_two_threads_get_distinct_numbers(self):
        batches, batch_size = 5, 3
        barrier = threading.Barrier(2)
        numbers, errors = [], []

        def worker():
            try:
                barrier.wait()
                for _ in range(batches):
                    proposals = allocate(self.convention, NamingContext(role=self.role), batch_size)
                    numbers.extend(p.number for p in proposals)
            except Exception as exc:  # noqa: BLE001 - re-raised as a failure on the main thread
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # No counter row existed before the race, so the first allocations also race to create it.
        self.assertEqual(errors, [])
        total = 2 * batches * batch_size
        self.assertEqual(sorted(numbers), list(range(1, total + 1)))
        self.assertEqual(NamingCounter.objects.get().last_value, total)
