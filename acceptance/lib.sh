#!/usr/bin/env bash
# Shared helpers for the Lumo acceptance oracle.

ESCROW_EXPECTED_PASS=14
WORKSPACE_EXPECTED_PASS=22
PYTEST_EXPECTED_PASS=40

QUICKSTART_IMAGE="stellar/quickstart:latest"
QUICKSTART_DIGEST="sha256:8ddf3ed87a5c07eab5202b0fd95f06fb5db3f48cacd7e69fdc0e22925f181168"
STELLAR_CLI_MAJOR=27
QUICKSTART_PROTOCOL=26
QUICKSTART_CONTAINER="lumo-quickstart"

preflight() {
    local missing=0
    command -v cargo >/dev/null 2>&1 || { echo "prefetch missing: cargo (rust toolchain)"; missing=1; }
    command -v stellar >/dev/null 2>&1 || { echo "prefetch missing: stellar CLI"; missing=1; }
    rustup target list --installed 2>/dev/null | grep -q '^wasm32v1-none$' \
        || { echo "prefetch missing: wasm32v1-none rust target"; missing=1; }
    return $missing
}

# HARDENING E: every e2e dependency is checked up front so a missing dep fails
# "prefetch missing" instead of a spurious mid-run RED.
preflight_e2e() {
    local missing=0
    preflight || missing=1
    command -v docker >/dev/null 2>&1 || { echo "prefetch missing: docker"; missing=1; }
    docker info >/dev/null 2>&1 || { echo "prefetch missing: docker daemon not running"; missing=1; }
    local cli_major
    cli_major=$(stellar --version 2>/dev/null | head -1 | sed -E 's/^stellar ([0-9]+)\..*/\1/')
    if [ "$cli_major" != "$STELLAR_CLI_MAJOR" ]; then
        echo "prefetch missing: stellar CLI major $STELLAR_CLI_MAJOR (got '${cli_major:-none}')"
        missing=1
    fi
    local digest
    digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$QUICKSTART_IMAGE" 2>/dev/null | sed 's/.*@//')
    if [ -z "$digest" ]; then
        echo "prefetch missing: quickstart image — run: docker pull $QUICKSTART_IMAGE"
        missing=1
    elif [ "$digest" != "$QUICKSTART_DIGEST" ]; then
        echo "prefetch missing: quickstart image digest drift (got $digest, pinned $QUICKSTART_DIGEST)"
        missing=1
    fi
    local py="$ROOT/.venv/bin/python"
    [ -x "$py" ] && "$py" -c "import pytest, pydantic, httpx" >/dev/null 2>&1 \
        || { echo "prefetch missing: python deps (pytest/pydantic/httpx) — create .venv"; missing=1; }
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

# Pytest variant of the false-green guard: a run that collected nothing or
# silently skipped the suite must never pass.
# $1 = minimum expected passed count, $2 = path to captured pytest output.
assert_pytest_passed() {
    local expected="$1" log="$2" passed
    passed=$(grep -oE '[0-9]+ passed' "$log" | grep -oE '[0-9]+' | head -1)
    if [ -z "$passed" ]; then
        echo "FAIL: no 'N passed' line in pytest output — collection error or empty suite"
        return 1
    fi
    if grep -qE '[1-9][0-9]* (failed|error)' "$log"; then
        echo "FAIL: pytest reported failures or errors"
        return 1
    fi
    if [ "$passed" -lt "$expected" ]; then
        echo "FAIL: expected >= $expected tests passed, got $passed"
        return 1
    fi
    echo "OK: $passed tests passed (>= $expected)"
    return 0
}

# Workspace variant: sums every "N passed" line across all test binaries.
# $1 = minimum expected total, $2 = captured cargo output.
assert_cargo_workspace_passed() {
    local expected="$1" log="$2" total
    total=$(grep -oE '[0-9]+ passed' "$log" | grep -oE '[0-9]+' | paste -sd+ - | bc)
    if [ -z "$total" ]; then
        echo "FAIL: no 'N passed' line in cargo output — compile error or zero-match filter"
        return 1
    fi
    if grep -qE '[1-9][0-9]* failed' "$log"; then
        echo "FAIL: cargo reported failing tests"
        return 1
    fi
    if [ "$total" -lt "$expected" ]; then
        echo "FAIL: expected >= $expected tests passed, got $total"
        return 1
    fi
    echo "OK: $total tests passed across workspace (>= $expected)"
    return 0
}
