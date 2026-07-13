#!/usr/bin/env bash
# T10 — e2e spine on the local Docker quickstart network.
#   happy path:   propose → escrow (chain-confirmed) → attest Shipped → release
#                 ⇒ SQLite 'released' + supplier SAC balance +amount
#                 ⇒ HARDENING A: anchor_payout row MOCK-<ulid> + matching amount
#   failure path: propose → escrow → deadline lapses in real time → refund
#                 ⇒ SME balance restored + 'reverted' audit row
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
source "$HERE/lib.sh"

echo "== Amanah acceptance :: T10 e2e (local quickstart) =="
preflight_e2e || { echo "T10: BLOCKED (prefetch)"; exit 3; }

PY="$ROOT/.venv/bin/python"
LOCAL="$ROOT/.amanah_local"

"$ROOT/scripts/local_network.sh" up
"$ROOT/scripts/deploy_local.sh"
"$ROOT/scripts/demo_seed.sh"
source "$LOCAL/env.sh"
export AMANAH_PROVIDER=mock AMANAH_MOCK_MODE=honest

fail() { echo "T10: FAIL — $*" >&2; exit 1; }

bal() {
    stellar contract invoke --id "$AMANAH_USDC_SAC" \
        --source-account amanah-admin --network "$AMANAH_NETWORK" --send no \
        -- balance --id "$1" 2>/dev/null | tr -d '"'
}

sql() { "$PY" -c "
from amanah.db.connection import connect
row = connect('$AMANAH_DB').execute(\"$1\").fetchone()
print(row[0] if row else '')
"; }

propose() {
    local out rc
    set +e
    out=$("$PY" -m amanah.cli propose "$1")
    rc=$?
    set -e
    [ $rc -eq 0 ] || fail "propose $1 exited $rc: $out"
    echo "$out" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['intent_id'])"
}

echo
echo "---- happy path ----"
export AMANAH_DEADLINE_SECS=600
INTENT1=$(propose "$LOCAL/invoice_happy.txt")
echo "proposed intent $INTENT1"
AMOUNT1=$(sql "SELECT amount FROM intents WHERE id = '$INTENT1'")
SUP_BEFORE=$(bal "$AMANAH_SUPPLIER_ADDRESS")

"$PY" -m amanah.cli execute "$INTENT1"
[ "$(sql "SELECT status FROM intents WHERE id = '$INTENT1'")" = "escrowed" ] \
    || fail "intent not escrowed after chain-confirmed create_intent"

"$PY" -m amanah.cli attest "$INTENT1" --kind Shipped
"$PY" -m amanah.cli release "$INTENT1"

STATUS1=$(sql "SELECT status FROM intents WHERE id = '$INTENT1'")
[ "$STATUS1" = "released" ] || fail "expected SQLite released, got '$STATUS1'"

SUP_AFTER=$(bal "$AMANAH_SUPPLIER_ADDRESS")
[ $((SUP_AFTER - SUP_BEFORE)) -eq "$AMOUNT1" ] \
    || fail "supplier balance moved $((SUP_AFTER - SUP_BEFORE)), expected +$AMOUNT1"
echo "OK: released + supplier balance +$AMOUNT1"

PAYOUT_REF=$(sql "SELECT ref FROM anchor_payouts WHERE intent_id = '$INTENT1'")
PAYOUT_AMOUNT=$(sql "SELECT amount FROM anchor_payouts WHERE intent_id = '$INTENT1'")
echo "$PAYOUT_REF" | grep -qE '^MOCK-[0-9A-HJKMNP-TV-Z]{26}$' \
    || fail "anchor_payout ref '$PAYOUT_REF' is not MOCK-<ulid>"
[ "$PAYOUT_AMOUNT" = "$AMOUNT1" ] \
    || fail "anchor_payout amount $PAYOUT_AMOUNT != intent amount $AMOUNT1"
echo "OK: anchor_payout $PAYOUT_REF amount $PAYOUT_AMOUNT (HARDENING A)"

echo
echo "---- failure path (deadline lapse, real time) ----"
export AMANAH_DEADLINE_SECS=8
INTENT2=$(propose "$LOCAL/invoice_lapse.txt")
echo "proposed intent $INTENT2"
AMOUNT2=$(sql "SELECT amount FROM intents WHERE id = '$INTENT2'")
DEADLINE2=$(sql "SELECT deadline FROM intents WHERE id = '$INTENT2'")
SME_BEFORE=$(bal "$AMANAH_SME_ADDRESS")

"$PY" -m amanah.cli execute "$INTENT2"
SME_MID=$(bal "$AMANAH_SME_ADDRESS")
[ $((SME_BEFORE - SME_MID)) -eq "$AMOUNT2" ] \
    || fail "escrow did not debit SME by $AMOUNT2"

NOW=$(date +%s)
WAIT=$((DEADLINE2 - NOW + 3))
[ $WAIT -gt 0 ] && { echo "waiting ${WAIT}s for deadline to lapse..."; sleep "$WAIT"; }

REVERTED=0
for _ in 1 2 3; do
    if "$PY" -m amanah.cli revert "$INTENT2"; then REVERTED=1; break; fi
    sleep 3
done
[ $REVERTED -eq 1 ] || fail "refund never succeeded after deadline"

STATUS2=$(sql "SELECT status FROM intents WHERE id = '$INTENT2'")
[ "$STATUS2" = "reverted" ] || fail "expected SQLite reverted, got '$STATUS2'"

AUDIT=$(sql "SELECT count(*) FROM decisions WHERE intent_id = '$INTENT2' AND decision = 'reverted'")
[ "$AUDIT" = "1" ] || fail "expected 1 reverted audit row, got '$AUDIT'"

SME_AFTER=$(bal "$AMANAH_SME_ADDRESS")
[ "$SME_AFTER" = "$SME_BEFORE" ] \
    || fail "SME balance not restored ($SME_BEFORE → $SME_AFTER)"
echo "OK: refund restored SME balance + reverted audit row"

echo
echo "== T-matrix =="
printf '  %-4s %-5s %s\n' T10 GREEN "e2e: happy (released, supplier +$AMOUNT1, MOCK payout) + failure (reverted, SME restored)"
echo
echo "T10: PASS"
