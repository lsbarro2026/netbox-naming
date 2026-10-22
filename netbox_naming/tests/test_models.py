from core.models import ObjectType
from dcim.models import Device, DeviceRole, DeviceType, Manufacturer
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from extras.models import CustomField

from netbox_naming.choices import CounterScopeChoices, KindChoices, TargetFieldChoices
from netbox_naming.models import NamingConvention, NamingCounter


class ModelTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        manufacturer = Manufacturer.objects.create(name="Acme", slug="acme")
        cls.device_type = DeviceType.objects.create(
            manufacturer=manufacturer, model="AP-1", slug="ap-1"
        )
        cls.other_type = DeviceType.objects.create(
            manufacturer=manufacturer, model="AP-2", slug="ap-2"
        )
        cls.role = DeviceRole.objects.create(name="Access Point", slug="access-point")
        cls.other_role = DeviceRole.objects.create(name="Switch", slug="switch")

    def make(self, **kwargs):
        defaults = {
            "name": "conv",
            "kind": KindChoices.NUMBERED,
            "target_field": TargetFieldChoices.NAME,
            "template": "ap##",
            "role": self.role,
        }
        defaults.update(kwargs)
        return NamingConvention(**defaults)

    def assertInvalid(self, convention, field=None):
        with self.assertRaises(ValidationError) as ctx:
            convention.full_clean()
        if field is not None:
            self.assertIn(field, ctx.exception.message_dict)


class CleanTest(ModelTestBase):
    def test_valid_conventions(self):
        self.make().full_clean()
        self.make(
            name="static",
            kind=KindChoices.STATIC,
            template="core-{site_slug}",
            role=None,
            device_type=self.device_type,
        ).full_clean()
        self.make(
            name="tail", kind=KindChoices.TAIL, template="{room}-{tail}", tail_max_length=12
        ).full_clean()

    def test_requires_role_or_device_type(self):
        self.assertInvalid(self.make(role=None))

    def test_unparseable_template(self):
        self.assertInvalid(self.make(template="ap{x.__class__}##"), "template")

    def test_numbered_needs_exactly_one_run(self):
        self.assertInvalid(self.make(template="ap"), "template")

    def test_tail_must_end_in_tail_without_run(self):
        self.assertInvalid(self.make(kind=KindChoices.TAIL, template="{room}"), "template")
        self.assertInvalid(self.make(kind=KindChoices.TAIL, template="ap##-{tail}"), "template")

    def test_static_cannot_have_run_or_tail(self):
        self.assertInvalid(self.make(kind=KindChoices.STATIC, template="ap##"), "template")
        self.assertInvalid(self.make(kind=KindChoices.STATIC, template="ap-{tail}"), "template")

    def test_self_reference(self):
        self.assertInvalid(self.make(template="{name}-##"), "template")
        self.assertInvalid(
            self.make(target_field=TargetFieldChoices.ASSET_TAG, template="{asset_tag}-##"),
            "template",
        )

    def test_one_way_dependency_allowed(self):
        self.make(name="tag", target_field=TargetFieldChoices.ASSET_TAG, template="at###").save()
        self.make(template="{asset_tag}-##").full_clean()

    def test_cycle_with_other_target_field(self):
        self.make(
            name="tag",
            target_field=TargetFieldChoices.ASSET_TAG,
            kind=KindChoices.STATIC,
            template="{name}-x",
            role=None,
            device_type=self.device_type,
        ).save()
        # Role-only slot overlaps the type-only slot: a device can match both.
        self.assertInvalid(self.make(template="{asset_tag}-##"), "template")

    def test_no_cycle_for_disjoint_slots(self):
        self.make(
            name="tag",
            target_field=TargetFieldChoices.ASSET_TAG,
            kind=KindChoices.STATIC,
            template="{name}-x",
        ).save()
        self.make(name="other", template="{asset_tag}-##", role=self.other_role).full_clean()

    def test_editing_a_convention_ignores_itself(self):
        convention = self.make(
            target_field=TargetFieldChoices.ASSET_TAG, kind=KindChoices.STATIC, template="{name}-x"
        )
        convention.save()
        convention.full_clean()

    def test_unknown_custom_field(self):
        self.assertInvalid(self.make(template="{cf_rack_unit}-##"), "template")

    def test_existing_custom_field(self):
        field = CustomField.objects.create(name="rack_unit", type="text")
        field.object_types.set([ObjectType.objects.get_for_model(Device)])
        self.make(template="{cf_rack_unit}-##").full_clean()

    def test_tail_max_length_only_for_tail(self):
        self.assertInvalid(self.make(tail_max_length=8), "tail_max_length")


class ConstraintTest(ModelTestBase):
    def test_check_constraint_needs_role_or_device_type(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(role=None).save()

    def test_unique_slot_with_null_device_type(self):
        self.make().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(name="dupe").save()

    def test_unique_slot_with_null_role(self):
        self.make(role=None, device_type=self.device_type).save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(name="dupe", role=None, device_type=self.device_type).save()

    def test_slot_is_per_target_field_role_and_type(self):
        self.make().save()
        self.make(name="tag", target_field=TargetFieldChoices.ASSET_TAG).save()
        self.make(name="other-role", role=self.other_role).save()
        self.make(name="typed", device_type=self.device_type).save()
        self.assertEqual(NamingConvention.objects.count(), 4)

    def test_name_is_unique(self):
        self.make().save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make(role=self.other_role).save()

    def test_defaults(self):
        convention = self.make()
        self.assertEqual(convention.counter_scope, CounterScopeChoices.GLOBAL)
        self.assertIsNone(convention.tail_max_length)


class ProtectTest(ModelTestBase):
    def test_role_delete_is_protected(self):
        self.make().save()
        with self.assertRaises(ProtectedError):
            self.role.delete()

    def test_device_type_delete_is_protected(self):
        self.make(device_type=self.device_type).save()
        with self.assertRaises(ProtectedError):
            self.device_type.delete()

    def test_unreferenced_role_deletes(self):
        self.make().save()
        self.other_role.delete()


class NamingCounterTest(TestCase):
    def test_default_and_unique_scope_key(self):
        counter = NamingCounter.objects.create(scope_key="name|global|-|ap|2|")
        self.assertEqual(counter.last_value, 0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            NamingCounter.objects.create(scope_key=counter.scope_key)
