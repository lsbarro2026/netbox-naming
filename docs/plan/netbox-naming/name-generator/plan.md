# name-generator — plan

FEAT-5, 2026-10-22. This segment has no research item. It builds on the segment map and contracts in
[`../overview.md`](../overview.md), the model and engine fixed in [`../core/plan.md`](../core/plan.md)
(cited as *core plan*), and the view idioms in [`../management-ui/plan.md`](../management-ui/plan.md)
(cited as *management-ui plan*).

## Status

**Approved** (2026-10-22). Draft → Approved → Implemented. The last implementation item (G3) sets
Implemented.

## Current state

- **Code:** nothing has landed under `netbox_naming/`. core (FEAT-7 … FEAT-10) and management-ui
  (FEAT-11 … FEAT-13) are filed but not started.
- **Engine API** (core plan §Engine API): `NamingContext` (role, device type, site, location, …,
  `asset_tag`, `name`; `from_device()`), `Proposal(value, number, conflict, parts)`,
  `find_convention(target_field, role, device_type)`, `preview(convention, context, count, *, tail)`
  (no locks, no writes) and `allocate(…)` (atomic, uses up numbers). Errors are `NamingError`
  subclasses in `exceptions.py`.
- **Counter storage** (core plan §Numbering and counter storage): `NamingCounter(scope_key,
  last_value)`. The next number is `max(last_value, scan_max) + 1`, skipping values already taken in
  the target field's uniqueness domain. The scan matches `^prefix(\d{w})suffix$` with `__regex` for
  `asset_tag` and `__iregex` for `name`, across the counter scope (all devices, or one site or
  location). Nesting is at most one level deep.
- **Templating** (core plan §Token grammar): the parser returns typed parts (literal, token, number
  run). The parser and the token registry are public names in `templating.py`, as management-ui also
  expects.
- **UI** (management-ui plan): NetBox 4.7 generic views registered with `@register_model_view`; a
  `PluginMenu` named "Naming" whose `groups` this segment adds to; `preview.py` is a UI helper this
  segment may reuse but doesn't need.

## Decision

**Replace (greenfield: build new), consuming core's planned engine.** There's no code to extend or
refactor. This segment adds a thin service module, `generator.py`, on top of core's public `engine`
and `templating` API, plus pages that follow management-ui's idioms. No `adr` sequence is configured,
so this section is the decision record.

1. **Read-only by construction.** `generator.py` imports `preview` and `find_convention` and never
   `allocate`. Tests assert that `NamingCounter` rows are unchanged after every generator call. The
   Generate page is a **GET** form: the results are bookmarkable and there's no write path. POST
   returns 405.
2. **Generate form.** Role and/or device type (at least one, matching core's "no catch-all
   convention" rule), an optional **Location** (which implies its Site, for `{room}`-style tokens),
   an optional **tail** (for `tail` conventions), and a **count** N from 1 to 50 (default 5). The
   generator looks up the `name` and the `asset_tag` convention with `find_convention`.
   - If the name convention nests `{asset_tag}`, each row's tag comes from that proposal's
     `parts["asset_tag"]`, as core's nesting already pairs them.
   - Otherwise the asset_tag convention is previewed on its own with the same context and count, and
     row i pairs with row i.
   - A missing convention for one field leaves that column empty, with a message naming the field.
   - `MissingToken` shows as a message naming the token ("Pick a Location: the template uses
     `{room}`"). Other `NamingError`s (`NumbersExhausted`, `TooLong`, `InvalidTail`, `TemplateError`)
     also show as messages. None of them causes a 500.
   - `conflict=True` proposals (static or tail values already taken) are flagged on their row, never
     hidden.
3. **Inventory.** For each convention: the values already in use, which numbers are taken, and the
   next free number.
   - **Match pattern**, built from core's parsed parts: an escaped literal matches itself, a token
     becomes `(.+?)`, the `#`-run becomes `(\d{w})`, and `{tail}` becomes `([A-Za-z0-9._-]+)`. The
     pattern is anchored. The database pre-filter uses `__regex` on `asset_tag` and `__iregex` on
     `name`, the same rule as core's scan.
   - **Series** = the counter-scope pk (none, the site or the location, per `counter_scope`) plus the
     text captured for each token. `ap##` has one series; `{site_slug}-sw##` has one per site.
   - For each series: the taken numbers collapsed into ranges ("01–17, 19–42"), the highest value,
     and the **next free** value. Next free comes from `engine.preview(convention, ctx, 1)`, where
     `ctx` is `NamingContext.from_device(representative)` with `name` and `asset_tag` cleared. The
     representative is a device in the series. If that preview's value doesn't match the series
     (the device has moved, so its fields render a different prefix), next free shows "—" instead
     of a guess.
   - Static and tail conventions get a value list only, with no numbers or next free.
   - Gaps aren't reused (core plan Q3), so the page labels them as skipped, not free.
4. **Permissions.** Both pages require `netbox_naming.view_namingconvention` and `dcim.view_device`.
   Posted role, device type and location ids resolve through `.restrict(user, "view")`; an id the
   user can't see counts as absent. The inventory's device list is the user's restricted device
   queryset. Next free comes from the engine's unrestricted scan, so it's the number `allocate` would
   hand out. A user with constrained device permissions can therefore infer that hidden values
   exist. That's the same disclosure trade-off management-ui Decision 4 accepted.
5. **No re-segmentation.** Every contract in overview.md holds as written. This segment calls only
   `preview` from the Engine API.

## Design

### Service (`netbox_naming/generator.py`)

```python
@dataclass(frozen=True)
class TakenValue:
    device: Device
    value: str
    number: int | None          # None for static / tail conventions

@dataclass(frozen=True)
class Series:
    label: str                  # rendered pattern, e.g. "ap##" or "lon-sw##"
    scope: Site | Location | None
    taken: list[TakenValue]     # sorted by number, then value
    ranges: list[tuple[int, int]]
    highest: TakenValue | None
    next: Proposal | None       # None when it can't be computed honestly

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

MAX_COUNT = 50

def series_pattern(convention) -> tuple[re.Pattern, list[str]]   # regex + token names per group
def collapse_ranges(numbers: Iterable[int]) -> list[tuple[int, int]]
def inventory(convention, devices: QuerySet[Device]) -> Inventory
def generate(*, role=None, device_type=None, location=None, count=5, tail=None) -> Generation
```

- `inventory` takes the queryset from its caller (the view passes the user's restricted one), filters
  it on the target field with the database regex, then matches each value in Python to get the
  captures and number. One query for the values, plus one `preview` per series.
- `generate` builds the context from role, device type, location and the location's site, and clamps
  `count` to `1..MAX_COUNT`.

### Pages (`views.py`, `forms.py`, `urls.py`, `navigation.py`, `templates/netbox_naming/`)

`views.py`, `urls.py`, `navigation.py` and `forms.py` are shared with management-ui (FEAT-11 creates
them). This segment's edits are **additive only**: new classes, new paths, and a new entry in the
menu's `groups` tuple. Nothing there is renamed or rewritten.

- **`GenerateForm(forms.Form)`** in `forms.py`: `role`, `device_type`, `location`
  (`DynamicModelChoiceField`, `required=False`), `tail` (`CharField`, `required=False`), `count`
  (`IntegerField`, 1–50, initial 5). `clean()` requires a role or a device type.
- **`GenerateNamesView(LoginRequiredMixin, View)`** at `generate/`, GET only. A bound and valid form
  calls `generator.generate`. Template `generate_names.html`: the form, the conventions used (linked),
  messages, and a results table (#, Name, Asset tag, with the conflict badge).
- **`NameInventoryListView`** at `inventory/`: one row per convention the user can view, with its
  template, target field, counter scope, number of values in use, highest value and next free.
  Next free is shown only for single-series conventions; otherwise it links to the convention's tab
  ("per site/location →"). Paginated per NetBox's per-page setting, so the inventory runs only for
  the visible page. Template `name_inventory.html`.
- **Inventory tab** on the convention detail page:
  `@register_model_view(NamingConvention, "inventory", path="inventory")` with
  `tab = ViewTab(label="Inventory", permission="dcim.view_device")`. Template
  `namingconvention_inventory.html` shows one card per series (label, scope, range strip, highest,
  next free) and a paginated table of devices holding values (device link, value, number, role,
  type, location).
- **Navigation**: a new group, `("Generator", (generate_item, inventory_item))`, with each item's
  `permissions` set to the view permission plus `dcim.view_device`.

## Contracts

This segment consumes, and changes none of, the contracts in
[overview.md § Contracts](../overview.md#contracts):

- Convention model: matching, the target field, the template and the counter scope.
- Number placeholder: the series pattern and the ranges.
- Nesting: pairing through `Proposal.parts`.
- Engine API: `preview` and `find_convention` only.
- URLs: `/plugins/naming/generate/`, `/plugins/naming/inventory/` and
  `/plugins/naming/namingconvention/<pk>/inventory/`.

## Test strategy

All tests run in core's `dev/` container (`manage.py test netbox_naming --keepdb`).

- **Generator** (`tests/test_generator.py`, `TestCase` with dcim fixtures):
  - `collapse_ranges` edge cases;
  - the pattern builder, including literals that need escaping (`.`, `-`);
  - hand-entered `ap01-old` and `xap05` are excluded from an `ap##` series;
  - series split by a `{site_slug}` prefix and by `counter_scope=location`;
  - next free equals `engine.preview`, and is `None` for a moved representative device;
  - generate pairing for a nested `{room}-{asset_tag}` name and for separate name and tag
    conventions;
  - the no-convention, `MissingToken`, tail and conflict paths, and `count` clamping;
  - **`NamingCounter` rows unchanged** after `inventory` and `generate`.
- **Views** (`tests/test_generator_views.py`):
  - the permission matrix: anonymous, no `dcim.view_device`, no `view_namingconvention`;
  - a hidden role or location id is treated as absent;
  - POST to `generate/` returns 405;
  - restricted devices aren't listed on the inventory tab;
  - the Generator menu items are hidden without permission.
- **Browser check** in the dev NetBox: an AP role with an `ap##` asset_tag convention and a
  `{room}-{asset_tag}` name convention. "Next 5" with a Location lists five name and tag pairs.
  Re-running it shows the same values, because nothing was used up. The inventory shows the taken
  ranges and the same next free value.

## Implementation breakdown

Filed as a chain G1 → G2 → G3. G1 waits on FEAT-5 and on core's engine (FEAT-10). G2 also waits on
management-ui's M1 (FEAT-11), which creates the shared view, URL, form and navigation files.

### G1. Generator service

- **Scope:** `netbox_naming/generator.py`, `netbox_naming/tests/test_generator.py`.
- **Route:** judgment (keeping the pattern in step with core's scan, grouping into series, honest
  next free).
- **Acceptance:** generator tests pass, including the unchanged `NamingCounter` assertion; full suite
  green.

### G2. Generate names page

- **Scope:** `GenerateForm` in `forms.py`, `GenerateNamesView` in `views.py`, the `generate/` path in
  `urls.py`, the Generator group and its Generate item in `navigation.py`,
  `templates/netbox_naming/generate_names.html`, `tests/test_generator_views.py` (generate cases).
- **Route:** standard.
- **Acceptance:** view tests pass; the "next 5" browser check passes; full suite green.

### G3. Inventory pages

- **Scope:** `NameInventoryListView` and the Inventory tab view in `views.py`, the `inventory/` path in
  `urls.py`, the Inventory item in `navigation.py`, `templates/netbox_naming/name_inventory.html`,
  `templates/netbox_naming/namingconvention_inventory.html`, the inventory cases in
  `tests/test_generator_views.py`. Sets this plan's Status to Implemented.
- **Route:** standard.
- **Acceptance:** view tests pass; the inventory browser check passes; full suite green; Status reads
  Implemented.

## Deviations

Implementation items record any departure from this plan here.

### G1 (FEAT-14)

- **Next free clears only the convention's own target field.** Decision 3 cleared both `name` and
  `asset_tag` on the representative's context. That makes a numbered convention that nests the
  other field (`{asset_tag}-##`) render a freshly nested value, so next free almost always shows
  "—". Keeping the device's own value for the other field gives the number `allocate` would hand
  that device. The series-match check still turns any mismatch into "—".
- **The asset_tag column always comes from a separate `preview`.** Decision 2 took the tags of a
  name that nests `{asset_tag}` from `Proposal.parts`. The separate preview returns the same values
  by construction (same convention, context, count and tail; a test asserts the equality). Unlike
  `parts`, it also keeps each tag's own number and conflict flag, and it still fills the column when
  the name preview fails.
- **Static and tail conventions get one series**, labelled with the template, instead of one per
  token capture. They have no numbers or counter, so per-capture series would only split the value
  list.
- **Devices without a location under `counter_scope=location`** form their own series with no
  scope and no next free, since the engine can't number them.
- **Ambiguous splits:** lazy `(.+?)` token groups can split a value such as `lon-core-ap01`
  differently from how it was rendered. In that case the series-match check shows "—" for next free,
  never a wrong number.
