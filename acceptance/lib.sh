#!/usr/bin/env bash
# Shared helpers for the Amanah acceptance oracle.

ESCROW_EXPECTED_PASS=12

preflight() {
    local missing=0
    command -v cargo >/dev/null 2>&1 || { echo "prefetch missing: cargo (rust toolchain)"; missing=1; }
    command -v stellar >/dev/null 2>&1 || { echo "prefetch missing: stellar CLI"; missing=1; }
    rustup target list --installed 2>/dev/null | grep -q '^wasm32v1-none$' \
        || { echo "prefetch missing: wasm32v1-none rust target"; missing=1; }
    return $missing
}

# Guard against a false-green: a filtered or empty cargo run must never pass.
# A missing "N passed" line (compile error, or a filter that matched nothing)
# fails hard instead of silently reporting success.
# $1 = minimum expected passed count, $2 = path to captured cargo output.
assert_cargo_passed() {
    local expected="$1" log="$2" passed
    passed=$(grep -oE '[0-9]+ passed' "$log" | grep -oE '[0-9]+' | head -1)
    if [ -z "$passed" ]; then
        echo "FAIL: no 'N passed' line in cargo output — compile error or zero-match filter"
        return 1
    fi
    if grep -qE '[1-9][0-9]* failed' "$log"; then
        echo "FAIL: cargo reported failing tests"
        return 1
    fi
    if [ "$passed" -lt "$expected" ]; then
        echo "FAIL: expected >= $expected tests passed, got $passed"
        return 1
    fi
    echo "OK: $passed tests passed (>= $expected)"
    return 0
}
