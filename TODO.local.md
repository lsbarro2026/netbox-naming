# TODO

## Admin

## Open
### FEAT-5 — name-generator: Plan asset-tag list and next-N name preview
- **What:** Plan segment `name-generator` of `netbox-naming`. This segment has no research item. Open plan.md with a short current-state survey of `docs/plan/netbox-naming/core/plan.md` (the engine's preview/allocate API and the counter storage) and whatever has landed under `netbox_naming/` (`engine.py`, `models.py`, and `views.py`/`templates/` from `management-ui` if present). Give the Extend / Refactor-then-extend / Replace verdict yourself, with a reason. Write `docs/plan/netbox-naming/name-generator/plan.md` with: Status (Draft → Approved → Implemented) · Decision · Design · Contracts (pointing at overview.md, not restating it) · Test strategy · Implementation breakdown (one entry per implementation item: scope, files, route, acceptance) · Deviations (empty). The design covers two views. (a) An intuitive list of existing asset tags (and names) per convention, showing which numbers are taken and the next free one. (b) A form where the user picks a device role or device type (plus a Location for `{room}`-style tokens) and a count N, and sees the next N names and asset tags. Generating must be a read-only preview through the engine's non-allocating API: it never uses up numbers. Planned files: `netbox_naming/generator.py`, a view in `netbox_naming/views.py`, a template under `netbox_naming/templates/`. Note in the plan that `views.py`/`urls.py`/`navigation.py` are shared with `management-ui`, and keep edits there additive. Your `/plan-todo` plan-mode plan is an outline of plan.md with the verdict up front, so my approval of it is the sign-off on extend vs replace; set Status to Approved when I approve.
- **ADR:** a Replace verdict, or any architecture decision, also gets an ADR, but only if `python3 .claude/todo-lock.py seq list` shows an `adr` sequence: reserve it with `seq reserve adr --claim FEAT-5` (`.claude/skills/plan-todo/todo-planning-reference.md`, "Reserving a sequence number"). Without one, the decision lives in plan.md's Decision section.
- **Filing the implementation items** (from this item's worktree, after plan.md is written): one `python3 .claude/todo-lock.py add-bulk --chain --commit --file <path>` call, the JSON written with the Write tool. The first item is `"blocked_by"` FEAT-5 (legal while it's in progress; the gate clears when it lands). Route each item honestly with `/todo`'s table, and give each `- **Docs:** docs/plan/netbox-naming/name-generator/plan.md#<its breakdown section>`. Each implementation body says: plan.md is binding; any departure is recorded under its Deviations section; the last item sets Status to Implemented; the plan docs stay in place and are never deleted or archived.
- **Re-gate Acceptance:** after filing them, run `python3 .claude/todo-lock.py block FEAT-6 --blocked-by <last implementation id> --commit`, before `/finish`. `block` refuses a claimed item, but FEAT-6 can't be claimed: it's gated on this Plan item until this lands.
- **Why:** previewing upcoming names ("the next 5 APs") is the user-facing payoff of the conventions, and it must not use up numbers it only shows.
- **Request:** "The user should be able to see an intuitive list of the existing asset tags, and generate a list of the next x devices of a device type. So, if I wanted to see what the next 5 ap's would be called, I can generate their names."
- **Files:** `docs/plan/netbox-naming/name-generator/plan.md` (new).
- **Docs:** `docs/plan/netbox-naming/overview.md`, `docs/plan/netbox-naming/core/plan.md`.
- **Acceptance:** plan.md has every section above with Status Approved; `todo-lock.py summary` shows the implementation chain, its first item gated on FEAT-5; `todo-lock.py show FEAT-6` shows it blocked on the chain's last item.
- **Re-segmentation stop:** if planning shows the segmentation is wrong (segments should merge or split, a new one is needed, or a contract in overview.md must change), write it up in plan.md and stop and surface it to the user before filing anything. Don't re-cut other segments.
- **Out of scope:** writing the implementation itself; changing the engine or model (`core`); convention CRUD pages (`management-ui`); assigning names to real devices; other segments' docs and items.
- **Open questions:** none.
- **Plan:** full.
- **Source:** /todo-expanded, 2026-10-22.
- **Route:** judgment

### FEAT-6 — [BLOCKED: FEAT-13] [BLOCKED: FEAT-10] [BLOCKED: FEAT-5] netbox-naming: Acceptance
- **What:** Check `netbox-naming` end to end against the original request in `docs/plan/netbox-naming/overview.md` ("Request"), once every segment has landed. Turn each clause of the request into an observable check. At minimum: the plugin has its own page in NetBox; static, auto-numbered and custom-tail conventions can be created; an access-point-role convention `{room}-{asset_tag}` with an asset-tag convention `ap##` (globally scoped) renders correctly, with `{room}` taken from the device's Location; the existing asset tags list is readable; generating the next 5 APs shows 5 correct names and uses up no numbers. Run the test suite, then exercise the feature in a running NetBox. Write the results to `docs/plan/netbox-naming/acceptance.md`: each check, pass/fail, and the evidence. File every gap as its own bug through `/plan-todo`'s spin-off protocol (`.claude/skills/plan-todo/todo-planning-reference.md`, "Spinning off work"), not fixed inline.
- **Why:** each segment was verified against its own plan; this checks that together they deliver what was asked.
- **Request:** "Hello, I would like you to build a netbox plugin for naming conventions".
- **Files:** `docs/plan/netbox-naming/acceptance.md` (new).
- **Docs:** `docs/plan/netbox-naming/overview.md`, `docs/plan/netbox-naming/core/plan.md`, `docs/plan/netbox-naming/management-ui/plan.md`, `docs/plan/netbox-naming/name-generator/plan.md`.
- **Gate:** blocked on every segment's Plan item at filing; each Plan item re-gates this onto its last implementation item, so it's claimable only once all of them have landed.
- **Acceptance:** acceptance.md lists one check per request clause with its result; every failing check has a filed bug id next to it.
- **Out of scope:** fixing the gaps it finds; changing any plan.md.
- **Open questions:** none.
- **Plan:** full.
- **Source:** /todo-expanded, 2026-10-22.
- **Route:** judgment

### FEAT-7 — core: Scaffold plugin package and dev environment
- **What:** Implement breakdown B1 of `docs/plan/netbox-naming/core/plan.md`: `pyproject.toml`, `netbox_naming/__init__.py` (`NetBoxNamingConfig`, `base_url = "naming"`, `min_version = "4.7.3"`, `max_version = "4.7.99"`), empty `netbox_naming/migrations/` and `netbox_naming/tests/` packages, the `dev/` Docker Compose environment (PostgreSQL, Redis, `netboxcommunity/netbox` for v4.7.3, repo bind-mounted and `pip install -e`'d, `PLUGINS = ["netbox_naming"]`, `DEVELOPER = True`) with `dev/README.md`, and `COMPATIBILITY.md`.
- **Binding plan:** plan.md is binding. Record any departure under its Deviations section. The plan docs stay in place; never delete or archive them.
- **Why:** every later core item needs an installable plugin and a real NetBox + PostgreSQL to test against.
- **Files:** `pyproject.toml`, `netbox_naming/__init__.py`, `netbox_naming/migrations/__init__.py`, `netbox_naming/tests/__init__.py`, `netbox_naming/tests/test_plugin.py`, `dev/`, `COMPATIBILITY.md`.
- **Docs:** docs/plan/netbox-naming/core/plan.md#b1-scaffold-and-dev-environment
- **Acceptance:** `docker compose up` in `dev/` serves NetBox 4.7.3 with the plugin installed; `manage.py check` is clean; a smoke test asserting the plugin is loaded passes via `manage.py test netbox_naming`.
- **Out of scope:** models, engine, UI files.
- **Plan:** full.
- **Route:** standard

### FEAT-8 — [BLOCKED: FEAT-7] core: Template grammar and token registry
- **What:** Implement breakdown B2 of `docs/plan/netbox-naming/core/plan.md`: the whitelist template parser (literals, `{token}`, one `#`-run of width 1–9, `{tail}` last, no escapes), the token registry from the plan's table, and the `NamingError` exception hierarchy.
- **Binding plan:** plan.md is binding. Record any departure under its Deviations section. The plan docs stay in place; never delete or archive them.
- **Why:** the model's `clean()` (B3) and the engine (B4) both parse templates; rendering must never evaluate user input (research F6).
- **Files:** `netbox_naming/templating.py`, `netbox_naming/exceptions.py`, `netbox_naming/tests/test_templating.py`.
- **Docs:** docs/plan/netbox-naming/core/plan.md#b2-template-grammar-and-token-registry
- **Acceptance:** parser/registry `SimpleTestCase` tests pass, including every rejection rule and the F6 injection strings; no `str.format`, `format_map`, `string.Template` or Jinja2 in the module.
- **Out of scope:** counters, preview/allocate, models.
- **Plan:** full.
- **Route:** standard

### FEAT-9 — [BLOCKED: FEAT-8] core: NamingConvention and NamingCounter models and migration
- **What:** Implement breakdown B3 of `docs/plan/netbox-naming/core/plan.md`: `choices.py`, `NamingConvention(PrimaryModel)` with the plan's fields, constraints and `clean()` rules, `NamingCounter(models.Model)`, and `0001_initial` generated with `makemigrations` in the dev container.
- **Binding plan:** plan.md is binding. Record any departure under its Deviations section. The plan docs stay in place; never delete or archive them.
- **Why:** `management-ui` and `name-generator` build against this model (overview Contracts).
- **Files:** `netbox_naming/choices.py`, `netbox_naming/models.py`, `netbox_naming/migrations/0001_initial.py`, `netbox_naming/tests/test_models.py`.
- **Docs:** docs/plan/netbox-naming/core/plan.md#b3-models-and-migration
- **Acceptance:** `makemigrations --check` reports no changes; model validation tests (each `clean()` rule, both constraints, PROTECT on role delete) pass.
- **Out of scope:** engine, forms/views.
- **Plan:** full.
- **Route:** standard

### FEAT-10 — [BLOCKED: FEAT-9] core: Naming engine preview, allocate, counters and nesting
- **What:** Implement breakdown B4 of `docs/plan/netbox-naming/core/plan.md`: `NamingContext`, `Proposal`, `find_convention`, `preview` (no locks, no writes) and `allocate` (one transaction, `get_or_create` + `select_for_update` on each counter, dependency first), the hybrid scan-plus-counter numbering, collision skipping in each field's uniqueness domain, and nesting.
- **Binding plan:** plan.md is binding. Record any departure under its Deviations section. The plan docs stay in place; never delete or archive them. This is the last core implementation item: set plan.md's Status to **Implemented**.
- **Why:** `name-generator` (FEAT-5) consumes the engine API; it is the core of the request's 'generate the next 5 AP names'.
- **Files:** `netbox_naming/engine.py`, `netbox_naming/tests/test_engine.py`, `netbox_naming/tests/test_allocation.py`, `docs/plan/netbox-naming/core/plan.md`.
- **Docs:** docs/plan/netbox-naming/core/plan.md#b4-engine-preview-allocate-counters-nesting
- **Acceptance:** engine `TestCase` tests and the `TransactionTestCase` concurrency test pass on PostgreSQL; the full `netbox_naming` suite is green; plan.md Status reads Implemented.
- **Out of scope:** writing values onto Devices; UI; the next-N page.
- **Plan:** full.
- **Route:** judgment

### FEAT-11 — [BLOCKED: FEAT-9] management-ui: Naming convention CRUD pages and menu
- **What:** Implement breakdown M1 of `docs/plan/netbox-naming/management-ui/plan.md`: filterset, model/filter/import forms (plain template input, no preview fieldset yet), table, generic list/detail/edit/delete/bulk-import/bulk-delete views with the declared list `actions`, `SimpleLayout` detail page without the sample panel, `urls.py`, the "Naming" `PluginMenu`, and `search.py`.
- **Binding plan:** plan.md is binding. Record any departure under its Deviations section. The plan docs stay in place; never delete or archive them.
- **Why:** this is the plugin's own page where users store and manage naming conventions (overview Request).
- **Files:** `netbox_naming/filtersets.py`, `netbox_naming/forms.py`, `netbox_naming/tables.py`, `netbox_naming/views.py`, `netbox_naming/urls.py`, `netbox_naming/navigation.py`, `netbox_naming/search.py`, `netbox_naming/templates/netbox_naming/`, `netbox_naming/tests/test_views.py`, `netbox_naming/tests/test_filtersets.py`.
- **Docs:** docs/plan/netbox-naming/management-ui/plan.md#m1-crud-pages-and-menu
- **Acceptance:** CRUD view, filterset and navigation tests pass; the "Naming" menu lists Naming Conventions in the dev NetBox; full suite green.
- **Out of scope:** REST API (M2), live preview and sample panel (M3), model/engine changes (`core`), generator pages (FEAT-5).
- **Plan:** full.
- **Route:** standard

### FEAT-12 — [BLOCKED: FEAT-11] management-ui: Naming convention REST API
- **What:** Implement breakdown M2 of `docs/plan/netbox-naming/management-ui/plan.md`: `NamingConventionSerializer`, `NamingConventionViewSet` with the filterset, and the `NetBoxRouter` in `api/urls.py`, so the API, event rules and webhooks work.
- **Binding plan:** plan.md is binding. Record any departure under its Deviations section. The plan docs stay in place; never delete or archive them.
- **Why:** event rules serialize objects via `get_serializer_for_model()` and fail without a plugin serializer (research F9).
- **Files:** `netbox_naming/api/__init__.py`, `netbox_naming/api/serializers.py`, `netbox_naming/api/views.py`, `netbox_naming/api/urls.py`, `netbox_naming/tests/test_api.py`.
- **Docs:** docs/plan/netbox-naming/management-ui/plan.md#m2-rest-api
- **Acceptance:** API tests pass; `get_serializer_for_model(NamingConvention)` resolves; full suite green.
- **Out of scope:** GraphQL, UI changes, model/engine changes.
- **Plan:** full.
- **Route:** routine

### FEAT-13 — [BLOCKED: FEAT-12] [BLOCKED: FEAT-10] management-ui: Live template editor and sample values
- **What:** Implement breakdown M3 of `docs/plan/netbox-naming/management-ui/plan.md`: `preview.py` (parse → `clean()` → `engine.preview` with shape-mode fallback), the `TemplateInput` htmx widget, preview-only form fields, the hand-secured `TemplatePreviewView` (permission gate per plan Decision 4), the detail page's `SampleValuesPanel`, and their templates. Then set plan.md's Status to Implemented.
- **Binding plan:** plan.md is binding. Record any departure (including any gap in core's API from plan §Consumed core surface) under its Deviations section. This is the last item: set Status to Implemented. The plan docs stay in place; never delete or archive them.
- **Why:** the request asks for an intuitive editor: unknown tokens flagged inline and a live sample render.
- **Files:** `netbox_naming/preview.py`, `netbox_naming/widgets.py`, `netbox_naming/forms.py`, `netbox_naming/views.py`, `netbox_naming/urls.py`, `netbox_naming/templates/netbox_naming/widgets/template_input.html`, `netbox_naming/templates/netbox_naming/inc/template_preview.html`, `netbox_naming/tests/test_preview.py`, `docs/plan/netbox-naming/management-ui/plan.md`.
- **Docs:** docs/plan/netbox-naming/management-ui/plan.md#m3-live-template-editor-and-sample-values
- **Acceptance:** preview tests pass (permission matrix, hidden ids absent, shape fallback, conflicts, count cap, no counter writes); browser check in the dev NetBox done; full suite green; plan Status reads Implemented.
- **Out of scope:** calling `allocate`; generator pages (FEAT-5); model/engine changes.
- **Plan:** full.
- **Route:** judgment
