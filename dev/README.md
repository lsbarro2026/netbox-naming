# Dev environment

A self-contained NetBox v4.7.3 (image `netboxcommunity/netbox:v4.7.3`) with PostgreSQL 17 and Redis 7.
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

The credentials in `docker-compose.yml` are throwaway dev values.
