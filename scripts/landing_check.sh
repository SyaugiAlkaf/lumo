#!/usr/bin/env bash
# scripts/landing_check.sh — asserts the public landing page exists, is fully
# self-contained (no external http(s) assets or links), carries every required
# section, and is responsive. Exit 0 only if all checks pass.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PAGE="$ROOT/site/index.html"
FAIL=0

check() {
    local label="$1" ok="$2"
    if [ "$ok" = 0 ]; then
        echo "ok   $label"
    else
        echo "FAIL $label"
        FAIL=1
    fi
}

if [ ! -f "$PAGE" ]; then
    echo "FAIL site/index.html does not exist"
    exit 1
fi
check "site/index.html exists" 0

EXTERNAL="$(grep -nE '(src|href)[[:space:]]*=[[:space:]]*["'\'']https?://|url\([[:space:]]*["'\'']?https?://|fetch\([[:space:]]*["'\'']?https?://|@import' "$PAGE" || true)"
if [ -n "$EXTERNAL" ]; then
    echo "$EXTERNAL"
    check "self-contained: no external http(s) src/href/url()/fetch/@import" 1
else
    check "self-contained: no external http(s) src/href/url()/fetch/@import" 0
fi

grep -q 'name="viewport"' "$PAGE"; check "viewport meta present (responsive)" $?

for marker in 'id="hero"' 'id="problem"' 'id="how"' 'id="demo"' 'id="platform"' 'id="proof"' '<footer'; do
    grep -qF "$marker" "$PAGE"; check "section marker $marker" $?
done

grep -q 'prefers-color-scheme' "$PAGE"; check "light + dark theme aware" $?
grep -qF 'The agent can be tricked' "$PAGE"; check "headline present" $?

if [ "$FAIL" = 0 ]; then
    echo "PASS landing_check"
    exit 0
else
    echo "FAIL landing_check"
    exit 1
fi
