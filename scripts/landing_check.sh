#!/usr/bin/env bash
# scripts/landing_check.sh — asserts the public landing page exists, ships no
# external assets beyond the pinned Google Fonts, carries every required
# section, links the live testnet proof, and leaks no secret seed.
# Exit 0 only if all checks pass.
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

# No external asset fetched at runtime (src=/url()/fetch/@import to http). Fonts
# are pulled via <link href=…> which is asserted separately below.
EXTERNAL_ASSETS="$(grep -nE 'src[[:space:]]*=[[:space:]]*["'\'']https?://|url\([[:space:]]*["'\'']?https?://|fetch\([[:space:]]*["'\'']?https?://|@import' "$PAGE" || true)"
if [ -n "$EXTERNAL_ASSETS" ]; then
    echo "$EXTERNAL_ASSETS"
    check "self-contained: no external http(s) src/url()/fetch/@import" 1
else
    check "self-contained: no external http(s) src/url()/fetch/@import" 0
fi

# Outbound hrefs limited to the explorer, the repo, and the Google Fonts hosts.
STRAY_HREFS="$(grep -oE 'href[[:space:]]*=[[:space:]]*["'\'']https?://[^"'\'']*' "$PAGE" \
    | grep -vE 'https?://(stellar\.expert/explorer/testnet/|github\.com/|fonts\.googleapis\.com|fonts\.gstatic\.com)' || true)"
if [ -n "$STRAY_HREFS" ]; then
    echo "$STRAY_HREFS"
    check "external hrefs limited to explorer + github + google fonts" 1
else
    check "external hrefs limited to explorer + github + google fonts" 0
fi

grep -q 'name="viewport"' "$PAGE"; check "viewport meta present (responsive)" $?

for marker in 'id="hero"' 'id="trust"' 'id="how"' 'id="before-after"' 'id="testnet"' '<footer'; do
    grep -qF "$marker" "$PAGE"; check "section marker $marker" $?
done

grep -qF 'be tricked.' "$PAGE"; check "honest tagline: the agent can be tricked" $?
grep -qF 'The money cannot.' "$PAGE"; check "honest tagline: the money cannot" $?
grep -qF 'CARKYFTVFVUX2Y3OZJUPYBBZKTVVIHC3APSFAQOVL6DGKWU6D6ZGJJMK' "$PAGE"; check "escrow contract link" $?
grep -qF 'CBY6WBJTUVEOGZVP65AUIUZFKYS5LKMH7MMD2TQX2HZXP67XVW6T7MGS' "$PAGE"; check "policy-account contract link" $?
grep -qF '0b5d14a535d0fd7ae03b40eccf14205c042d606c4c2c0675ef0ce47265956f4f' "$PAGE"; check "release tx link" $?
grep -qF 'href="/testnet"' "$PAGE"; check "testnet tester link" $?
grep -qF 'github.com/SyaugiAlkaf/lumo' "$PAGE"; check "repo link" $?
grep -qE 'S[A-Z0-9]{55}' "$PAGE" && SECRET=1 || SECRET=0; check "no Stellar secret seed on page" "$SECRET"

if [ "$FAIL" = 0 ]; then
    echo "PASS landing_check"
    exit 0
else
    echo "FAIL landing_check"
    exit 1
fi
