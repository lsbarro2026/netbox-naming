# management-ui — plan

FEAT-4, 2026-10-22. Builds on [`research.md`](research.md) (cited below as F1–F9, sources as
S-numbers), the segment map and contracts in [`../overview.md`](../overview.md), and the model and
engine fixed in [`../core/plan.md`](../core/plan.md) (cited as *core plan*).

## Status

**Approved** (2026-10-22). Draft → Approved → Implemented. The last implementation item (M3) sets
Implemented.

## Decision

**Replace (greenfield: build new) — research verdict confirmed, Option 1.** There is no UI code to
extend, and core's implementation (FEAT-7 … FEAT-10) hasn't started. The pages are NetBox 4.7 generic
views with a declarative `SimpleLayout` detail page, plus one hand-secured htmx preview endpoint and a
custom template widget (F1–F8). No `adr` sequence is configured, so this section is the decision
record.

Research open questions, settled here:

1. **REST API — in this segment**, as its own item (M2). Event rules and webhooks serialize the object
   through `get_serializer_for_model()` and fail without a plugin serializer (F9).
2. **Views** — list, detail, add/edit, delete, bulk import, bulk delete. No bulk edit (templates are
   per-convention) and no bulk rename. The list view declares
   `actions = (AddObject, BulkImport, BulkExport, BulkDelete)` so it only offers views that exist (F1).
3. **Preview context** — placeholders by default, plus two preview-only form fields: an optional
   **Location** (which implies its Site) and an optional **sample tail**, so `{room}` and `{tail}` can
   render for real.
4. **Preview permission** — the endpoint requires `netbox_naming.add_namingconvention` when no pk is
   posted, or `change` on that convention when one is (looked up through
   `.restrict(user, "change")`, 404 otherwise), **and** `dcim.view_device`. Posted role, device type and
   location ids resolve through `.restrict(user, "view")`; an id the user can't see counts as absent.
   The engine's device scan stays **unrestricted**, so the numbers shown are the numbers `allocate`
   would hand out. Residual disclosure — a user with constrained device permissions can infer that a
   value is taken — is accepted (research Risks).
5. **Detail page** — attributes, template, "Sample values" (next 5), comments, tags. The full "next N"
   generator stays FEAT-5's.
6. **Global search** — yes: `search.py` indexes `name`, `template`, `description` (S25).

No re-segmentation is needed: every contract in overview.md holds as written. The segment gains
supporting files beyond overview.md's file column — `filtersets.py`, `search.py`, `preview.py`,
`api/` — recorded here; overview.md is not edited.

## Design

All files live under `netbox_naming/`. Only documented plugin API is used, except where noted as a
soft boundary (research Risks): `netbox.object_actions` for list actions and NetBox's test-case
helpers. Both are pinned with core's `max_version = "4.7.99"`.

### Filterset (`filtersets.py`)

`NamingConventionFilterSet(PrimaryModelFilterSet)`, decorated with `@register_filterset` (F4).
Filters: `kind`, `target_field`, `counter_scope` (multiple choice); `role_id` / `role` (slug);
`device_type_id` / `device_type` (slug). `search()` matches `name`, `template` and `description`
(`icontains`).

### Forms (`forms.py`)

- `NamingConventionForm(PrimaryModelForm)`. Fieldsets:
  - **Convention** — `name`, `kind`, `target_field`, `template`, `description`, `tags`
  - **Applies to** — `role`, `device_type` (`DynamicModelChoiceField`, F2)
  - **Numbering** — `counter_scope`, `tail_max_length`, with help text saying which kind each applies to
  - **Preview** — non-model `preview_location` (`DynamicModelChoiceField(Location, required=False)`)
    and `preview_tail` (`CharField(required=False)`); never saved
  - plus `owner` and `comments` as `PrimaryModelForm` places them.
  Choice fields show a one-line description per option (F2). The template field gets the widget from
  §Live template editor (added in M3; M1 ships a plain input).
- `NamingConventionFilterForm(PrimaryModelFilterSetForm)` — kind, target field, counter scope,
  `role_id`, `device_type_id` (`DynamicModelMultipleChoiceField`), tags.
- `NamingConventionImportForm(PrimaryModelImportForm)` — role by slug, device type by slug
  (`CSVModelChoiceField(to_field_name="slug")`). A device-type slug shared by two manufacturers is a
  row error, not a guess. Preview fields are not part of it.

### Table (`tables.py`)

`NamingConventionTable(PrimaryModelTable)`: `name` (linkify), `kind` and `target_field`
(`ChoiceFieldColumn`), `template` (`TemplateColumn` wrapping `<code>`), `role`, `device_type`
(linkify), `counter_scope`, `tail_max_length`, `tags`. Default columns: name, kind, target field,
template, role, device type.

### Views and URLs (`views.py`, `urls.py`)

Registered with `@register_model_view(NamingConvention, …)` and included through `get_model_urls`
under `namingconvention/` and `namingconvention/<int:pk>/` (F1):

| View | Base | Name |
|---|---|---|
| list | `ObjectListView` (table, filterset, filter form, `actions` per Decision 2) | `list`, `path=""`, `detail=False` |
| detail | `ObjectView` with `layout` (below) | — |
| add / edit | `ObjectEditView` | `add` (`detail=False`), `edit` |
| delete | `ObjectDeleteView` | `delete` |
| bulk import | `BulkImportView` | `bulk_import`, `path="import"`, `detail=False` |
| bulk delete | `BulkDeleteView` | `bulk_delete`, `path="delete"`, `detail=False` |

Changelog and journal tabs register themselves (F1). Permissions come from the base mixins with no
extra code (F7).

Detail `layout = SimpleLayout(...)` (F6, S7): left — `ObjectAttributesPanel` (name, kind, target
field, role, device type, counter scope, tail max length, description), `TextCodePanel("template")`;
right — `SampleValuesPanel` (M3), tags; bottom — `CommentsPanel`. M1 ships the layout without the
sample panel.

`urls.py` also carries one explicit path, `preview/` → `TemplatePreviewView`, name
`namingconvention_preview` (M3).

### Navigation (`navigation.py`)

```python
menu = PluginMenu(
    label="Naming",
    groups=(("Conventions", (conventions_item,)),),
    icon_class="mdi mdi-label-outline",
)
```

`conventions_item = PluginMenuItem(link="plugins:netbox_naming:namingconvention_list",
link_text="Naming Conventions", permissions=["netbox_naming.view_namingconvention"], buttons=(add,))`,
the add button gated on `add_namingconvention` (F5). FEAT-5 (`name-generator`) adds its own group to
the same `groups` tuple. Edits to `navigation.py`, `views.py` and `urls.py` from either segment are
additive.

### Global search (`search.py`)

`NamingConventionIndex(SearchIndex)`, `@register_search`; fields `name` (100), `template` (300),
`description` (500); `display_attrs = ("kind", "target_field", "role", "device_type")`.

### REST API (`api/`)

- `api/serializers.py`: `NamingConventionSerializer(PrimaryModelSerializer)` with `url`, all model
  fields, `role` / `device_type` as dcim's nested brief serializers; `brief_fields = ("id", "url",
  "display", "name", "description")`.
- `api/views.py`: `NamingConventionViewSet(NetBoxModelViewSet)` with the filterset.
- `api/urls.py`: `NetBoxRouter`, `namingconventions` route. `PluginConfig` loads it by default.
- The serializer runs `NamingConvention.clean()` through the standard model validation, so the API
  enforces the same rules as the form.

### Live template editor (M3)

**Widget** — `TemplateInput(forms.TextInput)` with template
`netbox_naming/widgets/template_input.html`: the input, then a result region
(`<div aria-live="polite">`) carrying:

- `hx-post="{% url 'plugins:netbox_naming:namingconvention_preview' %}"`
- `hx-trigger="load, keyup changed delay:500ms from:#id_template, change from:closest form"` (S22)
- `hx-sync="closest form:abort"` so a submit cancels an in-flight preview
- a "Refresh preview" button doing the same post, as the fallback if a picker doesn't fire `change`.

The region sits inside the edit `<form>`, so htmx posts every form input, including the CSRF token,
as the core Markdown widget does (F8, S15). On edit, the form sets `data-pk` on the widget and the
region sends it with `hx-vals`. A collapsible list of available tokens, built from core's registry,
sits under the input.

**Endpoint** — `TemplatePreviewView(LoginRequiredMixin, View)`, POST only, returns the partial
`netbox_naming/inc/template_preview.html`. Checks per Decision 4; a failed check returns a 403 partial
saying which permission is missing (404 for an invisible pk). Read-only: no writes, no locks.

**Preview logic** (`preview.py`, a UI helper FEAT-5 may reuse):

1. Build an **unsaved** `NamingConvention` from the posted fields (the pk's instance when editing) and
   a `NamingContext` from role, device type, preview location and its site.
2. Parse the template with core's public parser. A `TemplateError` shows the parts up to the error and
   highlights the offending token.
3. Run the model's `clean()`. Its errors (kind/shape mismatch, self-reference, unknown `cf_*`, stray
   tail length) show as messages; a kind/shape mismatch adds a hint naming the kind the template
   implies.
4. Call `engine.preview(convention, context, count=5, tail=preview_tail or None)` — `count` is capped
   at 5 — and list the values, marking `conflict=True` ones as taken and showing nested `parts`.
5. On `MissingToken` (or a tail convention with no sample tail), fall back to **shape mode**: render
   each part with core's registry against the context, show unresolved tokens as `‹room›` and the
   number run as its `#`s, with a line naming what to fill in ("Pick a Location to see real
   numbers"). Shape mode never shows a number, because the number depends on the rendered prefix.
6. Other `NamingError`s (`NumbersExhausted`, `TooLong`, `InvalidTail`) show as messages.

The model's `clean()` stays the authority on save; the preview only reports.

**Sample values panel** — a `Panel` subclass on the detail page running steps 4–6 for the saved
convention with an empty context plus its own role/device type. It renders only when the user has
`dcim.view_device`; otherwise it says why it's hidden.

### Consumed core surface

Built against core plan §Models, §Token grammar, §Engine API, with these expectations (research
Risks), none of which changes an overview.md contract:

- the parser and token registry are public names in `templating.py`;
- `TemplateError` carries the offending token or offset;
- `clean()` raises `ValidationError({"template": …})` keyed by field;
- `engine.preview` accepts an unsaved convention.

If core lands without one of these, M3 adapts in the UI and records it under Deviations, or files a
core follow-up when adapting isn't reasonable.

## Contracts

This segment consumes, and changes none of, the contracts in
[overview.md § Contracts](../overview.md#contracts): Convention model (forms, tables, filters, API),
Number placeholder (shape mode, sample values), Nesting (display of nested `parts` only), Engine API
(`preview` only — nothing here calls `allocate`), and URLs (`/plugins/naming/namingconvention/…`).

## Test strategy

All tests run in core's `dev/` container (`manage.py test netbox_naming --keepdb`).

- **CRUD views** — NetBox `ViewTestCases` (`GetObjectViewTestCase`, `CreateObjectViewTestCase`,
  `EditObjectViewTestCase`, `DeleteObjectViewTestCase`, `ListObjectsViewTestCase`,
  `BulkImportObjectsViewTestCase`, `BulkDeleteObjectsViewTestCase`), which cover the permission-denied
  and object-constraint paths. Plus: the list page renders exactly the declared actions; an import
  row with an ambiguous device-type slug errors.
- **Filterset** — each filter and `q` search.
- **Navigation** — the menu item is hidden without `view_namingconvention`.
- **API** — `APIViewTestCases` for the full set; an invalid template is rejected with a field error;
  `get_serializer_for_model(NamingConvention)` resolves.
- **Preview endpoint** — `TestCase`: permission matrix (anonymous / view only / add / change on
  another object only / no `dcim.view_device`); a hidden role or location id is treated as absent;
  unknown token highlighted; shape fallback for `{room}` without a location; conflict marked;
  `count` capped; `NamingCounter` rows unchanged after previews.
- **Browser check** — in the dev NetBox, typing a template updates the preview after the pause, a
  bad token is flagged inline, and picking a Location turns `‹room›` into the real name.

## Implementation breakdown

Filed as a chain M1 → M2 → M3; M1 waits on FEAT-4 and on core's model (FEAT-9); M3 also waits on
core's engine (FEAT-10).

### M1. CRUD pages and menu

- **Scope:** `netbox_naming/filtersets.py`, `forms.py` (model, filter and import forms; plain template
  input, preview fieldset not yet added), `tables.py`, `views.py`, `urls.py`, `navigation.py`,
  `search.py`, any `templates/netbox_naming/` file the generic views need,
  `tests/test_views.py`, `tests/test_filtersets.py`.
- **Route:** standard.
- **Acceptance:** CRUD view, filterset and navigation tests pass; the "Naming" menu lists Naming
  Conventions in the dev NetBox; full suite green.

### M2. REST API

- **Scope:** `netbox_naming/api/__init__.py`, `api/serializers.py`, `api/views.py`, `api/urls.py`,
  `tests/test_api.py`.
- **Route:** routine.
- **Acceptance:** API tests pass; `get_serializer_for_model` resolves the model; full suite green.

### M3. Live template editor and sample values

- **Scope:** `netbox_naming/preview.py`, `widgets.py` (`TemplateInput`), the preview fieldset in
  `forms.py`, `TemplatePreviewView` and `SampleValuesPanel` in `views.py`, the `preview/` path in
  `urls.py`, `templates/netbox_naming/widgets/template_input.html`,
  `templates/netbox_naming/inc/template_preview.html`, the panel template, `tests/test_preview.py`.
  Sets this plan's Status to Implemented.
- **Route:** judgment (hand-written permission gate, disclosure trade-off, adapting to core's API).
- **Acceptance:** preview tests pass; browser check done; full suite green; Status reads Implemented.

## Deviations

None yet. Implementation items record any departure from this plan here.
