# netbox-naming

A NetBox plugin that generates and validates device names from naming conventions.

It adds a **Naming** menu with three pages:

- **Naming Conventions**: define name and asset tag templates, scoped by device role and type.
- **Generate names**: preview the next names or asset tags a convention will produce.
- **Inventory**: list the values already in use for each convention.

## Install

Install into the NetBox virtual environment:

```sh
source /opt/netbox/venv/bin/activate
pip install git+ssh://git@gitlab.triumf.ca/ist/net/netbox-naming.git
```

Enable the plugin in `configuration.py`:

```python
PLUGINS = ["netbox_naming"]
```

Apply the database migrations and restart NetBox:

```sh
cd /opt/netbox/netbox
python manage.py migrate
```

## Compatibility

See [COMPATIBILITY.md](COMPATIBILITY.md) for supported NetBox versions.

## Development

See [dev/README.md](dev/README.md) for the local Docker environment and how to run the tests.
