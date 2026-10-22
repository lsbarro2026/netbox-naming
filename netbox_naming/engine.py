"""Naming engine: find a convention, render it, and number it.

`preview` reads and never writes; `allocate` spends numbers under row locks in one transaction.
Neither saves a Device: the caller writes the values. See core plan, "Nesting", "Numbering and
counter storage" and "Engine API".
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from dcim.models import Device, DeviceRole, DeviceType, Location, Platform, Rack, Site
from django.db import transaction
from django.db.models.functions import Lower
from tenancy.models import Tenant

from .choices import CounterScopeChoices, TargetFieldChoices
from .exceptions import (
    Conflict,
    InvalidTail,
    MissingToken,
    NumbersExhausted,
    TemplateError,
    TooLong,
)
from .models import NamingConvention, NamingCounter
from .templating import TAIL, Literal, NumberRun, Token, parse_template, resolve_token

__all__ = ("NamingContext", "Proposal", "allocate", "find_convention", "preview")

_NESTABLE = frozenset(TargetFieldChoices.values())
_TAIL_RE = re.compile(r"[A-Za-z0-9._-]+")
# Separates the pattern pieces of a scope key; PostgreSQL text rejects NUL (plan Deviations, B3).
_KEY_SEP = "\x1f"


@dataclass(frozen=True)
class NamingContext:
    role: DeviceRole | None = None
    device_type: DeviceType | None = None
    site: Site | None = None
    location: Location | None = None
    rack: Rack | None = None
    tenant: Tenant | None = None
    platform: Platform | None = None
    serial: str = ""
    custom_fields: Mapping[str, object] = field(default_factory=dict)
    asset_tag: str | None = None
    name: str | None = None

    @classmethod
    def from_device(cls, device):
        return cls(
            role=device.role,
            device_type=device.device_type,
            site=device.site,
            location=device.location,
            rack=device.rack,
            tenant=device.tenant,
            platform=device.platform,
            serial=device.serial or "",
            custom_fields=dict(device.custom_field_data or {}),
            asset_tag=device.asset_tag,
            name=device.name,
        )


@dataclass(frozen=True)
class Proposal:
    value: str
    number: int | None  # None for static / tail
    conflict: bool  # value (or a nested value) already taken in its uniqueness domain
    parts: dict[str, str] = field(default_factory=dict)  # nested values, e.g. {"asset_tag": "ap07"}


def find_convention(target_field, role, device_type):
    """The most specific convention for `target_field`: role + type, then type only, then role only."""
    slots = []
    if role is not None and device_type is not None:
        slots.append({"role": role, "device_type": device_type})
    if device_type is not None:
        slots.append({"role": None, "device_type": device_type})
    if role is not None:
        slots.append({"role": role, "device_type": None})
    for slot in slots:
        convention = NamingConvention.objects.filter(target_field=target_field, **slot).first()
        if convention is not None:
            return convention
    return None


def preview(convention, context, count=1, *, tail=None):
    """Return the next `count` proposals without taking locks or writing anything."""
    return _generate(convention, context, count, tail, lock=False, depth=0)


def allocate(convention, context, count=1, *, tail=None):
    """Return the next `count` proposals and spend their numbers, atomically."""
    with transaction.atomic():
        return _generate(convention, context, count, tail, lock=True, depth=0)


def _generate(convention, context, count, tail, *, lock, depth):
    if count < 1:
        raise ValueError("count must be at least 1")
    target = convention.target_field
    parts = parse_template(convention.template)
    if tail and Token(TAIL) in parts:
        _check_tail(tail, convention)

    # Dependencies first, so in `allocate` their counters are locked before this one's.
    nested = _nested(parts, convention, context, count, tail, lock=lock, depth=depth)
    rows = []
    for i in range(count):
        row_parts = {name: proposals[i].value for name, proposals in nested.items()}
        nested_conflict = any(proposals[i].conflict for proposals in nested.values())
        rows.append((*_render(parts, context, tail, row_parts), row_parts, nested_conflict))

    if any(isinstance(p, NumberRun) for p in parts):
        return _numbered(convention, context, rows, lock=lock)
    return _fixed(target, context, rows, lock=lock)


def _nested(parts, convention, context, count, tail, *, lock, depth):
    """Proposals for each `{name}` / `{asset_tag}` the context has no value for, keyed by field."""
    nested = {}
    for part in parts:
        if not isinstance(part, Token) or part.name not in _NESTABLE or part.name in nested:
            continue
        if resolve_token(part.name, context):
            continue
        if part.name == convention.target_field or depth >= 1:
            raise TemplateError(f"{{{part.name}}} would nest more than one level deep")
        dependency = find_convention(part.name, context.role, context.device_type)
        if dependency is None:
            raise MissingToken(part.name)
        nested[part.name] = _generate(dependency, context, count, tail, lock=lock, depth=depth + 1)
    return nested


def _render(parts, context, tail, nested):
    """Render every non-number part; return (prefix, width or None, suffix)."""
    before, after = [], []
    width = None
    for part in parts:
        if isinstance(part, NumberRun):
            width = part.width
            continue
        if isinstance(part, Literal):
            text = part.text
        else:
            text = resolve_token(part.name, context, tail=tail) or nested.get(part.name)
            if not text:
                raise MissingToken(part.name)
        (before if width is None else after).append(text)
    return "".join(before), width, "".join(after)


def _check_tail(tail, convention):
    if not _TAIL_RE.fullmatch(tail):
        raise InvalidTail(f"Tail {tail!r} may contain only letters, digits, '.', '_' and '-'")
    limit = convention.tail_max_length
    if limit is not None and len(tail) > limit:
        raise InvalidTail(f"Tail {tail!r} is longer than {limit} characters")


def _check_length(value, target):
    limit = Device._meta.get_field(target).max_length
    if len(value) > limit:
        raise TooLong(f"{value!r} is {len(value)} characters; {target} allows {limit}")


def _domain(target, context):
    """Devices a value for `target` must be unique among: asset_tag globally, name per site+tenant."""
    if target == TargetFieldChoices.ASSET_TAG:
        return Device.objects.all()
    return Device.objects.filter(site=context.site, tenant=context.tenant)


def _fixed(target, context, rows, *, lock):
    """Static and tail values: flag (preview) or refuse (allocate) values already taken."""
    values = [prefix + suffix for prefix, _, suffix, _, _ in rows]
    for value in values:
        _check_length(value, target)
    if target == TargetFieldChoices.NAME:
        fold = str.lower
        taken = set(
            _domain(target, context)
            .annotate(folded=Lower("name"))
            .filter(folded__in={v.lower() for v in values})
            .values_list("folded", flat=True)
        )
    else:
        fold = str
        taken = set(
            _domain(target, context)
            .filter(asset_tag__in=values)
            .values_list("asset_tag", flat=True)
        )

    proposals = []
    seen = set()
    for value, (_, _, _, row_parts, nested_conflict) in zip(values, rows, strict=True):
        key = fold(value)
        conflict = nested_conflict or key in taken or key in seen
        seen.add(key)
        if conflict and lock:
            raise Conflict(f"{value!r} is already taken")
        proposals.append(Proposal(value, None, conflict, row_parts))
    return proposals


def _numbered(convention, context, rows, *, lock):
    target = convention.target_field
    scope_filter, scope_pk = _counter_scope(convention, context)
    keys = {
        (prefix, width, suffix): _scope_key(
            target, convention.counter_scope, scope_pk, prefix, width, suffix
        )
        for prefix, width, suffix, _, _ in rows
    }
    # Sorted, so concurrent allocations lock counters in the same order.
    sequences = {
        pattern: _Sequence(target, context, scope_filter, key, *pattern, lock=lock)
        for pattern, key in sorted(keys.items(), key=lambda item: item[1])
    }

    proposals = []
    for prefix, width, suffix, row_parts, nested_conflict in rows:
        number = sequences[(prefix, width, suffix)].take()
        value = f"{prefix}{number:0{width}d}{suffix}"
        _check_length(value, target)
        # Under `allocate` a conflicting dependency has already raised Conflict.
        proposals.append(Proposal(value, number, nested_conflict, row_parts))
    if lock:
        for sequence in sequences.values():
            sequence.save()
    return proposals


def _counter_scope(convention, context):
    """(Device filter, scope pk) for the convention's counter scope."""
    if convention.counter_scope == CounterScopeChoices.SITE:
        if context.site is None:
            raise MissingToken("site")
        return {"site": context.site}, context.site.pk
    if convention.counter_scope == CounterScopeChoices.LOCATION:
        if context.location is None:
            raise MissingToken("location")
        return {"location": context.location}, context.location.pk
    return {}, None


def _scope_key(target, counter_scope, scope_pk, prefix, width, suffix):
    key = f"{target}|{counter_scope}|{scope_pk or '-'}|{prefix}{_KEY_SEP}{width}{_KEY_SEP}{suffix}"
    if len(key) > NamingCounter._meta.get_field("scope_key").max_length:
        key = "sha256:" + hashlib.sha256(key.encode()).hexdigest()
    return key


def _taken_numbers(queryset, target, prefix, width, suffix):
    """Numbers held by `queryset` devices whose `target` matches prefix, width digits, suffix."""
    pattern = f"^{re.escape(prefix)}([0-9]{{{width}}}){re.escape(suffix)}$"
    if target == TargetFieldChoices.NAME:
        lookup, compiled = "iregex", re.compile(pattern, re.IGNORECASE)
    else:
        lookup, compiled = "regex", re.compile(pattern)
    values = queryset.filter(**{f"{target}__{lookup}": pattern}).values_list(target, flat=True)
    return {int(match.group(1)) for value in values if (match := compiled.fullmatch(value))}


class _Sequence:
    """Hands out numbers for one rendered pattern: past the counter and the scan, skipping taken."""

    def __init__(self, target, context, scope_filter, key, prefix, width, suffix, *, lock):
        self.pattern = f"{prefix}{'#' * width}{suffix}"
        if lock:
            NamingCounter.objects.get_or_create(scope_key=key)
            self.counter = NamingCounter.objects.select_for_update().get(scope_key=key)
            last_value = self.counter.last_value
        else:
            self.counter = None
            last_value = (
                NamingCounter.objects.filter(scope_key=key)
                .values_list("last_value", flat=True)
                .first()
                or 0
            )
        # Scanned after the lock, so a concurrent allocation's committed devices are seen.
        scanned = _taken_numbers(
            Device.objects.filter(**scope_filter), target, prefix, width, suffix
        )
        self.taken = _taken_numbers(_domain(target, context), target, prefix, width, suffix)
        self.next = max(last_value, max(scanned, default=0)) + 1
        self.limit = 10**width
        self.highest = None

    def take(self):
        number = self.next
        while number in self.taken:
            number += 1
        if number >= self.limit:
            raise NumbersExhausted(f"{self.pattern} has no numbers left")
        self.next = number + 1
        self.highest = number
        return number

    def save(self):
        if self.highest is not None:
            self.counter.last_value = self.highest
            self.counter.save(update_fields=["last_value"])
