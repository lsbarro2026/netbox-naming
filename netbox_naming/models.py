from core.models import ObjectType
from dcim.models import Device
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from extras.models import CustomField
from netbox.models import PrimaryModel

from .choices import CounterScopeChoices, KindChoices, TargetFieldChoices
from .exceptions import TemplateError
from .templating import TAIL, NumberRun, Token, cf_token_names, parse_template

__all__ = ("NamingConvention", "NamingCounter")


def _referenced_fields(parts):
    """Target fields (`name`, `asset_tag`) that a parsed template references."""
    return {p.name for p in parts if isinstance(p, Token) and p.name in TargetFieldChoices.values()}


class NamingConvention(PrimaryModel):
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=20, choices=KindChoices)
    target_field = models.CharField(max_length=20, choices=TargetFieldChoices)
    template = models.CharField(max_length=200)
    role = models.ForeignKey(
        to="dcim.DeviceRole",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
    )
    device_type = models.ForeignKey(
        to="dcim.DeviceType",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
    )
    counter_scope = models.CharField(
        max_length=20,
        choices=CounterScopeChoices,
        default=CounterScopeChoices.GLOBAL,
        help_text="Only meaningful for numbered conventions",
    )
    tail_max_length = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        help_text="Only meaningful for custom-tail conventions",
    )

    class Meta:
        ordering = ("name",)
        constraints = (
            models.CheckConstraint(
                condition=Q(role__isnull=False) | Q(device_type__isnull=False),
                name="%(app_label)s_%(class)s_role_or_device_type",
            ),
            models.UniqueConstraint(
                fields=("target_field", "role", "device_type"),
                name="%(app_label)s_%(class)s_unique_slot",
                nulls_distinct=False,
            ),
        )

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        if self.role_id is None and self.device_type_id is None:
            raise ValidationError("A convention must name a device role, a device type, or both.")

        try:
            parts = parse_template(self.template)
        except TemplateError as exc:
            raise ValidationError({"template": str(exc)}) from exc

        self._check_kind(parts)

        referenced = _referenced_fields(parts)
        if self.target_field in referenced:
            raise ValidationError(
                {
                    "template": f"The template cannot reference its own target field {{{self.target_field}}}."
                }
            )

        self._check_custom_fields(parts)
        self._check_cycle(referenced)

        if self.tail_max_length is not None and self.kind != KindChoices.TAIL:
            raise ValidationError(
                {
                    "tail_max_length": "A maximum tail length applies only to custom-tail conventions."
                }
            )

    def _check_kind(self, parts):
        runs = sum(isinstance(p, NumberRun) for p in parts)
        ends_in_tail = parts[-1] == Token(TAIL)
        if self.kind == KindChoices.NUMBERED:
            if runs != 1:
                raise ValidationError(
                    {"template": "A numbered convention needs exactly one '#' run in its template."}
                )
        elif self.kind == KindChoices.TAIL:
            if runs or not ends_in_tail:
                raise ValidationError(
                    {"template": "A custom-tail convention must end in {tail} and have no '#' run."}
                )
        elif runs or Token(TAIL) in parts:
            raise ValidationError(
                {"template": "A static convention cannot contain a '#' run or {tail}."}
            )

    def _check_custom_fields(self, parts):
        names = cf_token_names(parts)
        if not names:
            return
        existing = set(
            CustomField.objects.filter(
                object_types=ObjectType.objects.get_for_model(Device)
            ).values_list("name", flat=True)
        )
        missing = [n for n in names if n not in existing]
        if missing:
            raise ValidationError(
                {
                    "template": f"No custom field on dcim.Device named: {', '.join(sorted(set(missing)))}."
                }
            )

    def _check_cycle(self, referenced):
        """Reject a dependency loop with the other target field's conventions.

        The engine picks the nested convention from the device's own role and type, which can be
        more specific than this convention's slot, so every convention whose slot could match the same
        devices is considered.
        """
        compatible = Q()
        if self.role_id:
            compatible &= Q(role__isnull=True) | Q(role_id=self.role_id)
        if self.device_type_id:
            compatible &= Q(device_type__isnull=True) | Q(device_type_id=self.device_type_id)
        for other_field in referenced:
            candidates = NamingConvention.objects.filter(
                compatible, target_field=other_field
            ).exclude(pk=self.pk)
            for other in candidates:
                try:
                    other_parts = parse_template(other.template)
                except TemplateError:
                    continue
                if self.target_field in _referenced_fields(other_parts):
                    raise ValidationError(
                        {
                            "template": f"Referencing {{{other_field}}} forms a cycle with "
                            f"convention '{other.name}', whose template references "
                            f"{{{self.target_field}}}."
                        }
                    )


class NamingCounter(models.Model):
    scope_key = models.CharField(max_length=255, unique=True)
    last_value = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.scope_key}: {self.last_value}"
