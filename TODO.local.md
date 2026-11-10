# TODO

## Admin

## Open

### FEAT-18 — Support NetBox 4.6.0 through 4.7.x
- **What:** Widen the plugin from NetBox 4.7.3–4.7.99 to 4.6.0–4.7.99 so one release installs and runs on both lines. Set `min_version = "4.6.0"` (keep `max_version = "4.7.99"`) in `NetBoxNamingConfig` in `netbox_naming/__init__.py`, fix whatever 4.7-only API the plugin uses, and prove it on a NetBox 4.6.0 dev stack as well as 4.7.3.
- **Why:** the user needs the plugin on a NetBox 4.6.0 install; today `PluginConfig.validate()` refuses to load it below 4.7.3.
- **Request:** "can you please expand this plugin to work with netbox version: '4.6.0'". Decision (asked 2026-11-10): support 4.6.0 **through** 4.7.x in one release, not a 4.6-only retarget or a separate branch.
- **Files:** `netbox_naming/__init__.py`, `netbox_naming/tests/test_plugin.py` (asserts the pins), `netbox_naming/migrations/0001_initial.py`, `netbox_naming/filtersets.py`, `netbox_naming/views.py`, `netbox_naming/forms.py`, `netbox_naming/tables.py`, `COMPATIBILITY.md`, `dev/Dockerfile`, `dev/docker-compose.yml`, `dev/README.md`, `README.md`.
- **Docs:** `COMPATIBILITY.md` row becomes 0.1.x ↔ 4.6.0 – 4.7.x; `dev/README.md` explains how to run against each NetBox version.
- **Gotchas:**
  - **Migration dependencies are the hard blocker.** `0001_initial.py` (generated under Django 6.1.2 on NetBox 4.7) depends on `("dcim", "0251_fix_ltree_cascade_triggers")`, `("extras", "0144_customfield_status")`, `("users", "0016_default_ordering_indexes")`. Those are 4.7 migrations (the ltree one certainly; the others assumed) and will not exist on 4.6.0, so `migrate` fails. Likely fix: point each dependency at the latest migration of that app that exists in **4.6.0** (the model only needs the tables it FKs — e.g. `users.owner`, dcim, extras). Check the FK targets exist in 4.6.0; `PrimaryModel`'s `owner` FK is documented as in the plugin API since 4.5 (`docs/plan/netbox-naming/core/research.md#F2`). Don't regenerate the migration in a way that changes its shape for existing 4.7 installs — the operations must stay identical.
  - **ltree vs MPTT.** 4.7 moved Location/DeviceRole from django-mptt to PostgreSQL `ltree` (`research.md#F1`); 4.6 is MPTT. `filtersets.py` uses `TreeNodeMultipleChoiceFilter` from `utilities.filters` — verify it exists and behaves on 4.6. Any `ltree`-specific query or method must work on both (or branch on version).
  - **Newer UI/API imports may be missing on 4.6 (assumed, verify each):** `extras.ui.panels.TagsPanel`, `netbox.ui` (`attrs`, `layout`, `panels.*`), `netbox.object_actions`, `utilities.filtersets.register_filterset`, `PrimaryModelFilterSetForm`/`PrimaryModelImportForm`, `PrimaryModelTable`. Prefer an import that exists on both lines; only fall back to a version-guarded shim where no common API exists.
  - **Version gate:** `validate()` uses `packaging.version.parse` and rejects `current > max_version`, hence `"4.7.99"`; `"4.6.0"` as min is fine. Update the asserts in `test_plugin.py`.
  - 4.6 likely ships an older Django than 4.7's 6.1 (assumed) — avoid Django-6.1-only APIs.
  - The dev stack image is pinned in `dev/Dockerfile` (`FROM netboxcommunity/netbox:v4.7.3`) and `dev/docker-compose.yml` (`image: netbox-naming-dev:v4.7.3`). Make the NetBox tag a build arg (default 4.7.3) so a 4.6.0 stack can be built from the same files; the matching netbox-docker image tag for 4.6.0 is assumed to be `v4.6.0`.
- **Acceptance:** with the dev stack built on `netboxcommunity/netbox:v4.6.0` **and** on `v4.7.3`: NetBox starts with the plugin loaded, `manage.py migrate` applies `netbox_naming.0001_initial` cleanly on a fresh DB, and the plugin's test suite (`manage.py test netbox_naming`) passes on both. `COMPATIBILITY.md` lists 4.6.0 – 4.7.x.
- **Out of scope:** NetBox 4.8 support; NetBox < 4.6.0; new features; refactoring beyond what compatibility needs; the `/publish-internal` flow.
- **Open questions:** none on scope. Whether 4.6.0's security posture warrants a min of a later 4.6.x patch (assumed: honour the request, pin 4.6.0, mention it in `COMPATIBILITY.md` only if a known issue is found).
- **Plan:** full.
- **Source:** user request, 2026-11-10.
- **Route:** judgment
