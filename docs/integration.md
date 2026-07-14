# Integrating Lumo

Lumo is an on-device treasury agent: an untrusted LLM reads invoices, a
deterministic guard chain decides, and two Soroban contracts enforce. This page
is the adopter's map — each section below is one integration surface, and every
snippet has a runnable twin in `examples/`.

Common setup for all surfaces:

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

Configuration is one flat table read from `lumo.toml` (path in
`LUMO_CONFIG`), overridable per key by `LUMO_<KEY>` environment variables.
The defaults are safe: mock LLM provider, mock anchor, monitoring on, no chain
writes without an explicit escrow id.

## Integrate in 5 lines

The SDK embeds the whole agent — SQLite, migrations, guard chain, event bus —
in-process. No server, no network.

```python
from lumo import LumoClient

client = LumoClient()
decision = client.propose(open("invoice.txt").read())
print(decision.decision, decision.codes)
```

- `propose(text_or_path)` runs the full pipeline and returns a `Decision`
  (`proposed` with a `create_intent` tx plan, `refused` with typed codes, or
  `held` awaiting a human cosign).
- `status(intent_id)` returns the intent row; `attest(intent_id, kind)` records
  an oracle attestation (`Shipped` / `Failed`).
- Pass a `Config` to control everything: `LumoClient(Config.profile("strict",
  db_path="treasury.db"))`.

Runnable: `examples/sdk_propose.py`.

## Call from any language

`python -m lumo.api` serves a small REST API (default `127.0.0.1:8788`,
`api_host` / `api_port` in config). The OpenAPI 3 document is served by the API
itself at `/v1/openapi.json`.

| Method | Path | Effect |
|---|---|---|
| POST | `/v1/intents` | body `{"invoice": "..."}` → full decision JSON |
| GET | `/v1/intents/{intent_id}` | intent row (status, amount, request_hash) |
| POST | `/v1/intents/{intent_id}/attest` | body `{"kind": "Shipped"\|"Failed"}` |
| GET | `/v1/metrics` | counters + gauges snapshot |
| POST | `/v1/webhooks` | body `{"url": "..."}` registers an event webhook |

```bash
curl -X POST http://127.0.0.1:8788/v1/intents \
  -H 'Content-Type: application/json' \
  -d '{"invoice": "INVOICE INV-2026-0042\nFrom: CV Batik Nusantara\nAmount due: 1,250.00 USDC\n"}'
```

A refused invoice is still HTTP 200 — refusal is a first-class decision, not an
error; malformed requests are 400 and unknown intents 404.

Runnable: `examples/rest_curl.sh`.

## Use from any AI agent

`python -m lumo.mcp` is a Model Context Protocol server over stdio. Register
it in any MCP-capable agent runtime:

```json
{
  "mcpServers": {
    "lumo": {
      "command": "python",
      "args": ["-m", "lumo.mcp"],
      "env": { "LUMO_DB": "treasury.db" }
    }
  }
}
```

Tools exposed:

| Tool | Arguments | Returns |
|---|---|---|
| `lumo.propose_payment` | `invoice_text` | decision JSON |
| `lumo.get_status` | `intent_id` | intent row |
| `lumo.attest` | `intent_id`, `kind` (`Shipped`/`Failed`) | confirmation |

The trust boundary holds regardless of who calls: the agent can *ask* for a
payment, but the guard chain, policy-signer account, and escrow decide — an
out-of-policy ask is a typed refusal, never a transaction.

Runnable: `examples/mcp_tool_call.py`.

## Target any chain

Settlement sits behind three protocol seams, each selected by one config key
and each with a zero-network mock for tests and dry runs:

| Seam | Protocol | Config key | Implementations |
|---|---|---|---|
| Chain | `ChainAdapter` | `chain_adapter` | `soroban` (stellar CLI subprocess, the demo spine) · `mock` (in-memory) · `evm` (roadmap: x402) |
| Anchor off-ramp | `AnchorAdapter` | `anchor_adapter` | `mock` (SEP-24-shaped, `MOCK-<ulid>` receipts, zero network) · `gcash`, `pdax` (roadmap) |
| Oracle | `AttestationSource` | `oracle_adapter` | `""` (single local oracle) · `local` (comma-separated `oracle_signers` set) · `shipment_api` (roadmap) |

A new chain is one class implementing `ChainAdapter`
(`lumo/chain/adapter.py`): `create_intent`, `attest`, `release`, `refund`,
`get_status`. The pipeline, guards, and audit trail are chain-agnostic — money
state is only ever written after a chain read confirms it (`chain/mapper.py`).

## Monitor it

One event bus (`monitoring = true`, default on) carries every decision, guard
trip, injection block, and money-state change.

- **In-process:** `client.on_event(callback)` receives every event;
  `client.metrics()` returns the counters/gauges snapshot.
- **Metrics:** `GET /v1/metrics` — counters (`proposed`, `refused`, `held`,
  `released`, `reverted`, guard trips) and gauges (`intents_open`, escrowed
  value).
- **Webhooks:** `POST /v1/webhooks {"url": ...}` or the `webhook_urls` config
  key — each event is POSTed as JSON to every registered URL.
- **Dashboard:** the read-only UI (`http://127.0.0.1:8787`, started by the demo
  scripts) polls `/api/state` and renders the intent timeline plus a live
  monitoring panel.

Turning `monitoring` off silences the bus entirely — no events, no webhook
traffic, no event rows.

## Pick a trust tier

`Config.profile(name, **overrides)` returns a preset guard chain. Unlisted
fields keep their safe defaults, and any keyword override wins:

```python
from lumo import LumoClient
from lumo.config import Config

client = LumoClient(Config.profile("strict", db_path="treasury.db"))
```

| Guard | `fast` | `balanced` | `strict` |
|---|---|---|---|
| Injection scanner | on | on | on |
| Policy engine (caps, registry, duplicates) | on | on | on |
| Policy-signer mirror | — | on | on |
| Release needs `Shipped` attestation | — | on | on |
| k-of-n distinct oracles | — | — | 3 |
| Human cosign hold | — | — | above 100 USDC |
| Proof-of-compute receipt | — | — | on |

- **`fast`** — propose/refuse only: injection scan + deterministic policy.
  Lowest friction; still cannot pay an unknown supplier or exceed a cap.
- **`balanced`** — the recommended tier: adds the policy-signer mirror and
  requires a `Shipped` attestation before any release.
- **`strict`** — everything on: three distinct oracles must attest, payments
  above the cosign threshold hold for a human token, and every proposal must
  carry a valid compute receipt.

Whatever the tier, the on-chain contracts are unchanged: escrowed funds can
structurally only reach the bound supplier or return to the SME.
