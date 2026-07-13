#!/usr/bin/env bash
# Seed the local network + SQLite for the demo: oracle registered on the escrow,
# supplier bound in the registry, caps set, SAC USDC minted to the SME.
# Deadlines are SHORT (seconds) — the failure path lapses in real time,
# no ledger time-travel outside unit tests.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
OUT_DIR="$ROOT/.amanah_local"
NETWORK="local"
PY="$ROOT/.venv/bin/python"
DEPLOY_JSON="$OUT_DIR/deploy.json"

[ -f "$DEPLOY_JSON" ] || { echo "run deploy_local.sh first" >&2; exit 1; }

jqpy() { "$PY" -c "import json,sys; print(json.load(open('$DEPLOY_JSON'))['$1'])"; }
ESCROW_ID=$(jqpy escrow_id)
USDC_SAC=$(jqpy usdc_sac)
ISSUER_ADDR=$(jqpy issuer)

ensure_key() {
    stellar keys address "$1" >/dev/null 2>&1 \
        || stellar keys generate "$1" --network "$NETWORK" --fund >/dev/null
    local i
    for i in 1 2 3 4 5; do
        stellar keys fund "$1" --network "$NETWORK" >/dev/null 2>&1 && break
        [ "$i" = 5 ] && { echo "FAIL: could not fund $1 via friendbot" >&2; return 1; }
        sleep 2
    done
    stellar keys address "$1"
}

SME_ADDR=$(ensure_key amanah-sme)
SUPPLIER_ADDR=$(ensure_key amanah-supplier)
ORACLE_ADDR=$(ensure_key amanah-oracle)
echo "sme      $SME_ADDR"
echo "supplier $SUPPLIER_ADDR"
echo "oracle   $ORACLE_ADDR"

echo "-- USDC trustlines (sme, supplier) --"
stellar tx new change-trust --line "USDC:$ISSUER_ADDR" \
    --source-account amanah-sme --network "$NETWORK" >/dev/null 2>&1 || true
stellar tx new change-trust --line "USDC:$ISSUER_ADDR" \
    --source-account amanah-supplier --network "$NETWORK" >/dev/null 2>&1 || true

echo "-- mint 10,000 USDC to sme --"
stellar contract invoke --id "$USDC_SAC" \
    --source-account amanah-issuer --network "$NETWORK" \
    -- mint --to "$SME_ADDR" --amount 100000000000 >/dev/null

echo "-- register oracle on escrow --"
stellar contract invoke --id "$ESCROW_ID" \
    --source-account amanah-admin --network "$NETWORK" \
    -- add_oracle --oracle "$ORACLE_ADDR" >/dev/null

DB="$OUT_DIR/amanah.db"
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
        "UPDATE suppliers SET address = ? WHERE name = 'CV Batik Nusantara'", (supplier,)
    )
EOF

cat > "$OUT_DIR/invoice_happy.txt" <<EOF
INVOICE INV-2026-0042
From: CV Batik Nusantara
Payment address: $SUPPLIER_ADDR
Amount due: 1,250.00 USDC
Due: 2026-07-20
Memo: 40 bolts hand-stamped batik tulis, order PO-118
EOF

cat > "$OUT_DIR/invoice_lapse.txt" <<EOF
INVOICE INV-2026-0055
From: CV Batik Nusantara
Payment address: $SUPPLIER_ADDR
Amount due: 900.00 USDC
Due: 2026-07-22
Memo: 30 bolts natural-dye batik cap, order PO-121
EOF

cat > "$OUT_DIR/env.sh" <<EOF
export AMANAH_DB="$DB"
export AMANAH_ESCROW_ID="$ESCROW_ID"
export AMANAH_NETWORK="$NETWORK"
export AMANAH_SME_SOURCE="amanah-sme"
export AMANAH_ORACLE_SOURCE="amanah-oracle"
export AMANAH_ORACLE_ADDRESS="$ORACLE_ADDR"
export AMANAH_USDC_SAC="$USDC_SAC"
export AMANAH_SME_ADDRESS="$SME_ADDR"
export AMANAH_SUPPLIER_ADDRESS="$SUPPLIER_ADDR"
EOF
echo "wrote $OUT_DIR/env.sh"
