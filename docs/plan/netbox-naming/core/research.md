# core — research

FEAT-1, 2026-10-22. Feeds the `core` Plan item (FEAT-2). Segment map and contracts:
[`../overview.md`](../overview.md). Every source below was accessed on **2026-10-22**; NetBox source
links point at the `v4.7.3` tag.

## Question

What must `core` (the plugin scaffold, the `NamingConvention` model, the `{token}` engine and the number
counters) be built on, so that the static, auto-numbered and custom-tail conventions from the request
can be stored, previewed and allocated safely? Specifically:

1. Which NetBox release to pin, and what the 4.x plugin API requires.
2. Which `dcim.Device` fields and relations a template can expose as tokens.
3. The uniqueness rules on `Device.asset_tag` and `Device.name`.
4. How to hand out the next number when two allocations run at the same time.
5. How to render user-written templates without letting them evaluate arbitrary expressions.
6. What "custom tail" should mean.

## Current implementation

None. At `b6f214a` the repo holds only tooling (`.gitignore`, `CLAUDE.md`, `.claude/`, the backlog) and
`docs/plan/netbox-naming/overview.md`. There is no Python package, no `pyproject.toml` and no
migration. This is **greenfield**.

To carry the goal, the plugin package must contain at least the following:

| Piece | Why it is required |
|---|---|
| `pyproject.toml` at the project root | Makes the plugin installable (`pip install -e .`) into NetBox's venv [S3] |
| `netbox_naming/__init__.py` holding a `PluginConfig` subclass and `config = <that class>` | NetBox loads the plugin by reading `config` from the package's `__init__.py` [S3] |
| `netbox_naming/models.py` | Plugin models must be defined in a file named `models.py` [S4] |
| `netbox_naming/migrations/` (`__init__.py` + `0001_initial.py`) | Generated with `manage.py makemigrations netbox_naming`, which needs `DEVELOPER=True` [S4] |
| An entry in `PLUGINS` in `configuration.py` (plugin settings go in `PLUGINS_CONFIG`) | How a plugin is enabled [S3] |

The UI files (`forms.py`, `tables.py`, `views.py`, `urls.py`, `navigation.py`, `templates/`) belong to
`management-ui`, not here.

## Findings (cited)

### F1. Version to pin: NetBox v4.7.3

- The latest stable release is **v4.7.3, published 2026-10-13**. The v4.7 line began with v4.7.0 on
  2026-09-02, and v4.6.10 (2026-09-01) was the last 4.6 release [S1][S2].
- v4.7 requires **Python 3.12, 3.13 or 3.14**, **PostgreSQL 15+** (with the `ltree` extension) and
  **Redis 6+**. It ships **Django 6.1** [S5][S6][S7].
- v4.7.2 fixed a token-exposure bug in v4.7.0–4.7.1 [S1]. That is a further reason to pin `>=4.7.3`
  rather than `4.7.0`.
- v4.7 changes that matter here [S6]:
  - Nested group models, **Location and DeviceRole among them**, are now backed by PostgreSQL `ltree`
    instead of django-mptt.
  - `level` can no longer be used in queryset filters.
  - `get_root()` and similar MPTT methods are gone.
  - Plugins that subclass nested models should use `NestedLtreeGroupModel`.
  
  `core` only reads `location.name`, so this does not affect us beyond avoiding MPTT APIs.

### F2. Plugin API (v4.7)

- **`PluginConfig` fields** [S3]:
  - `name`, `verbose_name`, `version` and `description`
  - `author` and `author_email`
  - `base_url` (defaults to `name`)
  - `required_settings` and `default_settings`
  - `django_apps`
  - `min_version` and `max_version`
  - `middleware`, `queues` and `events_pipeline`
  - dotted paths for `menu`/`menu_items`, `template_extensions`, `search_indexes`, `graphql_schema`,
    `user_preferences` and others
  
  Settings are read with `netbox.plugins.get_plugin_config()`.
- **Version gate gotcha.** `PluginConfig.validate()` compares versions with `packaging.version.parse`
  and rejects `current > max_version` [S8].
  - `max_version = "4.7"` therefore *rejects 4.7.3*, because `4.7.3 > 4.7`.
  - To accept the whole minor series, use `min_version = "4.7.3"` and `max_version = "4.7.99"`.
- **Base model.** Subclassing `netbox.models.NetBoxModel` gives:
  - tags, custom fields, change logging, event rules and export templates
  - registration of the model for those features [S4]
  
  `PrimaryModel` (in the plugin API since 4.5) adds `description`, `comments` and `owner`. It is the
  documented "go-to class for most object types" [S4]. A model meant only for internal use can set
  `_netbox_private = True` to stay out of the object-type pickers [S4].
- **Plugin API boundary.** Anything not in the plugin docs is "*not* part of the supported plugins API",
  and the docs warn plugins not to use it [S3]. `core` should import only `netbox.plugins`, the
  documented `netbox.models` classes and `dcim.models` (to read devices).
- **Packaging.** The documented `pyproject.toml` uses the setuptools build backend with
  `requires-python = ">=3.12.0"` [S3]. Adding a `COMPATIBILITY.md` with a plugin-to-NetBox version
  matrix is recommended [S3].
- **Dev NetBox to test against.**
  - **netbox-docker 5.1.x** targets NetBox v4.7.x [S9]. Its documented plugin recipe [S10] needs:
    - a `Dockerfile-Plugins` based on `netboxcommunity/netbox`, which installs the plugin with
      `uv pip install`
    - `configuration/plugins.py` setting `PLUGINS = [...]`
    - a `docker-compose.override.yml` that points `netbox` and `netbox-worker` at the custom image
  - For a local editable plugin, use a bind mount plus `pip install -e` (instead of a PyPI name in
    `plugin_requirements.txt`).
  - This machine has Docker 29.5.3, Compose v5.1.3 and Python 3.12.3 (checked 2026-10-22). Its
    PostgreSQL client is 16, and the server isn't needed locally because netbox-docker brings its own.
- **Scaffold generator.** The official cookiecutter targets "NetBox 4.5+". It generates `pyproject.toml`,
  a pytest setup, Ruff, MkDocs and GitHub Actions publishing to PyPI [S11]. It doesn't mention any
  docker or devcontainer environment.

### F3. Device fields available as tokens (from `dcim/models/devices.py` @ v4.7.3 [S12])

| Token (proposed) | Source | Nullable? | Notes |
|---|---|---|---|
| `{room}` | `device.location.name` | **yes** (`location` is `null=True`) | Settled: room = `dcim.Location`. Location names are unique only per `(site, parent)` [S13], so the same room name can recur across sites |
| `{location_slug}` | `device.location.slug` | yes | URL-safe alternative |
| `{site}` / `{site_slug}` | `device.site.name` / `.slug` | no (`site` is required) | |
| `{role}` / `{role_slug}` | `device.role.name` / `.slug` | no | DeviceRole is nested (ltree) since v4.7 [S6] |
| `{device_type}` / `{model}` | `device.device_type.model` (and `.slug`) | no | |
| `{manufacturer}` | `device.device_type.manufacturer.name` / `.slug` | no | |
| `{rack}` | `device.rack.name` | yes | |
| `{tenant}` | `device.tenant.name` / `.slug` | yes | |
| `{platform}` | `device.platform.name` / `.slug` | yes | |
| `{asset_tag}` | `device.asset_tag` | yes | Usually produced by another convention (nesting contract) |
| `{serial}` | `device.serial` | no, but `blank=True` (empty string) | |
| `{name}` | `device.name` | yes | Only useful in an asset-tag template |
| `{cf_<name>}` | `device.custom_field_data[<name>]` | yes | `custom_field_data` is a JSONField on `CustomFieldsMixin` [S14]. From v4.7, selection custom fields are returned in the API as `{value, label}` objects [S6], so render the raw stored value |

Length limits: `Device.name` has `max_length=64` and `Device.asset_tag` has `max_length=50` [S12]. A
rendered value has to fit, and the engine should check this both at preview and at allocation.

### F4. Uniqueness

- **`asset_tag` is globally unique and nullable.** The field is
  `CharField(max_length=50, blank=True, null=True, unique=True)` [S12]. A database unique index enforces
  this across *all* devices. A `##` counter with global scope, as in the request's `ap##`, therefore
  lines up with what the database enforces.
- **`name` is unique per site and tenant, case-insensitively, and optional.** The constraint is
  `UniqueConstraint(Lower('name'), 'site', 'tenant', condition=Q(name__isnull=False), nulls_distinct=False)`
  [S12]. The model docstring says "Device names are not required" [S12]. As a result:
  - The same name may exist at two sites. Two devices with no tenant collide, because
    `nulls_distinct=False` treats a NULL tenant as equal to another NULL tenant.
  - `AP-1` and `ap-1` collide at the same site/tenant.
  - A *static* name template (no number) can therefore collide as soon as two devices render the same
    tokens. The engine must report that rather than present it as valid.
- `Device.clean()` rejects a location from another site [S12], so `{room}` always belongs to
  `{site}`.

### F5. Allocating the next number when allocations run at the same time

There are three options. "Gap" means a number is skipped forever; "reuse" means a freed number is
handed out again.

| | (a) Counter row + `select_for_update` | (b) Scan existing values, max+1 | (c) Hybrid: locked counter row as a high-water mark, plus a scan |
|---|---|---|---|
| How | `NamingCounter(scope_key, last_value)`. Allocation runs in `transaction.atomic()`: `select_for_update().get(...)`, then increment and save | Inside the transaction, regex-match existing `asset_tag`s or names against the pattern and take max+1 | Lock the counter row. `next = max(counter.last_value, max_existing) + 1`, skipping any value already present. Store the new high-water mark |
| Concurrency | Serialized by the row lock [S15] | **Races**: two transactions see the same max. Needs an extra lock (the counter row, or a PostgreSQL advisory lock) or a retry on the unique violation, which works only for `asset_tag` because it is unique-indexed | Serialized by the row lock |
| Gaps | A number is spent even if the device is never created. The rollback undoes the increment *inside* the same transaction, so rollback itself leaves no gap | None beyond deletions | Same as (a) |
| Reuse | Never | Yes, after the highest-numbered device is deleted (max drops) | Never below the high-water mark |
| Drift | Ignores hand-entered values, so it can propose `ap07` while `ap07` already exists | Always matches reality | Matches reality and never moves backwards |

Supporting facts:

- `select_for_update()` locks the selected rows until the transaction ends. A second locker blocks,
  unless `nowait`, which raises `DatabaseError`, or `skip_locked` is given. Evaluating it outside a
  transaction raises `TransactionManagementError`. `TestCase` hides that error, so tests of the lock
  need `TransactionTestCase` [S15].
- A PostgreSQL `SEQUENCE` is **not** an option for "no reuse, few gaps": `nextval` is never rolled
  back, and sequences "cannot be used to obtain 'gapless' sequences" [S16]. It would also need one
  sequence per counter scope, created at runtime.
- **Preview** (the contract: next N values without using numbers up) is a plain read of the counter
  plus the same scan, with no lock and no write. Two people can preview the same numbers; only
  allocation reserves them.
- To create the counter row the first time without a race, use `get_or_create` on a unique `scope_key`,
  then `select_for_update`. A concurrent duplicate insert hits the unique constraint and retries
  (Django's documented `get_or_create` behaviour [S15]).

### F6. Template safety

- `str.format` / `format_map` with a user-controlled format string lets the template walk attributes
  and indexes. For example, `{event.__init__.__globals__[CONFIG][SECRET_KEY]}` leaks module globals.
  This is how the Jinja2 sandbox was bypassed [S17].
- The format-spec mini-language also lets a template ask for an arbitrary width, e.g. `{x:>999999999}`
  [S18]. Even with only plain strings in the context, that is a memory/CPU denial-of-service.
- NetBox's own Jinja2 rendering (export and config templates) is a different, staff-only feature. Our
  conventions are data that any user with model permissions can edit.
- Conclusion: **do not use `str.format`, `format_map`, `string.Template` with objects, or Jinja2.**
  - Parse the template with a whitelist grammar: literal text, `{token}` where `token` matches
    `[a-z][a-z0-9_]*` and is a key of a fixed registry, `#`-runs, and the tail marker.
  - Resolve each token through a function in that registry that returns a `str`.
  - Reject unknown tokens, `.`, `[`, `:` and `!` inside braces when the convention is *saved*, not only
    when it renders.

### F7. Prior art

I found no NetBox plugin that generates device names from conventions [S19]:
- `netbox-tag-id` generates prefix/suffix/length identifiers as a custom field type.
- `netbox-inventory` only syncs asset tags.
- The Ansible `netbox_device` module only accepts a name.

There is nothing to extend or reuse.

## Options

1. **Hand-scaffold to the plugin docs** (`pyproject.toml`, `PluginConfig`, `PrimaryModel` models,
   `makemigrations` in netbox-docker). This is the minimal surface that matches the overview's file
   list exactly.
2. **Generate from the cookiecutter** [S11], then trim. It is fast, but it brings MkDocs, GitHub
   Actions/PyPI publishing, an `api/` package and test layout the overview doesn't plan for. It also
   targets "4.5+" rather than a pinned 4.7.3.
3. **Fork prior art** (`netbox-tag-id`). It solves a narrower problem (one custom-field type, no
   tokens, no nesting) and would bring its own model shape.

How to number: (a), (b) or (c) from F5. How to render: whitelist parser (F6) or Jinja2 sandbox.

## Verdict: Replace (greenfield: build new)

There is no implementation to *Extend* or *Refactor* (see Current implementation), and no prior art fits
(F7), so the verdict is **Replace**, meaning build new. The recommended approach:

- **Option 1, hand-scaffold to the v4.7 plugin docs.** Use the cookiecutter only as a reference for
  `pyproject.toml` details. Evidence: the docs list exactly the files we need [S3][S4], and the
  cookiecutter's extras are out of scope for this segment [S11].
- **Pin `min_version = "4.7.3"`, `max_version = "4.7.99"`.** 4.7.3 is the latest stable release and
  fixes the 4.7.0–4.7.2 token exposure [S1]. `"4.7.99"` works around the `packaging.version` comparison
  (F2) [S8].
- **Models subclass `PrimaryModel`** (or `NetBoxModel`) [S4]. The counter is a separate
  `NamingCounter` model with a unique `scope_key`, marked `_netbox_private = True`.
- **Numbering uses (c), the hybrid.** It is the only option that is serialized [S15], never reuses a
  number, and never proposes a value that already exists, even when tags were typed in by hand. (a)
  drifts; (b) races and reuses. Because `asset_tag` is unique-indexed [S12], a bug in the lock still
  fails closed with an `IntegrityError`, not a silent duplicate.
- **Rendering uses a whitelist token parser, with no `str.format` and no Jinja2** (F6) [S17][S18].

## Risks

- **No one calls `allocate`.** The request asks to *see* names ("generate the next 5 AP names"), not
  to write them onto devices. The overview's segment map has no step that stamps a name or asset tag
  onto a `Device` (no save hook, no "apply" action). Without allocations, the counter's high-water
  mark never moves and option (c) reduces to (b) plus a lock. That is still correct, because the scan
  keeps it honest. This is not a contract *change*, since the Engine API contract still holds, so
  research does not stop here. It is listed as an open question.
- **Static conventions collide** (F4). Every device with the same tokens renders the same name. The
  generator must flag duplicates against the `(lower(name), site, tenant)` constraint.
- **`{room}` is null** for devices without a location (F3). An "empty" rendering such as `-ap01` would
  be accepted silently.
- **Number overflow.** `ap##` runs out at `ap99`. Widening to `ap100` breaks the pattern's regex for
  later scans, and the width is part of the contract ("width is the run length").
- **Pattern match on hand-entered values.** The scan regex for `ap##` must be anchored to the whole
  rendered prefix and suffix (`^ap(\d{2})$`), or `ap01-old` / `xap05` would count. Matching is
  case-sensitive on `asset_tag` but needs to be case-insensitive on `name` (F4).
- **Upgrade churn.** v4.7 renamed and removed internals [S6]. Staying inside the documented plugin API
  (F2) is the mitigation. `max_version = "4.7.99"` means a deliberate bump to support 4.8.
- **Lock-test blind spot.** Under Django's `TestCase`, `select_for_update` does not raise outside a
  transaction [S15]. Concurrency tests need `TransactionTestCase`, against PostgreSQL in netbox-docker.

## Open questions for the plan

1. **What "custom tail" means. Proposal:** a convention whose template ends in a `{tail}` marker,
   e.g. `{room}-{role_slug}-{tail}`. The token prefix renders from device fields as usual, and the
   **user types the tail as free text** when generating or allocating, e.g. `lobby-east`. The
   convention stores the tail's rules: a regex of allowed characters (default `[A-Za-z0-9-]+`), and a
   maximum length checked so the full value fits in `name` (64) or `asset_tag` (50). Alternatives for
   the user to choose from:
   - (b) a fixed suffix stored on the convention, which would really be a static convention;
   - (c) a tail picked from a list stored on the convention;
   - (d) a numbered tail that the user may override.
   
   **Needs the user's answer.** The plan assumes the proposal.
2. **Is allocation in scope?** Should anything actually write generated values onto devices: a
   pre-save default, a "reserve" button, or a REST endpoint? Or is preview the whole deliverable, with
   `allocate` built only for the API contract? This decides whether `NamingCounter` ever moves (see
   Risks).
3. **Gap reuse.** Should numbers freed by deleting a device be handed out again? The recommendation
   is *no* (monotonic, so retired physical labels aren't reissued). The alternative is "lowest free
   number".
4. **What happens on overflow** (`ap##` past 99): refuse with a clear error (recommended), or widen?
5. **What a null token renders as** (no location, no tenant): refuse to render (recommended), or use
   a per-convention fallback string?
6. **Which Location field `{room}` reads**: `name` (assumed), `slug` or `facility`?
7. **Should the convention type be explicit or inferred?** The contract keeps an explicit type field.
   The plan should still validate it against the template: auto-numbered ⇔ exactly one `#`-run;
   custom tail ⇔ ends in `{tail}`; static ⇔ neither.

## Sources

- [S1] NetBox releases (GitHub API: v4.7.3 2026-10-13, v4.7.2 2026-09-29, v4.7.0 2026-09-02, v4.6.10 2026-09-01) — https://api.github.com/repos/netbox-community/netbox/releases — accessed 2026-10-22
- [S2] `netbox/release.yaml` @ v4.7.3 (`version: "4.7.3"`, `published: "2026-10-13"`) — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/release.yaml — accessed 2026-10-22
- [S3] Plugin development index (structure, `PluginConfig` attributes, `pyproject.toml`, compatibility matrix) @ v4.7.3 — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/index.md (rendered: https://netboxlabs.com/docs/netbox/plugins/development/) — accessed 2026-10-22
- [S4] Plugin database models (`NetBoxModel`, `PrimaryModel`, `_netbox_private`, migrations, `DEVELOPER=True`) @ v4.7.3 — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/plugins/development/models.md — accessed 2026-10-22
- [S5] Installation requirements (Python 3.12/3.13/3.14) @ v4.7.3 — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/installation/index.md — accessed 2026-10-22
- [S6] NetBox v4.7 release notes (PostgreSQL 15+, ltree, breaking changes, v4.7.2 fix) @ v4.7.3 — https://github.com/netbox-community/netbox/blob/v4.7.3/docs/release-notes/version-4.7.md (rendered: https://netboxlabs.com/docs/netbox/release-notes/version-4.7) — accessed 2026-10-22
- [S7] `base_requirements.txt` @ v4.7.3 (`Django==6.1.*`) — https://github.com/netbox-community/netbox/blob/v4.7.3/base_requirements.txt — accessed 2026-10-22
- [S8] `PluginConfig.validate()` @ v4.7.3, `netbox/netbox/plugins/__init__.py` L190–208 — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/netbox/plugins/__init__.py#L190-L208 — accessed 2026-10-22
- [S9] netbox-docker releases (5.1.1/5.1.0: "v4.7.x and above") — https://github.com/netbox-community/netbox-docker/releases — accessed 2026-10-22
- [S10] netbox-docker wiki, "Using Netbox Plugins" — https://github.com/netbox-community/netbox-docker/wiki/Using-Netbox-Plugins — accessed 2026-10-22
- [S11] cookiecutter-netbox-plugin ("target NetBox 4.5+") — https://github.com/netbox-community/cookiecutter-netbox-plugin — accessed 2026-10-22
- [S12] `dcim/models/devices.py` @ v4.7.3: `Device` fields L531–613, `Meta.constraints` L809–823, `clean()` location/site check L851 — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/dcim/models/devices.py — accessed 2026-10-22
- [S13] `dcim/models/sites.py` @ v4.7.3: `Location(NestedLtreeGroupModel)` L289, unique `(site, parent, name)` / `(site, parent, slug)` — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/dcim/models/sites.py — accessed 2026-10-22
- [S14] `netbox/models/features.py` @ v4.7.3: `CustomFieldsMixin.custom_field_data` JSONField L197 — https://github.com/netbox-community/netbox/blob/v4.7.3/netbox/netbox/models/features.py — accessed 2026-10-22
- [S15] Django 6.1 QuerySet API reference, `select_for_update()` and `get_or_create()` — https://docs.djangoproject.com/en/6.1/ref/models/querysets/ — accessed 2026-10-22
- [S16] PostgreSQL 18 docs, Sequence Manipulation Functions (caution on gaps) — https://www.postgresql.org/docs/current/functions-sequence.html — accessed 2026-10-22
- [S17] Armin Ronacher, "Be Careful with Python's New-Style String Format", 2016-12-29 — https://lucumr.pocoo.org/2016/12/29/careful-with-str-format/ — accessed 2026-10-22
- [S18] Python docs, Format Specification Mini-Language (width field) — https://docs.python.org/3/library/string.html#format-specification-mini-language — accessed 2026-10-22
- [S19] Prior-art search: netbox-tag-id https://pypi.org/project/netbox-tag-id/ ; netbox-inventory https://pypi.python.org/project/netbox-inventory/1.0.3/ ; Ansible `netbox_device` https://docs.ansible.com/projects/ansible/latest/collections/netbox/netbox/netbox_device_module.html — accessed 2026-10-22
