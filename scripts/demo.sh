#!/usr/bin/env bash
# scripts/demo.sh — timed walkthrough for the Amanah demo.
#
# Persona: Bu Sari, owner of Sari Craft Export, a batik exporter in
# Yogyakarta. Her on-device treasury agent reads supplier invoices; a
# deterministic policy layer decides; two Soroban contracts enforce.
#
# Everything below runs on the LOCAL Docker quickstart network with a
# MOCK cash-out anchor. No real funds move and nothing here touches
# testnet or mainnet — see scripts/deploy_testnet.sh for that checklist.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
source "$ROOT/acceptance/lib.sh"

PACE="${AMANAH_DEMO_PACE:-2}"
PY="$ROOT/.venv/bin/python"
LOCAL="$ROOT/.amanah_local"
UI_PORT="${AMANAH_UI_PORT:-8787}"
UI_PID=""

cleanup() {
    [ -n "$UI_PID" ] && kill "$UI_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

pause() { sleep "$PACE"; }

step() {
    echo
    echo "======================================================================"
    echo "  $*"
    echo "======================================================================"
    pause
}

intent_id_of() { "$PY" -c "import json,sys; print(json.load(sys.stdin)['intent_id'])"; }

sql() {
    "$PY" -c "
from amanah.db.connection import connect
row = connect('$AMANAH_DB').execute(\"$1\").fetchone()
print(row[0] if row else '')
"
}

echo "AMANAH — demo walkthrough"
echo "Persona: Bu Sari, owner of Sari Craft Export (batik exporter, Yogyakarta, Indonesia)"
echo "Network: LOCAL Docker quickstart. Cash-out: MOCK anchor — no real money moves."
pause

step "1/6 — seed: deploy escrow + policy-account, register the oracle, bind suppliers"
preflight_e2e || { echo "demo FAIL: prefetch missing (see above)"; exit 3; }
"$ROOT/scripts/local_network.sh" up
"$ROOT/scripts/deploy_local.sh"
"$ROOT/scripts/demo_seed.sh"
# shellcheck disable=SC1091
source "$LOCAL/env.sh"
export AMANAH_DB AMANAH_PROVIDER=mock AMANAH_MOCK_MODE=honest

"$PY" -m amanah.ui.server --db "$AMANAH_DB" --port "$UI_PORT" >/dev/null 2>&1 &
UI_PID=$!
echo "UI running at http://127.0.0.1:$UI_PORT — open it now to follow along (MOCK labels are called out there too)"

step "2/6 — a supplier email arrives asking to redirect payment to a new address"
INJECT="$ROOT/tests/fixtures/invoices/inject_address_swap.txt"
cat "$INJECT"
set +e
OUT=$("$PY" -m amanah.cli propose "$INJECT")
RC=$?
set -e
echo "$OUT"
[ "$RC" -eq 2 ] || { echo "demo FAIL: expected refusal exit 2, got $RC"; exit 1; }
echo "REFUSED before any transaction was proposed — the address-swap attempt never reached the chain. No funds were ever at risk."

step "3/6 — a legitimate invoice, in policy: propose, then escrow the funds on-chain"
INTENT1=$("$PY" -m amanah.cli propose "$LOCAL/invoice_happy.txt" | intent_id_of)
echo "proposed intent $INTENT1"
AMOUNT1=$(sql "SELECT amount FROM intents WHERE id = '$INTENT1'")
"$PY" -m amanah.cli execute "$INTENT1"
echo "escrowed on-chain: $((AMOUNT1 / 10000000)) USDC locked, structurally bound to this supplier only"

step "4/6 — the oracle attests delivery; escrow releases to the bound supplier"
"$PY" -m amanah.cli attest "$INTENT1" --kind Shipped
"$PY" -m amanah.cli release "$INTENT1"
echo "released — the funds reached the bound supplier and nowhere else"

step "5/6 — MOCK cash-out receipt (structurally zero real anchor network)"
PAYOUT_REF=$(sql "SELECT ref FROM anchor_payouts WHERE intent_id = '$INTENT1'")
PAYOUT_AMOUNT=$(sql "SELECT amount FROM anchor_payouts WHERE intent_id = '$INTENT1'")
echo "MOCK receipt $PAYOUT_REF — $((PAYOUT_AMOUNT / 10000000)) USDC (not a real payout, no anchor network was contacted)"

step "6/6 — failure path: a second order lapses past its deadline and refunds Bu Sari"
export AMANAH_DEADLINE_SECS=8
INTENT2=$("$PY" -m amanah.cli propose "$LOCAL/invoice_lapse.txt" | intent_id_of)
echo "proposed intent $INTENT2 (deadline in 8s — this is a real wait, no time-travel)"
"$PY" -m amanah.cli execute "$INTENT2"
DEADLINE2=$(sql "SELECT deadline FROM intents WHERE id = '$INTENT2'")
NOW=$(date +%s)
WAIT=$((DEADLINE2 - NOW + 3))
[ "$WAIT" -gt 0 ] && { echo "waiting ${WAIT}s for the deadline to lapse..."; sleep "$WAIT"; }

REVERTED=0
for _ in 1 2 3; do
    if "$PY" -m amanah.cli revert "$INTENT2"; then REVERTED=1; break; fi
    sleep 3
done
[ "$REVERTED" -eq 1 ] || { echo "demo FAIL: refund never landed"; exit 1; }
echo "reverted — Bu Sari's funds came straight back; the supplier never touched them"

echo
echo "======================================================================"
echo "  demo complete. UI still running at http://127.0.0.1:$UI_PORT"
echo "  Ctrl+C to stop, then: scripts/local_network.sh down"
echo "======================================================================"
wait "$UI_PID"
