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
OUT="$ROOT/.lumo_local"
DB="$OUT/testnet.db"
PORT="${LUMO_TESTNET_PORT:-8790}"

ESCROW_ID="${LUMO_ESCROW_ID:-CARKYFTVFVUX2Y3OZJUPYBBZKTVVIHC3APSFAQOVL6DGKWU6D6ZGJJMK}"
USDC_SAC="${LUMO_USDC_SAC:-CDWS5VFOIDNU7X3O4CXNF2I5TMGT5RKLB4GDHU24VOO7FRGGI3XYTQC7}"
# The policy-account smart account: create_intent is routed through it and
# authorized by the sme owner key's __check_auth, so the on-chain cap +
# approved-supplier + recipient binding gate every real payment.
POLICY_ID="${LUMO_SME_SMART_ACCOUNT:-CD2EIG3V4TBGHSGLZYCIZRHVFVQFUA3NL2KG7SZFF3SIEGL7MMV4PF5L}"

for key in lumo-deployer lumo-sme lumo-supplier; do
    stellar keys address "$key" >/dev/null 2>&1 \
        || { echo "missing keystore identity: $key (stellar keys generate $key --network testnet --fund)" >&2; exit 1; }
done
SME_ADDR=$(stellar keys address lumo-sme)
SUPPLIER_ADDR=$(stellar keys address lumo-supplier)
DEPLOYER_ADDR=$(stellar keys address lumo-deployer)

mkdir -p "$OUT"
rm -f "$DB" "$DB-wal" "$DB-shm"
LUMO_DB="$DB" "$PY" -m lumo.cli init >/dev/null

"$PY" - "$DB" "$SME_ADDR" "$SUPPLIER_ADDR" "$USDC_SAC" <<'EOF'
import sys
from lumo.db.connection import connect

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

export LUMO_DB="$DB"
export LUMO_ESCROW_ID="$ESCROW_ID"
export LUMO_NETWORK="testnet"
export LUMO_CHAIN_ADAPTER="soroban"
export LUMO_SME_SOURCE="lumo-sme"
export LUMO_SME_SMART_ACCOUNT="$POLICY_ID"
export LUMO_ORACLE_SOURCE="lumo-deployer"
export LUMO_ORACLE_ADDRESS="$DEPLOYER_ADDR"

echo "lumo testnet tool -> http://127.0.0.1:$PORT/testnet"
echo "network testnet · escrow $ESCROW_ID"
echo "create_intent flows through policy-account $POLICY_ID (owner-signed __check_auth)"
echo "signing: sme=lumo-sme oracle=lumo-deployer (keystore identities, testnet-only)"
exec "$PY" -m lumo.ui.server --db "$DB" --port "$PORT"
