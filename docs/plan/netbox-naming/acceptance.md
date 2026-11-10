# netbox-naming — acceptance (FEAT-6)

Run 2026-11-10 against base `024034f`, NetBox 4.7.3 (`dev/docker-compose.yml`, plugin 0.1.0
mounted from the worktree), as `admin`. Checks the plugin as a whole against the request in
[overview.md](overview.md#request). Result: **all 13 checks pass; no bugs filed.**

## Fixture

Seeded through `nbshell`: sites HQ (`hq`) and Branch (`branch`); locations R101 (HQ) and R202
(Branch); manufacturer Acme with device types AP-500 and SW-48; roles Access Point, Core and
Patch Panel. There are three Access Point / AP-500 devices: `R101-ap01` (tag `ap01`, R101),
`R101-ap02` (`ap02`, R101) and `R202-ap04` (`ap04`, R202). Before the run there were no
conventions and no counters.

Conventions:

| Name | Created via | Kind | Field | Template | Applies to | Scope |
|---|---|---|---|---|---|---|
| AP asset tag | UI form | numbered | asset_tag | `ap##` | role Access Point | global |
| AP name | UI form | static | name | `{room}-{asset_tag}` | role Access Point | — |
| Core switch | REST API | static | name | `{site_slug}-core` | role Core | — |
| Patch panel | REST API | tail | name | `pp-{room}-{tail}`, max tail 4 | role Patch Panel | — |
| SW-48 name | REST API | numbered | name | `{site_slug}-sw##` | device type SW-48 | per site |

## Results

| # | Request clause | Check | Result |
|---|---|---|---|
| T0 | (all) | `manage.py test netbox_naming --keepdb` | pass |
| A1 | "its own page in netbox" | Naming menu; plugin pages return 200; listed under Plugins | pass |
| A2 | "a user will go to to store the naming conventions" | Create via the UI form and the API; listed on the page and the API | pass |
| A3 | "static" | Static template renders literal plus field | pass |
| A4 | "auto numbered" | `##` renders zero-padded, 2 wide | pass |
| A5 | "custom tail" | Tail renders; an over-long or missing tail is refused | pass |
| A6 | "built using the netbox fields" | Tokens come from device fields; an unknown token is refused | pass |
| A7 | `'{room}-{asset_tag}'` for the AP role, `{room}` = Location | Nested name renders with the Location name | pass |
| A8 | `'ap##'`, "## is a globally scoped number" | One counter across both sites/locations | pass |
| A9 | "an intuitive list of the existing asset tags" | Inventory list and the convention's Inventory tab | pass |
| A10 | "what the next 5 ap's would be called" | Generate shows 5 correct name/tag pairs | pass |
| A11 | "see … generate their names" (preview only) | No counter or device written; output stable | pass |
| A12 | "the next x devices of a device type" | Generation by device type | pass |

## Evidence

**T0.** `Found 225 test(s)` … `OK`.

**A1.** The nav bar shows a **Naming** menu (icon `mdi-label-outline`) with *Naming Conventions*,
*Generate names* and *Inventory*. These all return HTTP 200: `/plugins/naming/namingconvention/`,
`/plugins/naming/namingconvention/2/`, `/plugins/naming/namingconvention/2/inventory/`,
`/plugins/naming/generate/`, `/plugins/naming/inventory/`, `/core/plugins/netbox_naming/`. The
`/core/plugins/` row reads `Naming Conventions | lsbarro | … | 0.1.0`.

**A2.** The UI add form POSTs returned `302 → /plugins/naming/namingconvention/2/` and `…/3/`.
The API POSTs to `/api/plugins/naming/namingconventions/` returned `201` three times.
`GET …/namingconventions/?brief=1` gave `"count": 5` with all five names.

**A3.** `generate/?role=<Core>&location=R202&count=3` gave `branch-core`. Rows 2–3 read
`branch-core Already taken`: a static name gives one value, and the page flags the repeats
instead of passing them off as distinct. This is expected for a static kind.

**A4 / A7 / A10.** `generate/?role=<Access Point>&location=R101&count=5`, under the header
"Name convention: AP name · Asset tag convention: AP asset tag":

```
1 | R101-ap05 | ap05
2 | R101-ap06 | ap06
3 | R101-ap07 | ap07
4 | R101-ap08 | ap08
5 | R101-ap09 | ap09
```

`R101` is the Location name (`{room}`). The nested `{asset_tag}` matches the asset-tag column.
`ap03` is skipped on purpose: numbers are monotonic and gaps aren't reused (core plan Q3), and
the inventory pages say so.

**A5.** With `tail=A1` the name is `pp-R101-A1`. With `tail=TOOLONG` there are 0 rows and the
message "Name: Tail 'TOOLONG' is longer than 4 characters". With no tail there are 0 rows and the
message "Enter a tail: the name template uses {tail}."

**A6.** `{room}`, `{site_slug}` and `{asset_tag}` resolve from the device context (above). The
UI form with template `{bogus}` re-rendered (200, not saved) with "Unknown token {bogus} at
position 0".

**A8.** Run from the other location (`role=<Access Point>&location=R202&count=3`):
`R202-ap05`, `R202-ap06`, `R202-ap07`. The numbering continues from `ap04` (R202) past
`ap01`/`ap02` (R101), so it is one global series. Compare `SW-48 name` (per site), which starts
at `branch-sw01`.

**A9.** `/plugins/naming/inventory/` shows one row per convention:

```
Convention   | Template           | Field     | Counter scope | In use | Highest | Next free
AP asset tag | ap##               | Asset tag | Global        | 3      | ap04    | ap05
AP name      | {room}-{asset_tag} | Name      | Global        | 3      | —       | —
```

The *AP asset tag* Inventory tab shows "Taken: 1–2, 4 · Highest: ap04 · Next free: ap05" and a
device table (`R101-ap01 | ap01 | 1 | Access Point | AP-500 | R101`, and so on). It counts as
intuitive because each value sits next to its device, role, type and location, and gaps are
labelled as skipped.

**A11.** Before: `COUNTERS []`, the three devices. Two identical GETs to the A10 URL gave
byte-identical page text (`cmp` clean). After: `COUNTERS []`, the same three devices. The page
says "Nothing is saved or used up, so running it again shows the same values." The view is
GET-only (`http_method_names`).

**A12.** `generate/?device_type=SW-48&location=R202&count=3` gave `branch-sw01`, `branch-sw02`,
`branch-sw03` (the type-only convention). `device_type=AP-500` alone gave "No name convention
matches…", which is correct because the AP conventions are role-scoped. `role=Access
Point&device_type=AP-500` falls back to the role convention (`R202-ap05`…).

## Observations (not failures)

- For a role-only query, the message "No asset tag convention matches this role and device
  type" names a device type that wasn't given. The wording is slightly off; it isn't a gap
  against the request.
- The inventory list shows "Counter scope: Global" for static and tail conventions, where the
  field doesn't apply (the model's help text says so).
