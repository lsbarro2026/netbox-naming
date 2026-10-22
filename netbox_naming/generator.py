"""Read-only generator service: inventory of values in use and "next N" proposals.

Only `preview` and `find_convention` are used from the engine; this module never imports `allocate`,
so nothing here spends a number. See name-generator plan, "Decision" and "Service".
"""

import dataclasses
import re
from collections.abc import Iterable
from dataclasses import dataclass

from dcim.models import Device, Location, Site
from django.db.models import QuerySet

from .choices import CounterScopeChoices, TargetFieldChoices
from .engine import NamingContext, Proposal, find_convention, preview
from .exceptions import MissingToken, NamingError
from .models import NamingConvention
from .templating import TAIL, Literal, NumberRun, parse_template

__all__ = (
    "MAX_COUNT",
    "NUMBER",
    "GeneratedRow",
    "Generation",
    "Inventory",
    "Series",
    "TakenValue",
    "collapse_ranges",
    "generate",
    "inventory",
    "series_pattern",
)

MAX_COUNT = 50
# Group name `series_pattern` gives the `#`-run.
NUMBER = "#"

_TAIL_GROUP = "([A-Za-z0-9._-]+)"
# Tokens a Location (and the Site it implies) gives a value to.
_LOCATION_TOKENS = frozenset({"room", "location_slug", "site", "site_slug", "location"})
_FIELD_LABELS = {TargetFieldChoices.NAME: "name", TargetFieldChoices.ASSET_TAG: "asset tag"}


@dataclass(frozen=True)
class TakenValue:
    device: Device
    value: str
    number: int | None  # None for static / tail conventions


@dataclass(frozen=True)
class Series:
    label: str  # rendered pattern, e.g. "ap##" or "lon-sw##"
    scope: Site | Location | None
    taken: list[TakenValue]  # sorted by number, then value
    ranges: list[tuple[int, int]]
    highest: TakenValue | None
    next: Proposal | None  # None when it can't be computed honestly


@dataclass(frozen=True)
class Inventory:
    convention: NamingConvention
    series: list[Series]


@dataclass(frozen=True)
class GeneratedRow:
    index: int
    name: Proposal | None
    asset_tag: Proposal | None


@dataclass(frozen=True)
class Generation:
    name_convention: NamingConvention | None
    asset_tag_convention: NamingConvention | None
    rows: list[GeneratedRow]
    messages: list[str]


def series_pattern(convention):
    """Anchored regex for the convention's values, and the token name (or NUMBER) of each group.

    Built the way engine `_taken_numbers` builds its scan: escaped literals, `[0-9]{w}` for the
    `#`-run, case-insensitive for `name`. The same pattern string is valid for PostgreSQL `__regex`.
    """
    pieces, names = [], []
    for part in parse_template(convention.template):
        if isinstance(part, Literal):
            pieces.append(re.escape(part.text))
        elif isinstance(part, NumberRun):
            pieces.append(f"([0-9]{{{part.width}}})")
            names.append(NUMBER)
        else:
            pieces.append(_TAIL_GROUP if part.name == TAIL else "(.+?)")
            names.append(part.name)
    flags = re.IGNORECASE if convention.target_field == TargetFieldChoices.NAME else 0
    return re.compile(f"^{''.join(pieces)}$", flags), names


def collapse_ranges(numbers: Iterable[int]) -> list[tuple[int, int]]:
    """Sorted, de-duplicated numbers as inclusive (start, end) runs."""
    ranges = []
    for number in sorted(set(numbers)):
        if ranges and number == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], number)
        else:
            ranges.append((number, number))
    return ranges


def inventory(convention, devices: QuerySet[Device]) -> Inventory:
    """Values of `convention`'s target field held by `devices`, grouped into counter series."""
    target = convention.target_field
    pattern, names = series_pattern(convention)
    lookup = "iregex" if target == TargetFieldChoices.NAME else "regex"
    queryset = devices.filter(**{f"{target}__{lookup}": pattern.pattern}).select_related(
        "role",
        "device_type__manufacturer",
        "site",
        "location",
        "rack",
        "tenant",
        "platform",
    )
    matches = [
        (device, match)
        for device in queryset
        if (match := pattern.fullmatch(getattr(device, target)))
    ]
    if NUMBER not in names:
        return Inventory(convention, [_fixed_series(convention, matches)] if matches else [])

    groups = {}
    for device, match in matches:
        scope = _scope(convention, device)
        key = (scope.pk if scope else None, _captures(convention, names, match))
        groups.setdefault(key, (scope, []))[1].append((device, match))
    series = [
        _numbered_series(convention, pattern, names, key, scope, members)
        for key, (scope, members) in groups.items()
    ]
    series.sort(key=lambda s: (s.label.lower(), s.scope.pk if s.scope else 0))
    return Inventory(convention, series)


def _scope(convention, device):
    if convention.counter_scope == CounterScopeChoices.SITE:
        return device.site
    if convention.counter_scope == CounterScopeChoices.LOCATION:
        return device.location
    return None


def _captures(convention, names, match):
    """Token captures (not the number), folded for `name` to match the engine's iregex scan."""
    fold = str.lower if convention.target_field == TargetFieldChoices.NAME else str
    return tuple(
        fold(text) for name, text in zip(names, match.groups(), strict=True) if name != NUMBER
    )


def _fixed_series(convention, matches):
    """Static and tail conventions: one value list, with no numbers or next free."""
    target = convention.target_field
    taken = sorted(
        (TakenValue(device, getattr(device, target), None) for device, _ in matches),
        key=lambda t: t.value,
    )
    return Series(convention.template, None, taken, [], None, None)


def _numbered_series(convention, pattern, names, key, scope, members):
    target = convention.target_field
    position = names.index(NUMBER) + 1
    members = sorted(members, key=lambda m: (int(m[1].group(position)), getattr(m[0], target)))
    taken = [
        TakenValue(device, getattr(device, target), int(match.group(position)))
        for device, match in members
    ]
    first, last = members[0][1], members[-1][1]
    label = (
        first.string[: first.start(position)]
        + NUMBER * len(first.group(position))
        + first.string[first.end(position) :]
    )
    tail = last.group(names.index(TAIL) + 1) if TAIL in names else None
    return Series(
        label=label,
        scope=scope,
        taken=taken,
        ranges=collapse_ranges(t.number for t in taken),
        highest=taken[-1],
        next=_next_free(convention, pattern, names, key, members[-1][0], tail),
    )


def _next_free(convention, pattern, names, key, representative, tail):
    """What `allocate` would hand a device in the series, or None when the representative no longer
    renders into it (it has moved) or the engine can't number it here.

    Only the convention's own target field is cleared, so a nested token keeps the device's value
    (plan Deviations, G1).
    """
    context = dataclasses.replace(
        NamingContext.from_device(representative), **{convention.target_field: None}
    )
    try:
        proposal = preview(convention, context, 1, tail=tail)[0]
    except NamingError:
        return None
    # Series are grouped by the device's current scope, so only the token captures can differ.
    match = pattern.fullmatch(proposal.value)
    if match is None or _captures(convention, names, match) != key[1]:
        return None
    return proposal


def generate(*, role=None, device_type=None, location=None, count=5, tail=None) -> Generation:
    """Preview the next `count` names and asset tags for a role and/or device type, paired by row."""
    if role is None and device_type is None:
        return Generation(None, None, [], ["Pick a role or a device type."])
    count = max(1, min(count, MAX_COUNT))
    context = NamingContext(
        role=role,
        device_type=device_type,
        site=location.site if location is not None else None,
        location=location,
    )
    messages = []
    conventions, columns = {}, {}
    for target in (TargetFieldChoices.NAME, TargetFieldChoices.ASSET_TAG):
        convention = find_convention(target, role, device_type)
        conventions[target] = convention
        if convention is None:
            messages.append(
                f"No {_FIELD_LABELS[target]} convention matches this role and device type."
            )
            columns[target] = []
            continue
        try:
            columns[target] = preview(convention, context, count, tail=tail or None)
        except NamingError as exc:
            columns[target] = []
            message = _error_message(target, exc)
            if message:
                messages.append(message)

    names, tags = columns[TargetFieldChoices.NAME], columns[TargetFieldChoices.ASSET_TAG]
    # A name nesting {asset_tag} gets the same tags as the separate preview: same convention,
    # context, count and tail (plan Deviations, G1).
    rows = [
        GeneratedRow(
            i + 1,
            names[i] if i < len(names) else None,
            tags[i] if i < len(tags) else None,
        )
        for i in range(max(len(names), len(tags)))
    ]
    return Generation(
        conventions[TargetFieldChoices.NAME],
        conventions[TargetFieldChoices.ASSET_TAG],
        rows,
        messages,
    )


def _error_message(target, exc):
    label = _FIELD_LABELS[target]
    if not isinstance(exc, MissingToken):
        return f"{label.capitalize()}: {exc}"
    token = exc.token
    if token in TargetFieldChoices.values():
        # The other field's own "no convention" message already says this.
        return None
    if token in _LOCATION_TOKENS:
        return f"Pick a Location: the {label} template uses {{{token}}}."
    if token == TAIL:
        return f"Enter a tail: the {label} template uses {{{TAIL}}}."
    return f"The {label} template uses {{{token}}}, which has no value here."
