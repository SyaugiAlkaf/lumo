#!/usr/bin/env bash
# Local Stellar network: pinned quickstart image in Docker, RPC on :8000.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
source "$ROOT/acceptance/lib.sh"

wait_healthy() {
    local deadline=$((SECONDS + 180))
    while [ $SECONDS -lt $deadline ]; do
        local status
        status=$(curl -s -X POST http://localhost:8000/rpc \
            -H 'Content-Type: application/json' \
            -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}' \
            | grep -o '"status":"healthy"' || true)
        if [ -n "$status" ]; then
            local fb
            fb=$(curl -s http://localhost:8000/friendbot || true)
            if [ -n "$fb" ]; then
                echo "local network healthy (rpc + friendbot :8000)"
                return 0
            fi
        fi
        sleep 2
    done
    echo "FAIL: local network not healthy after 180s" >&2
    docker logs --tail 30 "$QUICKSTART_CONTAINER" >&2 || true
    return 1
}

case "${1:-}" in
    up)
        cli_major=$(stellar --version | head -1 | sed -E 's/^stellar ([0-9]+)\..*/\1/')
        [ "$cli_major" = "$STELLAR_CLI_MAJOR" ] \
            || { echo "FAIL: stellar CLI major $STELLAR_CLI_MAJOR required, got $cli_major" >&2; exit 1; }
        docker image inspect "$QUICKSTART_IMAGE" >/dev/null 2>&1 \
            || { echo "prefetch missing: docker pull $QUICKSTART_IMAGE" >&2; exit 1; }
        docker rm -f "$QUICKSTART_CONTAINER" >/dev/null 2>&1 || true
        docker run -d --name "$QUICKSTART_CONTAINER" \
            -p 8000:8000 \
            "$QUICKSTART_IMAGE" --local --enable rpc \
            --protocol-version "$QUICKSTART_PROTOCOL" >/dev/null
        wait_healthy
        proto=$(curl -s -X POST http://localhost:8000/rpc \
            -H 'Content-Type: application/json' \
            -d '{"jsonrpc":"2.0","id":1,"method":"getLatestLedger"}' \
            | grep -o '"protocolVersion":[0-9]*' | grep -o '[0-9]*')
        [ "$proto" = "$QUICKSTART_PROTOCOL" ] \
            || { echo "FAIL: network protocol $proto, need $QUICKSTART_PROTOCOL (sdk 26 wasm)" >&2; exit 1; }
        echo "protocol $proto confirmed"
        ;;
    down)
        docker rm -f "$QUICKSTART_CONTAINER" >/dev/null 2>&1 || true
        echo "local network stopped"
        ;;
    *)
        echo "usage: local_network.sh up|down" >&2
        exit 2
        ;;
esac
