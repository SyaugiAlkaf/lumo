# Lumo

<p align="center">
  <img src="docs/hero.png" alt="Lumo — the agent can be tricked, the money cannot" width="860">
</p>

**The agent can be tricked. The money cannot.**

**Live site:** [syaugialkaf.github.io/lumo](https://syaugialkaf.github.io/lumo/) · **Testnet contracts:** see [Testnet deployment](#testnet-deployment)

On-device SME treasury agent for USDC on Soroban. An untrusted local LLM only
reads invoices; a deterministic policy layer decides; two on-chain contracts
enforce. Funds in escrow can structurally reach only the bound supplier (on a
`Shipped` attestation) or return to the SME (on `Failed`, or on deadline with no
attestation) — so compromising the agent cannot move money to an attacker.

**Demo persona:** Bu Sari, owner of Sari Craft Export, a batik exporter in
Yogyakarta, Indonesia. She pays overseas fabric suppliers in USDC and wants an
agent that can read an invoice and propose a payment — without ever being able
to send her money somewhere an attacker chose.

## Quick start

Everything below runs **offline in `mock` mode with no keys** — safe to try in under a minute.

**Run the agent (CLI):**
```bash
git clone https://github.com/SyaugiAlkaf/lumo && cd lumo
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m lumo.cli init                  # local DB + a seeded demo supplier
printf 'INVOICE INV-1\nFrom: CV Batik Nusantara\nAmount due: 1,250.00 USDC\n' > invoice.txt
.venv/bin/python -m lumo.cli propose invoice.txt   # -> decision + reason codes as JSON
```

**Embed it as an SDK (5 lines):**
```python
from lumo import LumoClient

client = LumoClient()
d = client.propose(open("invoice.txt").read())
print(d.decision, d.codes)   # proposed | refused | held  +  the reason codes
# a proposal carries the exact create_intent tx plan and an intent_id you can status() later
```

**Ship it as a microservice (Docker):**
```bash
docker compose up --build    # REST API on :8788, chain adapter in safe mock mode (no keys)
curl -sX POST localhost:8788/v1/intents -H 'Content-Type: application/json' \
  -d '{"invoice":"INVOICE INV-1\nFrom: CV Batik Nusantara\nAmount due: 1,250.00 USDC"}'
```

**Plug it into any AI agent (MCP):**
```bash
python -m lumo.mcp           # stdio MCP server: propose_payment · get_status · attest
```

To settle on **Stellar testnet**, add the `stellar` CLI + a keystore and set
`LUMO_CHAIN_ADAPTER=soroban` — plus `LUMO_SME_SMART_ACCOUNT=<policy-account>` to
gate every payment on-chain through the contract's `__check_auth`. Full options,
language bindings, and trust tiers: [Integrate](#integrate) · [`docs/integration.md`](docs/integration.md).

## Architecture

<p align="center">
  <img src="docs/architecture.png" alt="Lumo architecture: invoice -> on-device AI (reads only) -> policy engine (guard) -> Soroban (guard) -> USDC released; a bad payment is stopped at the policy engine and again on-chain" width="960">
</p>

The AI reads (untrusted); a deterministic policy decides; Soroban enforces. In
code that path is `lumo/security` (injection scan) -> `lumo/llm` (mock or llama,
extraction-only) -> `lumo/policy` (caps, allowlist) -> `lumo/flow` ->
`lumo/chain/soroban_client` (stellar CLI subprocess), with `lumo/db` as the
single audit chokepoint and two Soroban contracts as the on-chain gates: the
policy-signed account (`__check_auth`: per-tx cap + supplier allowlist) and the
attestation escrow (`create_intent -> attest -> release | refund`).

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

## Prior art, honestly

On-chain spend caps and payee allowlists already exist — Coinbase Spend
Permissions, Crossmint on Soroban, OpenZeppelin's Stellar smart accounts. Lumo
does not claim to invent them. Its contribution is the combination: an
**attestation-gated escrow fused with the policy-signed account** (others
release on a human signature), aimed squarely at the **compromised-agent and
invoice-fraud / business-email-compromise** threat that agent-payment guidance
usually leaves to the operator — packaged full-stack with on-device inference
for the cross-border SME vertical.

## Repository layout

```
contracts/           Rust workspace (soroban-sdk 26, wasm32v1-none)
  escrow/             conditional-release escrow (T1-T3, T5)
  policy-account/     __check_auth policy-signer smart account (T4)
bindings/             frozen contract interface (escrow.json, policy_account.json)
lumo/               the Python agent (one package)
  llm/                extraction-only providers: mock + llama-server
  security/           injection scanner (NFKC + zero-width strip, patterns)
  policy/             deterministic evaluate() — caps, registry, injection
  db/                 SQLite schema, migrations, repo (single audit chokepoint)
  chain/              stellar CLI client, request_hash, chain-wins mapper
  anchor/             mock_anchor.py — SEP-24-shaped, zero network
  ui/                 monitoring dashboard + wired testnet tester (/testnet)
site/                 self-contained public landing page (landing_check.sh gate)
tests/                pytest: policy engine, injection, audit, db, chain client
acceptance/           acceptance.sh (gate runner) + t10_e2e.sh (local e2e)
scripts/              local_network / deploy_local / demo / deploy_testnet / testnet_serve
```

## Contracts

### `lumo-escrow`

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

### `lumo-policy-account`

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
.venv/bin/python -m lumo.cli --db /tmp/lumo.db init
.venv/bin/python -m lumo.cli propose tests/fixtures/invoices/clean_in_policy.txt
```

`propose` exits `0` and prints a tx plan for an in-policy invoice, or exits `2`
with refusal codes (`INJECTION_SUSPECTED`, `OVER_TX_CAP`, `UNKNOWN_SUPPLIER`,
...) and proposes nothing on-chain. `LUMO_PROVIDER=mock` (default) never
touches a real model; point `LUMO_PROVIDER=llama` + `LUMO_LLAMA_URL` at a
local `llama-server` for the real extraction path (`make live-check`).

## Try it on Stellar testnet (web)

Two web surfaces ship with the agent:

- **Landing** — `site/index.html`, a self-contained page (the only external
  request is Google Fonts). `scripts/landing_check.sh` asserts it stays
  self-contained, links the live contracts, and leaks no secret key.
- **Live testnet tester** — a one-page tool that runs a real invoice against
  the deployed contracts and shows the actual `create_intent → attest →
  release` transactions on Stellar Expert, or refuses a poisoned / over-cap
  invoice with the real policy codes and **zero** transactions.

```bash
scripts/testnet_serve.sh     # one origin: / landing · /testnet tester · /dashboard monitor
scripts/testnet_smoke.sh     # POSTs a clean invoice, asserts a real create_intent tx hash
```

The tester refers to three funded testnet keystore identities
(`lumo-deployer`, `lumo-sme`, `lumo-supplier`) **by name only** — it never
reads, prints, or exports a secret key. Its presets (clean / over-cap /
injection) are built from the live per-transaction cap and approved supplier
returned by `/testnet/info`, so a clean invoice settles on-chain and a tampered
one is refused before anything is signed. Nothing here touches mainnet or real
funds.

<p align="center">
  <img src="docs/tester-proposed.png" alt="Proposed: a clean invoice settles with a real create_intent, attest and release trail" width="49%">
  <img src="docs/tester-refused.png" alt="Refused: a prompt-injected invoice is blocked with zero transactions" width="49%">
</p>

<p align="center"><sub><b>Left</b> — a clean invoice is escrowed, attested and released: three real testnet transactions to the approved payee.&nbsp;&nbsp;<b>Right</b> — a prompt-injected invoice is refused by the policy layer (<code>INJECTION_SUSPECTED · ADDRESS_MISMATCH</code>) and <b>zero</b> transactions are signed. The agent was fooled; the money never moved.</sub></p>

## Integrate

Deeper walkthrough with every option: [`docs/integration.md`](docs/integration.md).
Runnable versions of the snippets live in `examples/`.

### Integrate in 5 lines

```python
from lumo import LumoClient

client = LumoClient()
decision = client.propose(open("invoice.txt").read())
print(decision.decision, decision.codes)
```

`decision.decision` is `proposed`, `refused`, or `held`; a proposal carries the
exact `create_intent` tx plan and an `intent_id` you can `status()` later.

### Call from any language

Start the REST API (`python -m lumo.api`, default `127.0.0.1:8788`) and use
plain HTTP — the full schema is served at `/v1/openapi.json`:

```bash
curl -X POST http://127.0.0.1:8788/v1/intents \
  -H 'Content-Type: application/json' \
  -d '{"invoice": "INVOICE INV-2026-0042\nFrom: CV Batik Nusantara\nAmount due: 1,250.00 USDC\n"}'
```

### Run it as a microservice (Docker)

Drop the trust layer into any stack as a container:

```bash
docker compose up --build      # REST API on http://127.0.0.1:8788
# or:
docker build -t lumo . && docker run -p 8788:8788 lumo
```

The image ships the REST API plus the deterministic guard chain (injection
scan, per-tx cap, supplier allowlist, attestation gating) with the chain
adapter in **`mock`** mode — no keys, safe to publish. Callers get the payment
*decision* as a service and wire their own chain/signer. For real on-chain
settlement, extend the image with the `stellar` CLI and a mounted keystore,
then set `LUMO_CHAIN_ADAPTER=soroban` (see the `Dockerfile` header).

### Use from any AI agent

`python -m lumo.mcp` is an MCP server over stdio exposing three tools:
`lumo.propose_payment`, `lumo.get_status`, `lumo.attest`. Point any
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
- **Dashboard:** the read-only monitoring UI at
  `http://127.0.0.1:8787/dashboard` shows the intent timeline and live metrics
  (the same server serves the landing at `/` and the testnet tester at `/testnet`)

### Pick a trust tier

`Config.profile(name)` returns a preset guard chain; everything else stays at
safe defaults and any field can be overridden per call:

| Profile | Guards on | Extras |
|---|---|---|
| `strict` | injection · policy · signer · attestation · k-of-n · cosign · proof-of-compute | `k_of_n = 3`, cosign above 100 USDC |
| `balanced` | injection · policy · signer · attestation | single oracle, no cosign |
| `fast` | injection · policy | propose/refuse only, no release guards |

```python
client = LumoClient(Config.profile("balanced"))
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
5. **MOCK cash-out** — `lumo/anchor/mock_anchor.py` records a
   `MOCK-<ulid>` receipt. This is a stand-in for a real SEP-24 anchor
   off-ramp (structurally zero network calls) — never a real payout.
6. **Failure path** — a second order is left unshipped past its deadline
   (a real few-second wait, no ledger time-travel) and refunds Bu Sari; the
   supplier never touches those funds.

Pace between steps is `LUMO_DEMO_PACE` seconds (default `2`). The UI stays
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

Deployed to the **Stellar testnet** (`Test SDF Network ; September 2015`) — a
valueless public test network. No mainnet asset is referenced and no real funds
move; the cash-out anchor stays structurally mocked (`lumo/anchor/mock_anchor.py`).

| Artifact | Value |
|---|---|
| Network | `testnet` |
| `lumo-escrow` | [`CARKYFTVFVUX2Y3OZJUPYBBZKTVVIHC3APSFAQOVL6DGKWU6D6ZGJJMK`](https://stellar.expert/explorer/testnet/contract/CARKYFTVFVUX2Y3OZJUPYBBZKTVVIHC3APSFAQOVL6DGKWU6D6ZGJJMK) |
| `lumo-policy-account` | [`CD2EIG3V4TBGHSGLZYCIZRHVFVQFUA3NL2KG7SZFF3SIEGL7MMV4PF5L`](https://stellar.expert/explorer/testnet/contract/CD2EIG3V4TBGHSGLZYCIZRHVFVQFUA3NL2KG7SZFF3SIEGL7MMV4PF5L) |
| Escrow admin + oracle | `GBPSOKJDBP5REZBCL6TWAXMU6CEWV5YMU3PMQUSDRGJM6K77TZHGGEEY` |
| Policy owner (SME ed25519, hex) | `12265b095264b6a939bac5e35e7144fd0c3c8de5d44336e8799e4e0a9edf164b` |
| Policy per-tx cap | `20000000000` stroops (2,000 test USDC) |
| Test USDC SAC | [`CDWS5VFOIDNU7X3O4CXNF2I5TMGT5RKLB4GDHU24VOO7FRGGI3XYTQC7`](https://stellar.expert/explorer/testnet/contract/CDWS5VFOIDNU7X3O4CXNF2I5TMGT5RKLB4GDHU24VOO7FRGGI3XYTQC7) |

The USDC used here is a **self-issued testnet asset** (`USDC:GC5U5EI2…`), never a
mainnet asset. One full end-to-end smoke ran on-chain — `create_intent` →
`attest(Shipped)` → `release` — pulling 100 test USDC into escrow and settling it
to the bound supplier only:

| Step | Transaction |
|---|---|
| `add_oracle` | [`fe803970…`](https://stellar.expert/explorer/testnet/tx/fe8039705d83d4732edb3915f1d258b330ff6c9ebf2942c34351e2fe462ed0b6) |
| `create_intent` | [`88b5b770…`](https://stellar.expert/explorer/testnet/tx/88b5b7701d4013893ae063e20fd6f42944d9bac04dd290a3a19d32d09244c4a1) |
| `attest(Shipped)` | [`e948634a…`](https://stellar.expert/explorer/testnet/tx/e948634a0cf4e6e3fb7cdda1af21fdb0b0a1db742797a3a8d0aa7612f8a03391) |
| `release` | [`0b5d14a5…`](https://stellar.expert/explorer/testnet/tx/0b5d14a535d0fd7ae03b40eccf14205c042d606c4c2c0675ef0ce47265956f4f) |

The live tester (`scripts/testnet_serve.sh`) produces a fresh trail like this on
every clean run, and returns an empty transaction list on every refusal.

The policy-account is a custom smart account: its `set_escrow` / `add_supplier`
config calls are authorized by the SME owner's ed25519 signature through
`__check_auth`, on-chain — the CLI cannot forge that signature, so the account
was configured with an owner-signed authorization entry:

| Step | Transaction |
|---|---|
| `set_escrow` (bind the one fundable escrow) | [`bca818b7…`](https://stellar.expert/explorer/testnet/tx/bca818b75843b22768acd4dcf0942cea58e2bbe9dcf63c5f5c206236232b13eb) |
| `add_supplier` (approve the payee) | [`9bd11a5f…`](https://stellar.expert/explorer/testnet/tx/9bd11a5f1ba2a53affcbff11dfde0c4c282c5107e79dd6aa074cd18b158e4b57) |

### Every payment flows through the smart account

`create_intent` is routed through the policy-account, not a bare keypair. The
escrow's `create_intent` calls `sme.require_auth()` and transfers the funds
`from` the sme, so with `sme` = the policy-account **both** the intent and its
funding transfer pass through `__check_auth` — the on-chain per-tx cap,
approved-supplier allowlist, and recipient binding gate every real payment. The
owner's ed25519 key signs the authorization; a compromised agent cannot forge
it. This is `LUMO_SME_SMART_ACCOUNT` in `scripts/testnet_serve.sh`
(`lumo/chain/smart_account.py`), enforced live on-chain:

| Path | Transaction |
|---|---|
| approved supplier, in-cap → `__check_auth` passes, funds settle | [`42b9c73f…`](https://stellar.expert/explorer/testnet/tx/42b9c73f6c4761f7ddbc2db593934845e436e75c8b6edfe0f61acab9fda142c6) |
| unapproved supplier / over-cap / wrong recipient → rejected on-chain | see the verifier below + [`928eb96d…`](https://stellar.expert/explorer/testnet/tx/928eb96dd7c19e9fcd768676e20bc342bc57a0a690578973a188b3e60885d773) |

### The money cannot be tricked — verify it yourself

`scripts/verify_policy_enforcement.py` signs a **genuine owner authorization**
and asks the live deployed account to authorize three transfers, running each
through enforce-mode simulation so the RPC actually invokes `__check_auth`:

```
[ok] wrong recipient, in-cap  -> RecipientNotAllowed   (money can't be redirected)
[ok] bound escrow, over cap   -> OverCap                (money can't exceed the cap)
[ok] bound escrow, in-cap     -> AUTHORIZED             (the legitimate payment)
```

Even a correctly-signed instruction cannot move money outside policy — the
enforcement lives in the deployed contract, not the agent. Reproduce with:

```bash
pip install -e .
export SME_SECRET=$(stellar keys show lumo-sme)
export DEPLOYER_SECRET=$(stellar keys show lumo-deployer)
python scripts/verify_policy_enforcement.py
```

Re-deploying is a deliberate, human-run action — `scripts/deploy_testnet.sh`
prints the checklist and exits `1`; no gate, script, or Makefile target
automates it.

## Out of scope

Real anchor/off-ramp integration, mainnet deployment, and KYC/licensing are
outside this build — see `scripts/deploy_testnet.sh` for what a real (mainnet)
deploy would require.
