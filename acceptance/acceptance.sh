#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# shellcheck source=lib.sh
source "$HERE/lib.sh"

GATE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --gate) GATE="${2:-}"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

marker() { printf '  %-4s %-5s %s\n' "$1" "$2" "$3"; }

gate_p0() {
    echo "== Amanah acceptance :: gate P0 (escrow + red harness) =="
    preflight || { echo "GATE P0: BLOCKED (prefetch)"; exit 3; }

    local test_log build_log test_rc build_rc
    test_log="$(mktemp)"
    build_log="$(mktemp)"
    trap 'rm -f "$test_log" "$build_log"' RETURN

    echo "-- cargo test -p amanah-escrow --"
    set +e
    ( cd "$ROOT/contracts" && cargo test -p amanah-escrow --color never ) >"$test_log" 2>&1
    test_rc=$?
    set -e
    cat "$test_log"
    assert_cargo_passed "$ESCROW_EXPECTED_PASS" "$test_log" || { echo "GATE P0: FAIL"; exit 1; }
    [ "$test_rc" -eq 0 ] || { echo "GATE P0: FAIL (cargo exit $test_rc)"; exit 1; }

    echo "-- stellar contract build --"
    set +e
    ( cd "$ROOT/contracts" && stellar contract build ) >"$build_log" 2>&1
    build_rc=$?
    set -e
    cat "$build_log"
    [ "$build_rc" -eq 0 ] || { echo "GATE P0: FAIL (stellar build exit $build_rc)"; exit 1; }

    echo
    echo "== T-matrix =="
    marker T1 GREEN "release pays bound supplier after Shipped attestation"
    marker T2 GREEN "release without attestation reverts, zero token movement"
    marker T3 GREEN "guard chain: IntentFailed / NotYetExpired / AlreadyFinalized / binding"
    marker T5 GREEN "attest from unregistered oracle rejected (NotOracle)"
    marker T4 RED   "policy-signer __check_auth        -> P1 (contracts/policy-account)"
    marker T6 RED   "policy engine cap + allowlist      -> P2 (python)"
    marker T7 RED   "pipeline propose/refuse exit codes -> P2 (python)"
    marker T8 RED   "injection scanner + COMPROMISED    -> P2 (python)"
    marker T9 RED   "audit chokepoint record_decision   -> P2 (python)"
    marker T10 RED  "e2e quickstart happy+failure+anchor-> P3 (shell)"
    echo
    echo "GATE P0: PASS (T1-T3 green, T5 green; T4 and T6-T10 red as expected)"
}

gate_p1() {
    echo "== Amanah acceptance :: gate P1 (policy-signer + oracle auth) =="
    preflight || { echo "GATE P1: BLOCKED (prefetch)"; exit 3; }

    local test_log build_log test_rc build_rc
    test_log="$(mktemp)"
    build_log="$(mktemp)"
    trap 'rm -f "$test_log" "$build_log"' RETURN

    echo "-- cargo test --workspace --"
    set +e
    ( cd "$ROOT/contracts" && cargo test --workspace --color never ) >"$test_log" 2>&1
    test_rc=$?
    set -e
    cat "$test_log"
    assert_cargo_workspace_passed "$WORKSPACE_EXPECTED_PASS" "$test_log" || { echo "GATE P1: FAIL"; exit 1; }
    [ "$test_rc" -eq 0 ] || { echo "GATE P1: FAIL (cargo exit $test_rc)"; exit 1; }

    echo "-- stellar contract build --"
    set +e
    ( cd "$ROOT/contracts" && stellar contract build ) >"$build_log" 2>&1
    build_rc=$?
    set -e
    cat "$build_log"
    [ "$build_rc" -eq 0 ] || { echo "GATE P1: FAIL (stellar build exit $build_rc)"; exit 1; }

    echo
    echo "== T-matrix =="
    marker T4 GREEN "policy __check_auth: over-cap / unapproved-supplier / in-policy / unknown-fn / bad-sig"
    marker T5 GREEN "oracle auth: unregistered + removed rejected, non-admin cannot add"
    echo
    echo "GATE P1: PASS (T4 + T5 green)"
}

gate_p2() {
    echo "== Amanah acceptance :: gate P2 (on-device agent, MockProvider only) =="
    local py="$ROOT/.venv/bin/python"
    [ -x "$py" ] || py="$(command -v python3 || true)"
    [ -n "$py" ] && "$py" -c "import pytest, pydantic, httpx" >/dev/null 2>&1 \
        || { echo "prefetch missing: python deps (pytest/pydantic/httpx) — create .venv"; echo "GATE P2: BLOCKED (prefetch)"; exit 3; }

    local test_log test_rc
    test_log="$(mktemp)"
    trap 'rm -f "$test_log"' RETURN

    echo "-- pytest tests/ -k 'not live' --"
    set +e
    ( cd "$ROOT" && "$py" -m pytest tests/ -k "not live" -q ) >"$test_log" 2>&1
    test_rc=$?
    set -e
    cat "$test_log"
    assert_pytest_passed "$PYTEST_EXPECTED_PASS" "$test_log" || { echo "GATE P2: FAIL"; exit 1; }
    [ "$test_rc" -eq 0 ] || { echo "GATE P2: FAIL (pytest exit $test_rc)"; exit 1; }

    echo
    echo "== T-matrix =="
    marker T6 GREEN "in-policy invoice -> PROPOSE, tx-plan matches escrow binding"
    marker T7 GREEN "over-cap / unknown-supplier / duplicate -> REFUSE, no tx"
    marker T8 GREEN "5 inject fixtures + COMPROMISED mock refused; clean control passes"
    marker T9 GREEN "record_decision chokepoint: one audit row per decision state"
    marker T10 RED  "e2e quickstart happy+failure+anchor -> P3 (shell)"
    echo
    echo "GATE P2: PASS (T6-T9 green; T10 red as expected)"
    echo "NOTE: live-model check is human-triggered: make live-check (never a loop gate)"
}

case "$GATE" in
    P0) gate_p0 ;;
    P1) gate_p1 ;;
    P2) gate_p2 ;;
    "") echo "usage: acceptance.sh --gate P0|P1|P2" >&2; exit 2 ;;
    *)  echo "gate '$GATE' not implemented" >&2; exit 2 ;;
esac
