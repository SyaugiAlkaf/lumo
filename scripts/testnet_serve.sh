#!/usr/bin/env bash
# scripts/testnet_serve.sh — boots the one-page testnet test tool against the
# LIVE Stellar testnet deployment (a valueless public test network; the
# cash-out anchor stays structurally mocked). Rebuilds a local SQLite DB bound
# to the deployed contracts and refers to keystore identities by NAME only —
# no secret key is read, printed, or exported.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="$ROOT/.venv/bin/python"
OUT="$ROOT/.amanah_local"
DB="$OUT/testnet.db"
PORT="${AMANAH_TESTNET_PORT:-8790}"

ESCROW_ID="${AMANAH_ESCROW_ID:-CARKYFTVFVUX2Y3OZJUPYBBZKTVVIHC3APSFAQOVL6DGKWU6D6ZGJJMK}"
USDC_SAC="${AMANAH_USDC_SAC:-CDWS5VFOIDNU7X3O4CXNF2I5TMGT5RKLB4GDHU24VOO7FRGGI3XYTQC7}"

for key in amanah-deployer amanah-sme amanah-supplier; do
    stellar keys address "$key" >/dev/null 2>&1 \
        || { echo "missing keystore identity: $key (stellar keys generate $key --network testnet --fund)" >&2; exit 1; }
done
SME_ADDR=$(stellar keys address amanah-sme)
SUPPLIER_ADDR=$(stellar keys address amanah-supplier)
DEPLOYER_ADDR=$(stellar keys address amanah-deployer)

mkdir -p "$OUT"
rm -f "$DB" "$DB-wal" "$DB-shm"
AMANAH_DB="$DB" "$PY" -m amanah.cli init >/dev/null

"$PY" - "$DB" "$SME_ADDR" "$SUPPLIER_ADDR" "$USDC_SAC" <<'EOF'
import sys
from amanah.db.connection import connect

db, sme, supplier, token = sys.argv[1:5]
conn = connect(db)
with conn:
    conn.execute("UPDATE policy_rules SET value = ? WHERE key = 'sme_address'", (sme,))
    conn.execute("UPDATE policy_rules SET value = ? WHERE key = 'token_address'", (token,))
    conn.execute(
        "UPDATE policy_rules SET value = '1000000000000' WHERE key = 'cap_daily'"
    )
    conn.execute(
        "UPDATE suppliers SET address = ? WHERE name = 'CV Batik Nusantara'", (supplier,)
    )
EOF

export AMANAH_DB="$DB"
export AMANAH_ESCROW_ID="$ESCROW_ID"
export AMANAH_NETWORK="testnet"
export AMANAH_CHAIN_ADAPTER="soroban"
export AMANAH_SME_SOURCE="amanah-sme"
export AMANAH_ORACLE_SOURCE="amanah-deployer"
export AMANAH_ORACLE_ADDRESS="$DEPLOYER_ADDR"

echo "amanah testnet tool -> http://127.0.0.1:$PORT/testnet"
echo "network testnet · escrow $ESCROW_ID"
echo "signing: sme=amanah-sme oracle=amanah-deployer (keystore identities, testnet-only)"
exec "$PY" -m amanah.ui.server --db "$DB" --port "$PORT"
