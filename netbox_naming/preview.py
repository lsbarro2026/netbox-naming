"""Template preview for the convention editor and the detail page's sample values.

Reports only: it parses, runs the model's `clean()` and calls `engine.preview`, never `allocate`, and
writes nothing. The model's `clean()` stays the authority on save. See management-ui plan, "Live
template editor (M3)".
"""

import re
from dataclasses import dataclass, field

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError

from .choices import KindChoices, TargetFieldChoices
from .engine import Proposal, preview
from .exceptions import MissingToken, NamingError, TemplateError
from .templating import TAIL, Literal, NumberRun, Token, parse_template, resolve_token

__all__ = ("SAMPLE_COUNT", "TemplatePreview", "preview_convention")

SAMPLE_COUNT = 5

# Core's TemplateError carries its offset only in the message (plan Deviations, M3).
_POSITION_RE = re.compile(r"position (\d+)")
# Tokens a Location (and the Site it implies) gives a value to; `location` is the counter scope's.
_LOCATION_TOKENS = frozenset({"room", "location_slug", "site", "site_slug", "location"})
_NESTABLE = frozenset(TargetFieldChoices.values())


@dataclass(frozen=True)
class TemplatePreview:
    template: str
    error_span: tuple[str, str, str] | None = None  # (before, offending, after)
    messages: list[str] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    shape: str | None = None  # set when the values can't be computed yet


def preview_convention(convention, context, *, tail=None) -> TemplatePreview:
    """Up to SAMPLE_COUNT sample values for `convention` (saved or not), or why there are none."""
    template = convention.template or ""
    if not template:
        return TemplatePreview(template, messages=["Type a template to see sample values."])
    try:
        parts = parse_template(template)
    except TemplateError as exc:
        return TemplatePreview(template, _error_span(template, str(exc)), [str(exc)])

    if (
        convention.kind not in KindChoices.values()
        or convention.target_field not in TargetFieldChoices.values()
    ):
        return TemplatePreview(template, messages=["Pick a kind and a target field to see values."])

    messages = []
    try:
        convention.clean()
    except ValidationError as exc:
        errors = (
            exc.message_dict if hasattr(exc, "error_dict") else {NON_FIELD_ERRORS: exc.messages}
        )
        messages = [m for field_errors in errors.values() for m in field_errors]
        implied = _implied_kind(parts)
        if implied != convention.kind:
            messages.append(
                f"This template looks like a {dict(KindChoices.CHOICES)[implied].lower()} convention."
            )
        if "template" in errors:
            return TemplatePreview(template, messages=messages)

    numbered = any(isinstance(p, NumberRun) for p in parts)
    # A static or tail convention renders one value however many rows are asked for.
    count = SAMPLE_COUNT if numbered else 1
    try:
        proposals = preview(convention, context, count, tail=tail or None)
    except MissingToken as exc:
        shape, missing = _shape(parts, context, tail)
        hints = _hints(missing | {exc.token}, exc.token, numbered)
        return TemplatePreview(template, messages=messages + hints, shape=shape)
    except NamingError as exc:
        return TemplatePreview(template, messages=[*messages, str(exc)])
    return TemplatePreview(template, messages=messages, proposals=proposals)


def _error_span(template, message):
    """Split `template` around the part the error names: a `{token}`, a `#`-run or one character."""
    match = _POSITION_RE.search(message)
    if match is None or int(match.group(1)) >= len(template):
        return None
    start = end = int(match.group(1))
    if template[start] == "{":
        close = template.find("}", start)
        end = close + 1 if close != -1 else len(template)
    elif template[start] == "#":
        while end < len(template) and template[end] == "#":
            end += 1
    else:
        end = start + 1
    return template[:start], template[start:end], template[end:]


def _implied_kind(parts):
    if any(isinstance(p, NumberRun) for p in parts):
        return KindChoices.NUMBERED
    if parts[-1] == Token(TAIL):
        return KindChoices.TAIL
    return KindChoices.STATIC


def _shape(parts, context, tail):
    """The template rendered as far as the context allows; returns (shape, unresolved token names).

    Never shows a number: it depends on the rendered prefix.
    """
    pieces, missing = [], set()
    for part in parts:
        if isinstance(part, Literal):
            pieces.append(part.text)
        elif isinstance(part, NumberRun):
            pieces.append("#" * part.width)
        elif value := resolve_token(part.name, context, tail=tail):
            pieces.append(value)
        else:
            pieces.append(f"‹{part.name}›")
            missing.add(part.name)
    return "".join(pieces), missing


def _hints(names, cause, numbered):
    what = "numbers" if numbered else "values"
    hints = []
    if names & _LOCATION_TOKENS:
        hints.append(f"Needs a Location to show real {what}.")
    if TAIL in names:
        hints.append(f"Enter a sample tail to show real {what}.")
    if cause in _NESTABLE:
        label = dict(TargetFieldChoices.CHOICES)[cause].lower()
        hints.append(
            f"No {label} convention matches this role and device type, so {{{cause}}} is empty."
        )
    rest = sorted(names - _LOCATION_TOKENS - _NESTABLE - {TAIL})
    if rest:
        hints.append(
            f"{', '.join(f'{{{n}}}' for n in rest)}: filled in from the device being named."
        )
    return hints
