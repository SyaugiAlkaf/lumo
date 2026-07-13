# Amanah

On-device SME treasury agent for USDC on Soroban. An untrusted local LLM only
reads invoices; a deterministic policy layer decides; two on-chain contracts
enforce. Funds in escrow can structurally reach only the bound supplier (on a
`Shipped` attestation) or return to the SME (on `Failed`, or on deadline with no
attestation) — so compromising the agent cannot move money to an attacker.

**Demo persona:** Bu Sari, owner of Sari Craft Export, a batik exporter in
Yogyakarta, Indonesia. She pays overseas fabric suppliers in USDC and wants an
agent that can read an invoice and propose a payment — without ever being able
to send her money somewhere an attacker chose.

## Architecture

```
                              invoice.txt
                                   |
                                   v
+---------------------- Python: amanah/ (on-device) ----------------------+
|  security/injection --> llm/(llama|mock) --> policy/engine              |
|                    \--------------> pipeline --------/  PROPOSE/REFUSE  |
|  db/repo.record_decision  <-- single audit chokepoint (T9)              |
|  flow.py --> chain/soroban_client (stellar CLI subprocess)              |
|  chain/mapper.sync_status <-- chain-wins money-state read               |
|  anchor/mock_anchor.cash_out (MOCK, zero network) --> ui/server + index |
+-----------------------------------+---------------------------------------+
                                    |
                                    v
+---------------- Soroban (local quickstart / testnet) --------------------+
|  policy-account: __check_auth allowlist{transfer, create_intent}        |
|    + per-tx cap + supplier check --> OverCap / SupplierNotApproved      |
|  escrow: create_intent --> attest(oracle, first-write-wins)             |
|    --> release(-> supplier ONLY) | refund(-> sme ONLY)                  |
+---------------------------------------------------------------------------+
```

**Trust boundary:** the LLM is extraction-only and holds zero tools — it reads
invoice text and returns structured fields, nothing more. Every payment
decision is made by the deterministic Python policy layer (caps, supplier
registry, injection scanner), and every payment is enforced twice more
on-chain: the policy-signer smart account refuses an out-of-policy
transaction before it is ever submitted, and the escrow can only pay the one
supplier bound to that intent or refund the SME who funded it. A test suite
proves that even a fully compromised LLM (one that obeys attacker text in the
invoice) cannot move funds anywhere but the registered supplier or back to the
SME — see `tests/test_t8_injection.py`.

Money truth lives on-chain; agent-brain truth (suppliers, rules, intents,
audit) lives in SQLite; a `request_hash` (sha256 of the canonical intent JSON)
binds the two and is checked chain-side before any state is written locally.

## Repository layout

```
contracts/           Rust workspace (soroban-sdk 26, wasm32v1-none)
  escrow/             conditional-release escrow (T1-T3, T5)
  policy-account/     __check_auth policy-signer smart account (T4)
bindings/             frozen contract interface (escrow.json, policy_account.json)
amanah/               the Python agent (one package)
  llm/                extraction-only providers: mock + llama-server
  security/           injection scanner (NFKC + zero-width strip, patterns)
  policy/             deterministic evaluate() — caps, registry, injection
  db/                 SQLite schema, migrations, repo (single audit chokepoint)
  chain/              stellar CLI client, request_hash, chain-wins mapper
  anchor/             mock_anchor.py — SEP-24-shaped, zero network
  ui/                 read-only state viewer (poll /api/state)
tests/                pytest: policy engine, injection, audit, db, chain client
acceptance/           acceptance.sh (gate runner) + t10_e2e.sh (local e2e)
scripts/              local_network / deploy_local / demo_seed / demo / deploy_testnet
```

## Contracts

### `amanah-escrow`

Conditional-release escrow. One SME funds an `Intent` bound to one supplier; an
admin-registered oracle attests the outcome; funds settle only along the two
allowed paths.

| Entrypoint | Effect |
|---|---|
| `__constructor(admin)` | stores the admin |
| `add_oracle / remove_oracle / is_oracle` | admin-gated oracle registry |
| `create_intent(sme, supplier, token, amount, request_hash, deadline)` | pulls `amount` into escrow, status `Funded` |
| `attest(intent_id, oracle, kind)` | oracle-only, `Funded`-only, first-write-wins; `kind ∈ {Shipped, Failed}` |
| `release(intent_id)` | requires a `Shipped` attestation; pays the bound supplier only |
| `refund(intent_id)` | on `Failed`, or (no attestation and `now ≥ deadline`); pays the SME only |

A `Shipped` attestation always beats the deadline: once shipped, `refund` is
blocked and `release` stays valid.

### `amanah-policy-account`

Deny-by-default policy-signer smart account (`__check_auth`). Only two
functions are allowlisted (`transfer`, `create_intent`); every invocation is
checked against a per-transaction cap and, for `create_intent`, an approved
supplier set. Anything else — wrong function, over cap, unapproved supplier,
bad signature — is a typed revert, never a silent pass-through.

```bash
cd contracts
cargo test --workspace         # unit + revert tests, both crates
stellar contract build         # -> target/wasm32v1-none/release/*.wasm
```

## The Python agent

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m amanah.cli --db /tmp/amanah.db init
.venv/bin/python -m amanah.cli propose tests/fixtures/invoices/clean_in_policy.txt
```

`propose` exits `0` and prints a tx plan for an in-policy invoice, or exits `2`
with refusal codes (`INJECTION_SUSPECTED`, `OVER_TX_CAP`, `UNKNOWN_SUPPLIER`,
...) and proposes nothing on-chain. `AMANAH_PROVIDER=mock` (default) never
touches a real model; point `AMANAH_PROVIDER=llama` + `AMANAH_LLAMA_URL` at a
local `llama-server` for the real extraction path (`make live-check`).

## Integrate

Deeper walkthrough with every option: [`docs/integration.md`](docs/integration.md).
Runnable versions of the snippets live in `examples/`.

### Integrate in 5 lines

```python
from amanah import AmanahClient

client = AmanahClient()
decision = client.propose(open("invoice.txt").read())
print(decision.decision, decision.codes)
```

`decision.decision` is `proposed`, `refused`, or `held`; a proposal carries the
exact `create_intent` tx plan and an `intent_id` you can `status()` later.

### Call from any language

Start the REST API (`python -m amanah.api`, default `127.0.0.1:8788`) and use
plain HTTP — the full schema is served at `/v1/openapi.json`:

```bash
curl -X POST http://127.0.0.1:8788/v1/intents \
  -H 'Content-Type: application/json' \
  -d '{"invoice": "INVOICE INV-2026-0042\nFrom: CV Batik Nusantara\nAmount due: 1,250.00 USDC\n"}'
```

### Use from any AI agent

`python -m amanah.mcp` is an MCP server over stdio exposing three tools:
`amanah.propose_payment`, `amanah.get_status`, `amanah.attest`. Point any
MCP-capable agent at that command and it can propose payments — while every
cap, registry, and injection guard still decides, not the agent.

### Target any chain

Settlement is behind `ChainAdapter` / `AnchorAdapter` / `AttestationSource`
seams, selected by config:

| Seam | Config key | Live | Roadmap |
|---|---|---|---|
| Chain | `chain_adapter` | `soroban` (stellar CLI), `mock` | `evm` (x402) |
| Anchor off-ramp | `anchor_adapter` | `mock` (SEP-24-shaped, zero network) | `gcash`, `pdax` |
| Oracle | `oracle_adapter` | `""` (single local), `local` (signer set) | `shipment_api` |

### Monitor it

Every decision, guard trip, and state change emits an event through one bus
(`monitoring = true`, on by default):

- **SDK:** `client.on_event(print)` · `client.metrics()`
- **REST:** `GET /v1/metrics` (counters + gauges), `POST /v1/webhooks`
  registers a URL that receives every event as JSON
- **Dashboard:** the read-only UI at `http://127.0.0.1:8787` shows the intent
  timeline and live metrics

### Pick a trust tier

`Config.profile(name)` returns a preset guard chain; everything else stays at
safe defaults and any field can be overridden per call:

| Profile | Guards on | Extras |
|---|---|---|
| `strict` | injection · policy · signer · attestation · k-of-n · cosign · proof-of-compute | `k_of_n = 3`, cosign above 100 USDC |
| `balanced` | injection · policy · signer · attestation | single oracle, no cosign |
| `fast` | injection · policy | propose/refuse only, no release guards |

```python
client = AmanahClient(Config.profile("balanced"))
```

## Local demo

Requires Docker, the `stellar` CLI (major version pinned in
`acceptance/lib.sh`), and the Rust `wasm32v1-none` target. Everything below
runs on the local Stellar quickstart container — no testnet, no real funds.

```bash
scripts/demo.sh
```

This is a narrated, timed walkthrough of the whole spine as Bu Sari would see
it:

1. **Seed** — deploys the escrow + policy-account, registers the oracle,
   binds her suppliers, and starts a read-only UI at
   `http://127.0.0.1:8787`.
2. **Injected refusal** — a fake "our payment address has changed" email is
   proposed as an invoice. The injection scanner and policy layer refuse it
   before any transaction is proposed — exit code `2`, no chain call.
3. **In-policy escrow** — a legitimate invoice is proposed and escrowed
   on-chain, funds locked and structurally bound to that one supplier.
4. **Attestation + release** — the oracle attests `Shipped`; the escrow
   releases to the supplier and nowhere else.
5. **MOCK cash-out** — `amanah/anchor/mock_anchor.py` records a
   `MOCK-<ulid>` receipt. This is a stand-in for a real SEP-24 anchor
   off-ramp (structurally zero network calls) — never a real payout.
6. **Failure path** — a second order is left unshipped past its deadline
   (a real few-second wait, no ledger time-travel) and refunds Bu Sari; the
   supplier never touches those funds.

Pace between steps is `AMANAH_DEMO_PACE` seconds (default `2`). The UI stays
up after the walkthrough finishes — `Ctrl+C` to stop it, then
`scripts/local_network.sh down`.

## Acceptance gates

Each phase gate is one runnable command; `acceptance/acceptance.sh` (no
flags) re-runs all of them and requires the full T1–T10 matrix green with no
regression.

```bash
acceptance/acceptance.sh --gate P0   # T1-T3, T5 — escrow contract
acceptance/acceptance.sh --gate P1   # T4        — policy-signer __check_auth
acceptance/acceptance.sh --gate P2   # T6-T9     — policy engine, injection, audit (pytest)
acceptance/acceptance.sh --gate P3   # T10       — local e2e: happy + failure + MOCK cash-out
acceptance/acceptance.sh             # full re-run, T1-T10
```

`make live-check` runs the real-model extraction test against a local
`llama-server`; it is a human-triggered exit check, never part of a gate.

## Testnet deployment

Not deployed. `scripts/deploy_testnet.sh` prints the manual checklist for a
real Stellar testnet deploy and exits `1` — it is a human-run STOP boundary,
not called by any gate, script, or Makefile target. A deployed contract
address will be added here only after that checklist is completed by hand.

## Out of scope

Real anchor/off-ramp integration, mainnet deployment, KYC/licensing, and
testnet submission are outside this build — see `scripts/deploy_testnet.sh`
for what a real deploy would require.
