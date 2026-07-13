#!/usr/bin/env bash
# scripts/testnet_smoke.sh — LIVE smoke against a RUNNING testnet tool
# (start it first: scripts/testnet_serve.sh). POSTs a clean invoice and
# asserts a real create_intent tx hash comes back from the Stellar testnet.
# External + live by design — never part of an automated gate.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="$ROOT/.venv/bin/python"
PORT="${AMANAH_TESTNET_PORT:-8790}"
BASE="http://127.0.0.1:$PORT"

SUPPLIER_ADDR=$(stellar keys address amanah-supplier)
REF="INV-SMOKE-$(date +%s)"

INVOICE="INVOICE $REF
From: CV Batik Nusantara
Payment address: $SUPPLIER_ADDR
Amount due: 120.00 USDC
Due: 2026-08-01
Memo: live testnet smoke, order PO-SMOKE
"

echo "-- POST $BASE/testnet/run ($REF, 120.00 USDC) --"
BODY=$(INVOICE="$INVOICE" "$PY" -c 'import json,os; print(json.dumps({"invoice_text": os.environ["INVOICE"]}))')
RESP=$(curl -sf --max-time 300 -X POST "$BASE/testnet/run" \
    -H 'Content-Type: application/json' --data "$BODY")

RESP="$RESP" "$PY" - <<'EOF'
import json, os, re, sys

data = json.loads(os.environ["RESP"])
if data.get("decision") != "proposed":
    print(f"FAIL: expected proposed, got {data}")
    sys.exit(1)
txs = {tx["step"]: tx for tx in data.get("txs", [])}
create = txs.get("create_intent")
if not create or not re.fullmatch(r"[0-9a-f]{64}", create["hash"] or ""):
    print(f"FAIL: no real create_intent tx hash in {data.get('txs')}")
    sys.exit(1)
for step in ("create_intent", "attest", "release"):
    tx = txs.get(step)
    print(f"{step:14s} {tx['hash'] if tx else '-'}")
    if tx:
        print(f"{'':14s} {tx['url']}")
print("TESTNET SMOKE PASS")
EOF
