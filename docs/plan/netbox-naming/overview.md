# NetBox naming conventions plugin — plan overview

Filed by `/todo-expanded` on 2026-10-22. Each segment's research and plan live in
`docs/plan/netbox-naming/<segment>/`. These docs stay after the work lands; they're never deleted.

## Request

> Hello, I would like you to build a netbox plugin for naming conventions:
>
> How it should work:
>
> It should have its own page in netbox, where a user will go to to store the naming conventions. For naming conventions, a user should be able to have a static, auto numbered, or custom tail naming convention. For each of these, they will be built using the netbox fields, e.g. a naming convention for the access point role  could be '{room}-{asset_tag}', where the asset tag for the access point role has its own convention: 'ap##' where ## is a globally scoped number.
>
> The user should be able to see an intuitive list of the existing asset tags, and generate a list of the next x devices of a device type. So, if I wanted to see what the next 5 ap's would be called, I can generate their names.

Decisions already settled with the user (2026-10-22):

- `{room}` means the device's NetBox **Location** (`dcim.Location`). Template tokens map to native NetBox device fields.
- Target **the latest stable NetBox 4.x**. The `core` research pins the exact minor version.

## State at filing

The repo held only tooling (`.gitignore`, `CLAUDE.md`, the backlog). No plugin code existed yet. This is greenfield work.

## Segments

| Segment | Covers | Files | Chain | Research |
|---|---|---|---|---|
| `core` | Plugin scaffold (`pyproject.toml`, `PluginConfig`); the `NamingConvention` model and migrations; the static / auto-numbered / custom-tail types; the `{field}` token engine; number counters (global or scoped) | `pyproject.toml`, `netbox_naming/__init__.py`, `netbox_naming/models.py`, `netbox_naming/engine.py`, `netbox_naming/migrations/` | FEAT-1 → FEAT-2 | yes: the NetBox 4.x plugin API, which device fields tokens can use, asset_tag uniqueness, and allocating numbers safely when allocations run at the same time |
| `management-ui` | The plugin's own page: CRUD for conventions, the nav menu, forms that check templates | `netbox_naming/forms.py`, `netbox_naming/tables.py`, `netbox_naming/views.py`, `netbox_naming/urls.py`, `netbox_naming/navigation.py`, `netbox_naming/templates/` | FEAT-3 → FEAT-4 | yes: NetBox generic views, tables, filtersets and the navigation API |
| `name-generator` | A list of existing asset tags and names per convention; "generate the next N" for a role or device type | `netbox_naming/generator.py`, its view and template | FEAT-5 | no: builds on `core`'s engine and `management-ui`'s view patterns |

Acceptance: FEAT-6. It is gated on every segment's Plan item, then on each segment's last
implementation item.

## Contracts

What the segments must agree on. A segment changes a contract only by stopping and raising it
(see below), never on its own.

- **Convention model**: `NamingConvention` in `netbox_naming/models.py`. It holds a type (static | auto-numbered | custom tail), a template string with `{token}` placeholders, and what it applies to (a device role and/or device type), and it targets a device field (`name` or `asset_tag`). `core` produces it; `management-ui` and `name-generator` consume it. `core`'s plan fixes the exact fields.
- **Number placeholder**: a run of `#` in a template (`ap##`) is a zero-padded auto number whose width is the run length. Each convention declares its counter scope (global by default). `core` produces it; everyone consumes it.
- **Nesting**: a name template can reference a field another convention produces (for example `{room}-{asset_tag}`, where `asset_tag` comes from its own `ap##` convention). The engine resolves the dependency first.
- **Engine API**: a preview function returns the next N rendered values for a convention and a context (role/type, plus location for `{room}`) **without using up numbers**. A separate allocate step does use them up, atomically. `core` produces it; `name-generator` consumes it. `core`'s plan fixes the signature.
- **URLs**: everything lives under the plugin's `base_url` (`naming` assumed), so the pages are at `/plugins/naming/…`.

## Dependency order

`management-ui` and `name-generator` both wait on `core`'s Plan item (FEAT-2). Their forms, tables and generator calls are built against the model and engine API that plan fixes. `management-ui` and `name-generator` don't wait on each other. `name-generator` reuses `management-ui`'s view idioms (assumed), but its own Plan can follow NetBox's standard pattern without it.

## Re-segmentation

If research or planning shows this split is wrong (segments should merge or split, a new one is
needed, or a contract above must change), the item that finds it writes it up in its own doc and
stops for the user before filing anything. It does not re-cut other segments itself.
