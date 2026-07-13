#!/usr/bin/env bash
# scripts/ui_smoke.sh — boots the demo-hero UI against a seeded mock demo DB,
# asserts the endpoints answer, the hero markers are present, and the page is
# fully self-contained (no external http(s) assets). Exit 0 only if all pass.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="$ROOT/.venv/bin/python"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
TMP="$(mktemp -d)"
DB="$TMP/demo.db"
UI_PID=""
FAIL=0

cleanup() {
    [ -n "$UI_PID" ] && kill "$UI_PID" >/dev/null 2>&1 || true
    rm -rf "$TMP"
}
trap cleanup EXIT

check() {
    local label="$1" ok="$2"
    if [ "$ok" = 0 ]; then
        echo "ok   $label"
    else
        echo "FAIL $label"
        FAIL=1
    fi
}

echo "-- seed demo db --"
"$PY" "$ROOT/scripts/seed_demo_db.py" --db "$DB"

PORT=$("$PY" -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()")
"$PY" -m amanah.ui.server --db "$DB" --port "$PORT" >/dev/null 2>&1 &
UI_PID=$!

for _ in $(seq 1 50); do
    curl -sf "http://127.0.0.1:$PORT/api/metrics" >/dev/null 2>&1 && break
    sleep 0.1
done

echo "-- endpoints --"
for path in / /api/state /api/metrics; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT$path")
    [ "$CODE" = 200 ]; check "GET $path -> $CODE" $?
done

HTML=$(curl -s "http://127.0.0.1:$PORT/")

echo "-- hero markers --"
for marker in injection-banner spine-timeline monitor-panel trust-dial; do
    grep -q "id=\"$marker\"" <<<"$HTML"; check "marker #$marker" $?
done

echo "-- self-contained (no external http(s) assets) --"
if grep -qE 'https?://' <<<"$HTML"; then
    grep -nE 'https?://' <<<"$HTML" | head -5
    check "no http(s) references in served HTML" 1
else
    check "no http(s) references in served HTML" 0
fi

echo "-- seeded story present in metrics --"
"$PY" - "http://127.0.0.1:$PORT/api/metrics" <<'EOF'
import json, sys, urllib.request
snap = json.load(urllib.request.urlopen(sys.argv[1]))
c = snap["counters"]
missing = [k for k in ("proposed", "injection_blocked", "released", "reverted") if c[k] < 1]
if missing:
    print(f"missing story beats in counters: {missing} ({c})")
    sys.exit(1)
print(f"counters {c}")
EOF
check "counters cover proposed/blocked/released/reverted" $?

kill "$UI_PID" >/dev/null 2>&1 || true
UI_PID=""

[ "$FAIL" = 0 ] && echo "UI SMOKE PASS" || echo "UI SMOKE FAIL"
exit "$FAIL"
