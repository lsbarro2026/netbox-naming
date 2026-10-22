"""Whitelist template parser and token registry.

Templates are data that any user with model permissions can edit, so they are never handed to
``str.format`` or a template engine. The parser accepts only literals, ``{token}`` references to the
registry below, one ``#``-run and a trailing ``{tail}``; nothing is evaluated. See core plan, "Token
grammar".
"""

import re
from dataclasses import dataclass

from .exceptions import TemplateError

MAX_NUMBER_WIDTH = 9
TAIL = "tail"
CF_PREFIX = "cf_"

_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
_CF_NAME_RE = re.compile(r"cf_[a-z0-9_]+")
_FORBIDDEN_IN_BRACES = frozenset(".[:!")


@dataclass(frozen=True)
class Literal:
    text: str


@dataclass(frozen=True)
class Token:
    name: str


@dataclass(frozen=True)
class NumberRun:
    width: int


Part = Literal | Token | NumberRun


def _chain(obj, *attrs):
    for attr in attrs:
        if obj is None:
            return None
        obj = getattr(obj, attr, None)
    return obj


def _attr(*path):
    """Resolver reading ``context.<path>``; None when any hop is None."""
    return lambda ctx, tail: _chain(ctx, *path)


def _serial(ctx, tail):
    return _chain(ctx, "serial") or None


# Each entry maps (context, tail) to str | None. `asset_tag` and `name` return only the context's own
# value; the engine falls back to the nested convention when they are None.
TOKENS = {
    "room": _attr("location", "name"),
    "location_slug": _attr("location", "slug"),
    "site": _attr("site", "name"),
    "site_slug": _attr("site", "slug"),
    "role": _attr("role", "name"),
    "role_slug": _attr("role", "slug"),
    "device_type": _attr("device_type", "model"),
    "device_type_slug": _attr("device_type", "slug"),
    "manufacturer": _attr("device_type", "manufacturer", "name"),
    "manufacturer_slug": _attr("device_type", "manufacturer", "slug"),
    "rack": _attr("rack", "name"),
    "tenant": _attr("tenant", "name"),
    "tenant_slug": _attr("tenant", "slug"),
    "platform": _attr("platform", "name"),
    "platform_slug": _attr("platform", "slug"),
    "serial": _serial,
    "asset_tag": _attr("asset_tag"),
    "name": _attr("name"),
    TAIL: lambda ctx, tail: tail,
}


def is_known_token(name):
    return name in TOKENS or _CF_NAME_RE.fullmatch(name) is not None


def resolve_token(name, context, *, tail=None):
    """Return the token's value for `context`, or None when it has none."""
    resolver = TOKENS.get(name)
    if resolver is not None:
        return resolver(context, tail)
    if _CF_NAME_RE.fullmatch(name):
        value = (_chain(context, "custom_fields") or {}).get(name[len(CF_PREFIX) :])
        return None if value is None else str(value)
    raise TemplateError(f"Unknown token {{{name}}}")


def cf_token_names(parts):
    """Custom field names referenced by `{cf_<name>}` tokens, in order."""
    return [
        p.name[len(CF_PREFIX) :]
        for p in parts
        if isinstance(p, Token) and p.name not in TOKENS and p.name.startswith(CF_PREFIX)
    ]


def _parse_token(template, start):
    """Parse the token whose `{` is at `start`; return (Token, index after `}`)."""
    for i in range(start + 1, len(template)):
        char = template[i]
        if char == "}":
            break
        if char in "{#":
            raise TemplateError(f"Unbalanced '{{' at position {start}")
    else:
        raise TemplateError(f"Unbalanced '{{' at position {start}")
    inner = template[start + 1 : i]
    if not inner:
        raise TemplateError(f"Empty token at position {start}")
    for offset, char in enumerate(inner):
        if char in _FORBIDDEN_IN_BRACES or char.isspace():
            raise TemplateError(
                f"Character {char!r} is not allowed inside braces (position {start + 1 + offset})"
            )
    if not _NAME_RE.fullmatch(inner):
        raise TemplateError(f"Invalid token name {inner!r} at position {start}")
    if not is_known_token(inner):
        raise TemplateError(f"Unknown token {{{inner}}} at position {start}")
    return Token(inner), i + 1


def parse_template(template):
    """Parse `template` into a list of Literal / Token / NumberRun parts, or raise TemplateError."""
    parts = []
    seen_run = False
    pos = 0
    while pos < len(template):
        char = template[pos]
        if char == "{":
            part, pos = _parse_token(template, pos)
            parts.append(part)
        elif char == "}":
            raise TemplateError(f"Unbalanced '}}' at position {pos}")
        elif char == "#":
            end = pos
            while end < len(template) and template[end] == "#":
                end += 1
            if seen_run:
                raise TemplateError(f"Only one '#' run is allowed (second at position {pos})")
            if end - pos > MAX_NUMBER_WIDTH:
                raise TemplateError(
                    f"A '#' run may be at most {MAX_NUMBER_WIDTH} wide (position {pos})"
                )
            seen_run = True
            parts.append(NumberRun(end - pos))
            pos = end
        else:
            end = pos
            while end < len(template) and template[end] not in "{}#":
                end += 1
            parts.append(Literal(template[pos:end]))
            pos = end
    if not parts:
        raise TemplateError("Template is empty")
    if Token(TAIL) in parts[:-1]:
        raise TemplateError("{tail} must be the last part of the template")
    return parts
