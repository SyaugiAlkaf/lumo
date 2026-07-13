# Amanah

On-device SME treasury agent for USDC on Soroban. An untrusted local LLM only
reads invoices; a deterministic policy layer decides; two on-chain contracts
enforce. Funds in escrow can structurally reach only the bound supplier (on a
`Shipped` attestation) or return to the SME (on `Failed`, or on deadline with no
attestation) — so compromising the agent cannot move money to an attacker.

## Contracts

`contracts/` is a Rust workspace (`soroban-sdk 26`, target `wasm32v1-none`).

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

## Build and test

```bash
cd contracts
cargo test -p amanah-escrow      # unit + revert tests
stellar contract build           # -> target/wasm32v1-none/release/amanah_escrow.wasm
```

## Acceptance gate

```bash
acceptance/acceptance.sh --gate P0
```

P0 requires the escrow tests (T1–T3) green and the wasm build clean. T4 and
T6–T10 are later-phase placeholders.
