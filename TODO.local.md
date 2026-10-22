# TODO

## Admin

## Open
### FEAT-6 — [BLOCKED: FEAT-16] netbox-naming: Acceptance
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
### FEAT-16 — name-generator: Inventory pages
- **What:** Implement breakdown G3 of `docs/plan/netbox-naming/name-generator/plan.md`: `NameInventoryListView` at `inventory/`, the Inventory tab on the convention detail page (`register_model_view(NamingConvention, "inventory")` with a `ViewTab`), the Inventory menu item, `templates/netbox_naming/name_inventory.html`, `templates/netbox_naming/namingconvention_inventory.html`, and the inventory cases in `tests/test_generator_views.py`. Edits to shared files are additive only.
- **Binding plan:** plan.md is binding. Record any departure under its Deviations section. The plan docs stay in place; never delete or archive them. This is the last name-generator implementation item: set plan.md's Status to **Implemented**.
- **Why:** "The user should be able to see an intuitive list of the existing asset tags."
- **Files:** `netbox_naming/views.py`, `netbox_naming/urls.py`, `netbox_naming/navigation.py`, `netbox_naming/templates/netbox_naming/name_inventory.html`, `netbox_naming/templates/netbox_naming/namingconvention_inventory.html`, `netbox_naming/tests/test_generator_views.py`, `docs/plan/netbox-naming/name-generator/plan.md`.
- **Docs:** docs/plan/netbox-naming/name-generator/plan.md#g3-inventory-pages
- **Acceptance:** view tests pass (restricted devices not listed, menu gating); the inventory browser check passes; full suite green; plan.md Status reads Implemented.
- **Out of scope:** CSV export; changing core or management-ui pages beyond additive registration.
- **Plan:** full.
- **Route:** standard
- **Route:** standard
