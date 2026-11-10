ARG NETBOX_VERSION=v4.7.3
FROM netboxcommunity/netbox:${NETBOX_VERSION}

# Editable install of the plugin into the image's venv. docker-compose.yml bind-mounts the repo over
# /opt/netbox-naming, so the editable install then resolves to the live source tree.
COPY pyproject.toml /opt/netbox-naming/pyproject.toml
COPY netbox_naming /opt/netbox-naming/netbox_naming
RUN /usr/local/bin/uv pip install --python /opt/netbox/venv/bin/python -e /opt/netbox-naming
