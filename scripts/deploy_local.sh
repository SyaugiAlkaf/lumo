#!/usr/bin/env bash
# Deploy escrow + policy-account + USDC SAC to the local quickstart network.
# Writes contract IDs as JSON to .lumo_local/deploy.json.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
OUT_DIR="$ROOT/.lumo_local"
WASM_DIR="$ROOT/contracts/target/wasm32v1-none/release"
NETWORK="local"
PY="$ROOT/.venv/bin/python"

mkdir -p "$OUT_DIR"

echo "-- build contracts --"
( cd "$ROOT/contracts" && stellar contract build ) >/dev/null

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

echo "-- identities --"
ADMIN_ADDR=$(ensure_key lumo-admin)
ISSUER_ADDR=$(ensure_key lumo-issuer)
SME_ADDR=$(ensure_key lumo-sme)
echo "admin  $ADMIN_ADDR"
echo "issuer $ISSUER_ADDR"

echo "-- deploy escrow --"
ESCROW_ID=$(stellar contract deploy \
    --wasm "$WASM_DIR/lumo_escrow.wasm" \
    --source-account lumo-admin --network "$NETWORK" \
    -- --admin "$ADMIN_ADDR")
echo "escrow $ESCROW_ID"

echo "-- deploy policy-account (owner = sme ed25519 key) --"
SME_PUBKEY_HEX=$("$PY" -c "
import base64, sys
raw = base64.b32decode('$SME_ADDR')
sys.stdout.write(raw[1:33].hex())
")
CAP_PER_TX=20000000000
POLICY_ID=$(stellar contract deploy \
    --wasm "$WASM_DIR/lumo_policy_account.wasm" \
    --source-account lumo-admin --network "$NETWORK" \
    -- --owner "$SME_PUBKEY_HEX" --cap_per_tx "$CAP_PER_TX")
echo "policy $POLICY_ID"

# Money-safety: bind the policy account to the one escrow it is allowed to fund.
# Until this is set the account authorizes NO token transfer (fail-closed), and
# once set it authorizes a transfer only when the recipient is this escrow — so a
# compromised agent cannot move funds to any other address.
stellar contract invoke \
    --id "$POLICY_ID" --source-account lumo-admin --network "$NETWORK" \
    -- set_escrow --escrow "$ESCROW_ID"
echo "policy bound to escrow $ESCROW_ID"

echo "-- wrap USDC as SAC --"
USDC_SAC=$(stellar contract asset deploy \
    --asset "USDC:$ISSUER_ADDR" \
    --source-account lumo-admin --network "$NETWORK" 2>/dev/null \
    || stellar contract id asset --asset "USDC:$ISSUER_ADDR" --network "$NETWORK")
echo "usdc   $USDC_SAC"

"$PY" - "$OUT_DIR/deploy.json" <<EOF
import json, sys
json.dump(
    {
        "network": "$NETWORK",
        "escrow_id": "$ESCROW_ID",
        "policy_account_id": "$POLICY_ID",
        "usdc_sac": "$USDC_SAC",
        "admin": "$ADMIN_ADDR",
        "issuer": "$ISSUER_ADDR",
    },
    open(sys.argv[1], "w"),
    indent=2,
)
EOF
echo "wrote $OUT_DIR/deploy.json"
