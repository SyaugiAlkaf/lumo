#!/usr/bin/env sh
# Initialize the SQLite brain once (schema + demo suppliers/rules), then serve
# the REST API. A mounted /data volume keeps state across restarts.
set -e
DB="${LUMO_DB:-/data/lumo.db}"
if [ ! -f "$DB" ]; then
    echo "lumo: initializing $DB"
    python -m lumo.cli init
fi
exec python -m lumo.api
