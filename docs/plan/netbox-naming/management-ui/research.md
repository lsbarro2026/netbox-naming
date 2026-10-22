# management-ui — research

FEAT-3, 2026-10-22. Feeds the `management-ui` Plan item (FEAT-4). Segment map and contracts:
[`../overview.md`](../overview.md). Model and engine this UI edits: [`../core/plan.md`](../core/plan.md)
(cited below as *core plan*). Every source below was accessed on **2026-10-22**. NetBox source and docs
links point at the `v4.7.3` tag, the version `core` pinned.

## Question

How should the plugin's own page be built, so that a user can list, add, edit, view and delete
`NamingConvention`s from a nav menu entry, with permissions respected? And how can editing a template
string be made "intuitive", meaning unknown tokens are flagged inline and a sample render is shown live?
Specifically:

1. Which NetBox 4.7 plugin APIs to use for views, URLs, forms, tables, filtersets, navigation and
   templates, and which of them are the supported plugin API.
2. How the generic views enforce object permissions, and what a custom (non-generic) view must do to
   match.
3. How to validate a template and preview a render live inside NetBox's edit form.
4. What `core`'s planned API gives the UI, and what is missing.

## Current implementation

**No code yet.** At `bab220f` the repo holds tooling and `docs/` only, and `core`'s implementation
(B1–B4) hasn't started. So "current" here means the **planned** surface in the core plan, which the UI
is built against:

| Core piece (core plan) | What the UI does with it |
|---|---|
| `NamingConvention(PrimaryModel)`, fields `name`, `kind`, `target_field`, `template`, `role`, `device_type`, `counter_scope`, `tail_max_length` (L61–75) | The model form, table columns, filterset fields and the detail page. `PrimaryModel` adds `description`, `comments`, `owner`, tags and custom fields, which the `PrimaryModel*` form, table and filterset bases already handle [S2][S3][S4] |
| `CheckConstraint` role-or-type, and `UniqueConstraint(target_field, role, device_type)` (L77–79) | Surfaced as form errors on save. `ModelForm` validation runs model constraints |
| `clean()` (L81–87): kind ⇔ template shape, self/cyclic reference, unknown `cf_*`, stray `tail_max_length` | The authoritative server-side check. The edit form shows its errors |
| Token grammar and registry in `templating.py` (L101–132). The parser "returns a list of typed parts; nothing is evaluated" | Inline validation, and the list of available tokens shown as help text |
| `engine.preview(convention, context, count, *, tail)`, `NamingContext`, `Proposal`, `find_convention` (L164–194) | The live sample render and the detail page's "next values" panel |
| `exceptions.py`, with `NamingError` → `TemplateError`, `MissingToken`, `NumbersExhausted`, `TooLong`, `InvalidTail`, `Conflict` (L199–200), "so forms can map them" | Mapped to field errors and preview messages |
| `base_url = "naming"` (L49–50) | Pages live under `/plugins/naming/…` |

`management-ui` must therefore add these files: `forms.py`, `tables.py`, `filtersets.py`, `views.py`,
`urls.py`, `navigation.py` and `templates/netbox_naming/`. `filtersets.py` isn't in overview.md's file
column, but the list view needs it [S4]. See Open questions for `api/`.

## Findings (cited)

### F1. Generic views and URL registration

- NetBox's **supported** generic views for plugins are `ObjectView`, `ObjectEditView`,
  `ObjectDeleteView`, `ObjectChildrenView`, `ObjectListView`, `BulkImportView`, `BulkEditView`,
  `BulkRenameView` and `BulkDeleteView`. "Only the classes which appear in this documentation are
  currently supported" [S1 L56–71].
- **URL registration** has two parts [S1 L73–110]:
  - Decorate each view with `@register_model_view(Model, name=…, detail=…)`.
  - In `urls.py`, include `get_model_urls('netbox_naming', 'namingconvention', detail=False)` under
    `namingconvention/`, and include `get_model_urls(...)` again under `namingconvention/<int:pk>/`.
- Core NetBox registers small CRUD models this way. For example, the export template views [S14
  L305–343] register:
  - `'list'` with `path=''` and `detail=False`
  - the detail view (no name)
  - `'add'` with `detail=False`, and `'edit'`, on one `ObjectEditView`
  - `'delete'`
  - `'bulk_import'` with `path='import'`, plus the bulk views
- Change log and journal views are **registered automatically** for models that support them, so a
  `PrimaryModel` gets its Changelog tab for free [S1 L178–183].
- `NetBoxModel.get_absolute_url()` reverses the view name produced by `get_viewname()` [S20 L48–50].
  The detail view must therefore be registered, or table links and redirects break.
- **List actions.** By default, `ObjectListView.actions` is `(AddObject, BulkImport, BulkExport,
  BulkEdit, BulkRename, BulkDelete)` [S12 L90–102].
  - An action's URL resolves to `None` on `NoReverseMatch` [S13 L45–52].
  - Declare `actions` explicitly, so the list page only offers views that actually exist.
  - `netbox.object_actions` is used by core views but appears in the plugin docs only through a v4.4
    release note [S24]. That makes it a soft API boundary (see Risks).

### F2. Forms

- Plugins use `NetBoxModelForm`, or `PrimaryModelForm` for a `PrimaryModel`. Layout comes from
  `fieldsets = (FieldSet(...), ...)` [S2 L3–58].
- Related objects use `DynamicModelChoiceField`. The examples use it for core FKs, and here it covers
  `role → dcim.DeviceRole` and `device_type → dcim.DeviceType` [S2 L34–55, L244–252]. These widgets
  call **core's** REST API, so they don't need a plugin API.
- Static choice fields render a plain `<select>` and can show per-option descriptions [S2 L213–243].
  This suits `kind`, `target_field` and `counter_scope`, where a one-line description of each option
  helps.
- `ObjectEditView.get()` and `post()` call `restrict_form_fields(form, request.user)`. Every
  `RestrictedQuerySet` field is narrowed to objects the user may view [S9 L251, L294][S11 L239–246].
  So the role and device-type pickers respect object permissions with no extra code.
- **The edit view already speaks htmx.**
  - On an htmx (non-boosted) GET, `ObjectEditView` returns only the form body (`htmx/form.html`),
    built from `initial=normalize_querydict(request.GET)` [S9 L183–266].
  - Core's `HTMXSelect` widget uses this to re-render the whole form when a select changes [S16
    L98–118].
  - `HTMXSelect` is **not** in the plugin docs, though, so it's outside the supported API (core
    research F2).
- Also available: `NetBoxModelImportForm` / `PrimaryModelImportForm` for CSV/JSON/YAML import, and
  `NetBoxModelBulkEditForm` / `PrimaryModelBulkEditForm` [S2 L60–147].

### F3. Tables

- Use `NetBoxTable`, or `PrimaryModelTable` for a `PrimaryModel`. Users can configure columns and
  their order. The table gets custom field columns, related-object prefetching, and the `pk` / `id` /
  `actions` columns [S3 L5–45].
- Supported columns include `ChoiceFieldColumn`, `TagColumn`, `TemplateColumn` and `MarkdownColumn`
  [S3 L63–106]. `template` displays fine as a plain `Column` (it's short, ≤200 chars, core plan L71).
  Wrap it in `<code>` through `TemplateColumn` if wanted.
- Bulk edit and delete buttons appear automatically when `<model>_bulk_edit` / `<model>_bulk_delete`
  views are registered [S3 L59–61].

### F4. Filtersets and filter forms

- Use `NetBoxModelFilterSet`, or `PrimaryModelFilterSet`, and decorate it with `@register_filterset`.
  Registering adds lookup modifiers to the filter form. It's optional but recommended [S4 L5–40].
- The list view's quick search works only if the filterset overrides `search()` [S4 L70–80].
  Searching here would cover `name`, `template` and `description`.
- The filter form uses `NetBoxModelFilterSetForm` / `PrimaryModelFilterSetForm`, with
  `DynamicModelMultipleChoiceField` for `role_id` / `device_type_id` [S2 L149–188].
- Global search is separate. A `search.py` with an `@register_search` `SearchIndex` puts conventions
  in NetBox's global search [S25 L1–27]. It's optional.

### F5. Navigation

- There are two ways to add menu entries [S5 L3–45]:
  - Your own top-level submenu: `menu = PluginMenu(label, groups=((label, items),), icon_class=…)` in
    `navigation.py`.
  - Entries under the shared "Plugins" menu: `menu_items = (…)`.
  
  `PluginConfig._load_resource` loads `navigation.menu` / `navigation.menu_items` by default [S20
  L35–44, L163–165].
- `PluginMenuItem(link, link_text, permissions=[…], buttons=…)` and
  `PluginMenuButton(link, title, icon_class, color, permissions)`. "Any buttons associated within a
  menu item will be shown only if the user has permission to view the link" [S5 L47–90]. Icons are
  Material Design Icons (`mdi mdi-…`).
- So a conventions entry should carry `permissions=['netbox_naming.view_namingconvention']`. Its
  "add" button should carry `…add_namingconvention`.

### F6. Templates and page layout

- Plugin templates live in `templates/netbox_naming/` [S6 L5–7]. Generic templates
  (`generic/object.html`, `object_edit.html`, `object_list.html`, `object_delete.html` and the bulk
  ones) extend `base/layout.html` and expose override blocks. For example, `object_edit.html` has
  `form` and `buttons` blocks [S6 L25–110].
- **v4.7 declarative detail pages.** An `ObjectView` can declare `layout = SimpleLayout(left_panels=…,
  right_panels=…, bottom_panels=…)` using documented panels such as `ObjectAttributesPanel`,
  `CommentsPanel`, `TemplatePanel` and `TextCodePanel`, with `netbox.ui.attrs.*` attributes such as
  `ChoiceAttr`, `RelatedObjectAttr` and `TextAttr`. Breadcrumbs are new in 4.7 [S7 L5–258].
- Core's export-template detail page is built entirely this way: `template_name =
  'generic/object.html'` plus a `TextCodePanel('template_code')` [S14 L316–331]. The convention detail
  page needs **no custom HTML** apart from a custom `Panel` for the sample render [S7 L122–145].

### F7. Permissions

- `BaseObjectView` and `BaseMultiObjectView` both subclass `ObjectPermissionRequiredMixin` [S10a L13,
  L62].
  - On dispatch, it checks `get_required_permission()`: view / add / change / delete per view, and
    `ObjectEditView` picks add or change by whether a pk is present [S9 L194–203].
  - It then narrows `self.queryset` with `.restrict(user, action)`, so object-level constraints apply
    [S10b L106–151].
  - `get_object()` is `get_object_or_404(self.queryset, …)` [S10a L42–49]. An object the user may not
    see therefore gets a 404, not a 403.
- **A custom view** (such as a preview endpoint) gets none of this unless it opts in. The documented
  route is `ObjectPermissionRequiredMixin` from `utilities.views`, with `queryset` and
  `permission_required` set [S8 L40–71].
- Core's Markdown preview endpoint is a precedent for a lighter gate: it is only `LoginRequiredMixin`
  [S14 L1942–1950].
- Custom actions (`Meta.permissions`) appear as checkboxes on ObjectPermission [S8 L1–38]. A `preview`
  action isn't needed if previewing is gated on `view`/`add`/`change`.

### F8. Live validation and sample render (the "intuitive" editor)

- **htmx 2 is already on every page.**
  - The NetBox bundle imports `htmx.org` 2.0.10 [S17a L32][S17b L3].
  - `django-htmx` 1.29.0 middleware sets `request.htmx` [S17c L6][S17d L544].
  - Inline `<script>` is allowed: base.html sets `window.CSRF_TOKEN` inline [S18 L31–36].
- **Core precedent: the Markdown preview widget.**
  - It is a form widget whose template places a button with `hx-post="{% url 'extras:render_markdown'
    %}"`, `hx-target`ing an `aria-live="polite"` div inside the edit `<form>` [S15 L10, L20].
  - The view validates a small form and returns HTML [S14 L1942–1950].
  - Because the element is inside the form and the request is non-GET, htmx sends every input of the
    form, including the CSRF token [S22 "Parameters"].
- **Debounced as-you-type.**
  - `hx-trigger="keyup changed delay:500ms"` waits 500 ms after the last keystroke, and only fires if
    the value changed [S22 "Trigger Modifiers"].
  - `hx-sync="closest form:abort"` cancels an in-flight preview when the form submits [S22
    "Synchronization"].
  - NetBox uses exactly this trigger on its own table quick-search [S19c L13].
- **What a preview can show without a device:**
  - The template is parsed (core plan L101–115), so the UI can list parts and flag unknown tokens by
    name.
  - A full render needs a `NamingContext`: role and device type come from the form; `{room}`,
    `{site}`, `{rack}`, `{tenant}`, `{platform}` and `{serial}` don't.
  - `preview` raises `MissingToken` on a null token (core plan L136).
  - So the preview needs either sample context pickers (Location/Site …) next to the template, or a
    placeholder mode that renders unresolved tokens as visible stand-ins (`‹room›-ap07`).
- **Prior art.** A search found no NetBox plugin with a live naming-template preview [S23]. The
  Markdown widget [S15] is the nearest pattern in NetBox itself.

### F9. REST API: not needed by the UI, but by events

- Every UI piece above works without a plugin REST API. The official tutorial builds tables, forms,
  views, URLs, templates, navigation and filtersets (steps 3–9) before the REST API (step 10) [S21].
- **But** event rules and webhooks serialize the object with `get_serializer_for_model()` [S19a L77],
  which raises `SerializerNotFound` when `netbox_naming.api.serializers.NamingConventionSerializer`
  doesn't exist [S19b L53–90].
  - Serialization is lazy: it happens only when a consumer reads `data` [S19a L60–69].
  - So a user who creates an event rule on naming conventions hits an error.
  - Core's "quick add" and object-selector widgets also call the REST API, but only for models that
    are *pointed at*, and nothing points at conventions.

## Options

| # | Option | For | Against |
|---|---|---|---|
| 1 | **NetBox generic views and declarative layout**, plus one htmx preview endpoint and a custom template widget | Everything documented and supported [S1–S8]. Permissions, change log, tags, custom fields, export and user table config come free. The detail page needs no HTML [S7]. The preview follows a core precedent [S15][S14] | One custom view to secure by hand (F7). The widget template is plain Django, no NetBox API |
| 2 | Generic views, but validate-on-submit only (no live preview) | Least code. `clean()` errors already show on submit | Misses the request's "intuitive" bar. The user only learns `{rom}` is wrong after saving |
| 3 | Generic views, with a client-side JS parser for live feedback | No server round-trip | Two parsers (Python and JS) drift. A JS bundle needs a build step NetBox plugins don't have. It still can't preview numbers or nested values (those need the DB) |
| 4 | Plain Django views and templates extending `base/layout.html` | Full control of the page | Re-implements permissions, tables, filters, export and change logging. Against the plugin docs' advice to use generic views "whenever possible" [S1 L52] |
| 5 | Re-render the whole form via `HTMXSelect` / htmx GET on `ObjectEditView` [S9][S16] | Reuses core's mechanism | `HTMXSelect` is unsupported API. A full-form re-render on every keystroke loses focus and cursor position in the template input |

## Verdict: Replace (greenfield: build new)

There is no UI code to extend or refactor, and the core plan made the same call for the model (core
plan L13–14). Build new, as **Option 1**:

- **CRUD** with generic views registered through `register_model_view` / `get_model_urls` [S1]:
  `ObjectListView` (`PrimaryModelTable`, `PrimaryModelFilterSet` with `search()`,
  `PrimaryModelFilterSetForm`), `ObjectView` with a `SimpleLayout` [S7], `ObjectEditView`
  (`PrimaryModelForm`), and `ObjectDeleteView`. Permissions come from the base mixins [S10][S11] and
  need no extra code (F7).
- **Navigation**: a `PluginMenu` "Naming" with a "Conventions" item gated on
  `view_namingconvention`, plus an add button [S5]. A top-level menu leaves room for FEAT-5's
  generator page.
- **Template editing**: a custom widget on `template` that renders the input plus a preview region.
  The input `hx-post`s, debounced [S22], to a plugin `preview` endpoint, the same way the Markdown
  widget does [S15][S14]. The endpoint builds an **unsaved** `NamingConvention` from the posted form
  values, runs the core parser, and returns a partial with three parts:
  - the parts, with unknown or invalid tokens highlighted
  - the available tokens (from the registry)
  - up to N sample values from `engine.preview`, falling back to placeholders for context tokens
    that aren't provided
  
  The model's `clean()` stays the authority on save.

Evidence: every piece is in the v4.7 plugin docs except the widget's own template, which is plain
Django [S1–S8]. Core NetBox builds equivalent pages the same way [S14 L305–343], and live preview inside
an edit form has an exact core precedent [S15].

## Risks

- **Core API gaps the preview depends on** (none of them changes an overview.md contract):
  - `engine.preview` must accept an **unsaved** convention. Its scope key and matching are pattern-
    and FK-based (core plan L151), so nothing in the plan needs a pk, but B4 should keep it that way
    and test it.
  - The parser and registry must be importable as a public function and mapping, not private
    helpers.
  - `TemplateError` should carry the offending token or offset, so the UI can point at it.
  - `clean()` should raise `ValidationError({'template': …})` keyed by field, so the error lands under
    the input and not at the top of the form.
  
  If B2/B3 land without these, FEAT-4 has to adapt or file follow-ups.
- **Information disclosure through preview.** `preview` scans every Device in scope and reports
  `conflict` / next numbers (core plan L153–160). A user with `view_namingconvention` but restricted
  `dcim.view_device` would learn that hidden names or asset tags exist. The custom endpoint must gate
  explicitly (F7). At minimum, require the convention permission plus `dcim.view_device`. Whether to
  scan with `Device.objects.restrict(user)` is a design call for the plan, because a restricted scan
  would show numbers that `allocate` won't actually hand out.
- **Soft API boundary.** `netbox.object_actions` (list `actions`) and widget-template internals aren't
  in the plugin docs [S24][S1 L70–71]. Pin to 4.7.x as core does (core plan L16–17), and cover the list
  page in tests so a minor upgrade that breaks it fails loudly.
- **Preview load.** Each debounced keystroke runs a DB scan. A 500 ms delay and `changed` [S22] bound
  the rate, and `count` should be capped (for example ≤10).
- **Shared file with FEAT-5.** `name-generator` will add its own menu item to `navigation.py` and its
  views to `urls.py`, so FEAT-4 and FEAT-5 touch the same two files. Whichever lands second merges.
- **Event rules without a serializer** fail at delivery time (F9).

## Open questions for the plan

1. **REST API.** Ship a minimal `netbox_naming/api/` (serializer, viewset, router) so event rules,
   webhooks and API users work (F9)? It isn't in overview.md's management-ui file list. Proposal:
   include it in FEAT-4 as a small item, or file it as its own item. Either way it's not a
   re-segmentation, since no overview contract changes.
2. **Bulk views.** Proposal: list, detail, add/edit, delete, `BulkImportView` (YAML/CSV seeding of
   conventions is useful) and `BulkDeleteView`. Skip `BulkEditView` (templates are per-convention) and
   `BulkRenameView`. Set `actions` to match (F1).
3. **Preview context.** Placeholders only, or also optional Site/Location pickers in the preview panel
   so `{room}` renders for real? Proposal: placeholders by default, plus an optional Location picker
   (which implies its Site), since `{room}` is the request's example.
4. **Preview permission.** Should the gate be the convention's view permission, or add/change? And
   should the scan be restricted to the user's visible devices? (See Risks.)
5. **Detail page panels.** Attributes, the template (`TextCodePanel`), "next 5 values" (`engine.preview`
   with placeholders), comments and tags. Is "next N" here a duplicate of FEAT-5's generator? Proposal:
   show a small fixed sample here, and leave the generator page to FEAT-5.
6. **Global search.** Add a `search.py` index [S25]? Proposal: yes, since it's cheap and covers `name`
   and `template`.

## Sources

NetBox sources are at tag `v4.7.3` (https://github.com/netbox-community/netbox/blob/v4.7.3/…). Doc
pages also render at https://netboxlabs.com/docs/netbox/plugins/development/. All accessed 2026-10-22.

- [S1] Plugin views: generic view classes, `register_model_view` / `get_model_urls`, feature views — `docs/plugins/development/views.md` — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/views.md
- [S2] Plugin forms: `NetBoxModelForm` / `PrimaryModelForm`, import, bulk edit and filter forms, field types — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/forms.md
- [S3] Plugin tables: `NetBoxTable` / `PrimaryModelTable`, columns, bulk buttons — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/tables.md
- [S4] Plugin filtersets: `NetBoxModelFilterSet`, `register_filterset`, quick search — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/filtersets.md
- [S5] Plugin navigation: `PluginMenu`, `PluginMenuItem`, `PluginMenuButton` — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/navigation.md
- [S6] Plugin templates: blocks, `base/layout.html`, generic view templates — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/templates.md
- [S7] Plugin UI components: layouts, breadcrumbs (new in 4.7), panels, attributes — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/ui-components.md
- [S8] Plugin permissions: custom actions, `ObjectPermissionRequiredMixin` — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/permissions.md
- [S9] `ObjectEditView` (htmx partial, `restrict_form_fields`, add/change permission) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/netbox/views/generic/object_views.py#L183-L375
- [S10a] `BaseObjectView` / `BaseMultiObjectView` — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/netbox/views/generic/base.py
- [S10b] `ObjectPermissionRequiredMixin` (`queryset.restrict`) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/utilities/views.py#L106-L151
- [S11] `restrict_form_fields` — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/utilities/forms/utils.py#L239-L246
- [S12] `ObjectListView` default `actions` — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/netbox/views/generic/bulk_views.py#L90-L102
- [S13] `ObjectAction.get_url` (`NoReverseMatch` → `None`) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/netbox/object_actions.py#L45-L52
- [S14] `extras/views.py`: export-template CRUD set (L305–343) and `RenderMarkdownView` (L1942–1950) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/extras/views.py
- [S15] Markdown input widget template (htmx preview) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/utilities/templates/widgets/markdown_input.html
- [S16] `HTMXSelect` widget — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/utilities/forms/widgets/select.py#L98-L118
- [S17a] `project-static/package.json` (`htmx.org` 2.0.10) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/project-static/package.json
- [S17b] `project-static/src/index.ts` (`import 'htmx.org'`) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/project-static/src/index.ts
- [S17c] `requirements.txt` (`django-htmx==1.29.0`) — https://github.com/netbox-community/netbox/blob/v4.7.3/requirements.txt
- [S17d] `settings.py` (`HtmxMiddleware`, L544) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/netbox/settings.py
- [S18] `templates/base/base.html` (inline script, `CSRF_TOKEN`) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/templates/base/base.html#L31-L36
- [S19a] `extras/events.py` (`serialize_for_event`, lazy `data`) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/extras/events.py#L60-L83
- [S19b] `utilities/api.py` `get_serializer_for_model` — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/utilities/api.py#L53-L90
- [S19c] `templates/inc/table_controls_htmx.html` (`keyup changed delay:500ms`) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/templates/inc/table_controls_htmx.html
- [S20] `NetBoxModel.get_absolute_url` (`netbox/models/__init__.py` L48–50) and `PluginConfig` resource paths (`netbox/plugins/__init__.py` L35–44, L163–165) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/netbox/plugins/__init__.py
- [S21] NetBox plugin tutorial (targets "NetBox v4.5 or later"; step order 3–9 UI, 10 REST API) — https://github.com/netbox-community/netbox-plugin-tutorial
- [S22] htmx 2.x docs: Parameters, Triggers (`changed`, `delay`), Synchronization (`hx-sync`) — https://htmx.org/docs/
- [S23] Prior-art web search, "NetBox plugin device naming template preview htmx 4.x": no matching plugin found — results e.g. https://pypi.org/project/homer/0.6.0 , https://redes-abertas.readthedocs.io/en/Guias/Netbox/Render_Templates/Criando%20um%20Template/
- [S24] NetBox v4.4 release notes (#19735, `ObjectAction` registration) — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/release-notes/version-4.4.md
- [S25] Plugin search: `SearchIndex`, `@register_search` — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/search.md
