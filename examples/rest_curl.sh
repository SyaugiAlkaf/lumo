#!/usr/bin/env bash
set -euo pipefail
BASE="${AMANAH_API:-http://127.0.0.1:8788}"

decision=$(curl -sS -X POST "$BASE/v1/intents" \
  -H 'Content-Type: application/json' --data @- <<'EOF'
{"invoice": "INVOICE INV-2026-0042\nFrom: CV Batik Nusantara\nPayment address: GBATIKYLX7IEOR2YJMNTPMKZCIWXT2PAX635P7ZDGB3DTLQLS263VNS3\nAmount due: 1,250.00 USDC\nMemo: 40 bolts hand-stamped batik tulis\n"}
EOF
)
echo "$decision"

intent_id=$(echo "$decision" | python3 -c 'import json,sys; print(json.load(sys.stdin)["intent_id"])')
curl -sS "$BASE/v1/intents/$intent_id"
echo
curl -sS "$BASE/v1/metrics"
echo
