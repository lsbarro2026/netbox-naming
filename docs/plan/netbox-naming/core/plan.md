# core — plan

FEAT-2, 2026-10-22. Builds on [`research.md`](research.md) (cited below as F1–F7) and the segment map
and contracts in [`../overview.md`](../overview.md).

## Status

**Approved** (2026-10-22). Draft → Approved → Implemented. The last implementation item (B4) sets
Implemented.

## Decision

**Replace (greenfield: build new) — research verdict confirmed.** There is no code to extend and no
prior art fits (F7). No `adr` sequence is configured, so this section is the decision record.

1. **Scaffold by hand** to the v4.7 plugin docs (research Option 1). Pin `min_version = "4.7.3"`,
   `max_version = "4.7.99"` (F1, and the `packaging.version` gotcha in F2).
2. **Numbering is the hybrid** (F5 option c): under a row lock on the counter,
   `next = max(counter.last_value, scan_max) + 1`, then skip any value already taken in the target
   field's uniqueness domain. Numbers are monotonic and never reused.
3. **Rendering uses a whitelist parser**, never `str.format`, `format_map`, `string.Template` or
   Jinja2 (F6).
4. **Custom tail is free text** the user types when previewing or allocating, filling a `{tail}` token
   that must end the template (research open question 1, proposal taken). **Override of the research
   proposal:** the allowed characters are a fixed set, `[A-Za-z0-9._-]`, plus a per-convention maximum
   length. A per-convention regex is not stored, because a user-written regex run by Python's `re` is a
   ReDoS vector and conventions are editable by any user with model permissions (F6).

Other research open questions, settled here:

- Q2 — `allocate` is built to the Engine API contract but **nothing in `core` writes onto a Device**
  (no save hook, no apply action). Whether a later segment should call it is outside this plan.
- Q3 — no gap reuse (monotonic). Q4 — overflow refuses with an error. Q5 — a null token refuses to
  render. Q6 — `{room}` reads `Location.name`. Q7 — the type is explicit and validated against the
  template.
- A convention must name a device role, a device type, or both: there is no catch-all convention.
- Role and device-type foreign keys are `PROTECT`, so deleting a role can't silently widen a
  convention to more devices.

No re-segmentation is needed: every contract in overview.md holds as written.

## Design

### Scaffold and dev/test environment

- `pyproject.toml`: setuptools backend, `name = "netbox-naming"`, `requires-python = ">=3.12"`, no
  runtime dependencies beyond NetBox itself, Ruff config (line length 100). Package data includes
  `migrations/`.
- `netbox_naming/__init__.py`: `NetBoxNamingConfig(PluginConfig)` with `name = "netbox_naming"`,
  `verbose_name = "Naming Conventions"`, `base_url = "naming"`, `min_version`/`max_version` as above;
  `config = NetBoxNamingConfig`. Only documented plugin API is imported (F2).
- `netbox_naming/tests/` holds all tests (NetBox's test runner discovers them).
- `dev/`: a self-contained Docker Compose environment — PostgreSQL 17, Redis 7 and the
  `netboxcommunity/netbox` image for NetBox v4.7.3 (exact image tag fixed in B1). The repo is
  bind-mounted at `/opt/netbox-naming` and `pip install -e`'d into the image's venv at start-up.
  `dev/configuration/plugins.py` sets `PLUGINS = ["netbox_naming"]`; `DEVELOPER = True` so
  `makemigrations` works (research "Current implementation"). `dev/README.md` gives the three commands:
  bring it up, `makemigrations netbox_naming`, and `manage.py test netbox_naming --keepdb`.
- `COMPATIBILITY.md`: one row, plugin 0.1.x ↔ NetBox 4.7.3–4.7.x (F2 recommendation).

### Models (`netbox_naming/models.py`, choices in `netbox_naming/choices.py`)

`NamingConvention(PrimaryModel)` — `PrimaryModel` adds `description`, `comments`, `owner`, tags,
custom fields and change logging (F2).

| Field | Type | Notes |
|---|---|---|
| `name` | `CharField(100, unique=True)` | Human label |
| `kind` | `CharField` choices `static` / `numbered` / `tail` | The request's three types |
| `target_field` | `CharField` choices `name` / `asset_tag` | Device field the convention produces |
| `template` | `CharField(200)` | Grammar below |
| `role` | `FK dcim.DeviceRole, null, PROTECT` | |
| `device_type` | `FK dcim.DeviceType, null, PROTECT` | |
| `counter_scope` | `CharField` choices `global` / `site` / `location`, default `global` | Only meaningful for `numbered` |
| `tail_max_length` | `PositiveSmallIntegerField(null)` | Only meaningful for `tail`; null = limited only by the field length |

Constraints: a `CheckConstraint` that `role` or `device_type` is set; a `UniqueConstraint` on
`(target_field, role, device_type)` with `nulls_distinct=False`, so each specificity slot holds at most
one convention per target field.

`clean()` parses the template and rejects:
- a kind that disagrees with the template's shape: `numbered` ⇔ exactly one `#`-run; `tail` ⇔ ends in
  `{tail}` and has no `#`-run; `static` ⇔ neither;
- a template that references its own target field, or a cycle with the other target field's matching
  convention (`name` ⇄ `asset_tag`);
- a `{cf_<x>}` token whose custom field doesn't exist on `dcim.Device`;
- non-null `tail_max_length` on a non-tail convention.

Counter scope is allowed for either target field: the engine skips candidates that collide in the
field's uniqueness domain, so a site-scoped `asset_tag` counter can't hand out a duplicate.

`NamingCounter(models.Model)` — a plain Django model (no change logging, not exposed in pickers):
`scope_key = CharField(255, unique=True)`, `last_value = PositiveIntegerField(default=0)`.

### Matching

The convention for a `(target_field, role, device_type)` is the most specific match:
role + type, then type only, then role only. Role matching is exact — ltree ancestors are not
consulted (F1).

### Token grammar (`netbox_naming/templating.py`)

```
template := part*
part     := literal | token | numrun
token    := "{" NAME "}"        NAME := [a-z][a-z0-9_]*, a key of the registry
numrun   := "#"{1,9}            at most one per template; width = run length
literal  := any run of characters other than "{", "}", "#"
```

- No escapes: `{`, `}` and `#` cannot appear literally.
- `{tail}` must be the last part.
- Rejected when the convention is saved (and again on render): unknown tokens, any of `. [ : !` or
  whitespace inside braces, unbalanced braces, a second `#`-run, a run longer than 9.
- The parser returns a list of typed parts; nothing is evaluated.

Token registry (each entry is a function of the context returning `str | None`), from F3:

| Token | Source |
|---|---|
| `room`, `location_slug` | `location.name`, `location.slug` |
| `site`, `site_slug` | `site.name`, `.slug` |
| `role`, `role_slug` | `role.name`, `.slug` |
| `device_type`, `device_type_slug` | `device_type.model`, `.slug` |
| `manufacturer`, `manufacturer_slug` | `device_type.manufacturer.name`, `.slug` |
| `rack` | `rack.name` |
| `tenant`, `tenant_slug` | `tenant.name`, `.slug` |
| `platform`, `platform_slug` | `platform.name`, `.slug` |
| `serial` | `serial` (empty string counts as null) |
| `asset_tag`, `name` | context value, else nested convention (below) |
| `tail` | the caller's `tail` argument |
| `cf_<name>` | raw stored `custom_field_data[<name>]`, stringified |

### Rendering rules

- A token that resolves to `None` or `""` raises `MissingToken` naming the token — no silent `-ap01`.
- A number that needs more digits than the run raises `NumbersExhausted`.
- A rendered value longer than 64 (`name`) or 50 (`asset_tag`) raises `TooLong` (F3).
- A tail outside `[A-Za-z0-9._-]+` or longer than `tail_max_length` raises `InvalidTail`.

### Nesting

`{asset_tag}` / `{name}` take the context's value when it is set. Otherwise the engine finds the
matching convention for that field and renders it first — in `preview`, the i-th dependent value pairs
with the i-th outer value; in `allocate`, the dependency is allocated first in the same transaction.
Depth is at most 1, since there are only two target fields and cycles are rejected at save.

### Numbering and counter storage

- **Pattern.** Render every non-number part; the result is `prefix`, `#`-run of width `w`, `suffix`.
- **Scope key** = `"{target_field}|{counter_scope}|{scope_pk or '-'}|{prefix}\x00{w}\x00{suffix}"`,
  hashed to fit 255 when longer. Two conventions that render the same pattern share one counter.
- **Scan.** Devices in the counter scope (all / `site=` / `location=`) whose target field matches
  `^{re.escape(prefix)}(\d{w}){re.escape(suffix)}$` — `__regex` for `asset_tag`, `__iregex` for `name`
  (F4, Risks). `scan_max` is the largest captured number, 0 if none.
- **Uniqueness domain** for collision skipping: `asset_tag` globally, exact; `name` per
  `(site, tenant)`, case-insensitive (F4). The taken set is fetched once per call.
- **Candidates**: `max(counter.last_value, scan_max) + 1`, upward, skipping taken values.
- **Preview** reads the counter (no row → 0) with no lock and no write.
- **Allocate** runs in `transaction.atomic()`: `get_or_create(scope_key=…)`, then
  `select_for_update().get(…)`, compute candidates, set `last_value` to the highest one handed out,
  save. Dependency counters are locked before the outer one, so lock order is fixed.

### Engine API (`netbox_naming/engine.py`)

```python
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
    def from_device(cls, device: Device) -> "NamingContext": ...

@dataclass(frozen=True)
class Proposal:
    value: str
    number: int | None          # None for static / tail
    conflict: bool              # value already taken in the uniqueness domain
    parts: dict[str, str]       # nested values, e.g. {"asset_tag": "ap07"}

def find_convention(target_field: str, role, device_type) -> NamingConvention | None
def preview(convention, context, count=1, *, tail=None) -> list[Proposal]   # no locks, no writes
def allocate(convention, context, count=1, *, tail=None) -> list[Proposal]  # atomic, spends numbers
```

- `numbered` proposals never conflict (taken values are skipped). `static` and `tail` proposals are
  returned with `conflict=True` when taken, never hidden; `allocate` raises `Conflict` instead.
- `allocate` does not save a Device; the caller writes the values.
- Errors: `NamingError` base, with `TemplateError`, `MissingToken`, `NumbersExhausted`, `TooLong`,
  `InvalidTail`, `Conflict`. They live in `netbox_naming/exceptions.py` so forms can map them.

## Contracts

All five contracts in [overview.md § Contracts](../overview.md#contracts) are met as written:
Convention model and Number placeholder → [Models](#models-netbox_namingmodelspy-choices-in-netbox_namingchoicespy)
and [Token grammar](#token-grammar-netbox_namingtemplatingpy); Nesting → [Nesting](#nesting);
Engine API → [Engine API](#engine-api-netbox_namingenginepy); URLs → `base_url = "naming"`.
Consumers (`management-ui` FEAT-3/4, `name-generator` FEAT-5) build against the signatures above.

## Test strategy

All tests run in the `dev/` container against PostgreSQL (`manage.py test netbox_naming --keepdb`).

- **Parser and registry** — `SimpleTestCase` table tests: valid templates, every rejection rule, the
  F6 injection strings (`{x.__class__}`, `{x[0]}`, `{x:>999999}`, `{x!r}`).
- **Model validation** — `TestCase`: each `clean()` rule, both constraints, PROTECT on role delete.
- **Engine** — `TestCase` with dcim fixtures: matching precedence; scan with hand-entered values
  (`ap01-old`, `xap05` ignored); collision skipping in both uniqueness domains; nesting
  (`{room}-{asset_tag}` with `ap##`); preview leaves the counter untouched; every error path.
- **Concurrency** — `TransactionTestCase`: two threads allocate on one counter and get distinct
  numbers; the first allocation creates the counter row without a race (F5, research Risks).

## Implementation breakdown

Filed as a chain; B1 waits on FEAT-2.

### B1. Scaffold and dev environment

- **Scope:** `pyproject.toml`, `netbox_naming/__init__.py`, empty `migrations/` and `tests/`
  packages, `dev/` (compose, plugin config, README), `COMPATIBILITY.md`.
- **Route:** standard.
- **Acceptance:** `docker compose up` in `dev/` serves NetBox 4.7.3 with the plugin listed under
  installed plugins; `manage.py check` is clean; a smoke test asserting the plugin is loaded passes.

### B2. Template grammar and token registry

- **Scope:** `netbox_naming/templating.py` (parser, part types, registry), `netbox_naming/exceptions.py`,
  `netbox_naming/tests/test_templating.py`.
- **Route:** standard.
- **Acceptance:** the parser and registry tests in Test strategy pass; no `format`/Jinja2 use.

### B3. Models and migration

- **Scope:** `netbox_naming/choices.py`, `netbox_naming/models.py` (`NamingConvention`,
  `NamingCounter`, `clean()`), `netbox_naming/migrations/0001_initial.py`,
  `netbox_naming/tests/test_models.py`.
- **Route:** standard.
- **Acceptance:** `makemigrations --check` reports no changes; model validation tests pass.

### B4. Engine: preview, allocate, counters, nesting

- **Scope:** `netbox_naming/engine.py`, `netbox_naming/tests/test_engine.py`,
  `netbox_naming/tests/test_allocation.py`. Sets this plan's Status to Implemented.
- **Route:** judgment (row locking, nesting order, collision domains).
- **Acceptance:** engine and concurrency tests pass; full suite green; Status reads Implemented.

## Deviations

None yet. Implementation items record any departure from this plan here.
