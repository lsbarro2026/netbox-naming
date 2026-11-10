# Dev environment

A self-contained NetBox (default v4.7.3, image `netboxcommunity/netbox:v4.7.3`; see below for others) with PostgreSQL 17 and Redis 7.
The repo is bind-mounted at `/opt/netbox-naming` and installed editable (`pip install -e` equivalent,
done at image build), so edits show up without a rebuild. `dev/configuration/plugins.py` enables the
plugin and `DEVELOPER=true` is set so `makemigrations` works.

Run these from `dev/`:

```sh
# Bring it up (first start runs NetBox migrations; UI at http://localhost:8000, admin / admin)
docker compose up

# Generate migrations (writes into netbox_naming/migrations/ on the host)
docker compose exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py makemigrations netbox_naming

# Run the tests (PostgreSQL; --keepdb reuses the test database)
docker compose exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py test netbox_naming --keepdb
```

Check the plugin loads: `manage.py check`, or **Admin → Plugins** in the UI.

## Other NetBox versions

The NetBox image tag is the `NETBOX_VERSION` build arg (default `v4.7.3`). To run against the oldest
supported version, give it its own compose project so it gets its own database volume — a NetBox 4.6
database must never be one that 4.7 has already migrated:

```sh
NETBOX_VERSION=v4.6.0 docker compose -p netbox-naming-dev-v46 up --build
NETBOX_VERSION=v4.6.0 docker compose -p netbox-naming-dev-v46 exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py test netbox_naming --keepdb
```

Both stacks publish port 8000, so run one at a time.

Generate migrations on the default 4.7 stack, then check the new file's `dependencies` name only
NetBox migrations that exist in 4.6.0 (normally it depends only on this plugin's previous migration).
On 4.6, `makemigrations` reports an `AlterField` on `owner`: 4.7 added `related_name="+"` to
NetBox's owner FK, a state-only difference with no schema change. Don't commit that migration.

The credentials in `docker-compose.yml` are throwaway dev values.
