# Contract interface bindings

Frozen cross-facet interface artifacts. Regenerate with `make spec` (rebuilds the
wasm, then `stellar contract info interface --output json-formatted`). The Python
chain layer builds tx plans against these — treat the argument order as an ABI.

- `escrow.json` — `LumoEscrow` SCSpec (`SCSpecEntry` stream).
- `policy_account.json` — `PolicyAccount` SCSpec.

## Frozen `create_intent` argument order

`create_intent(sme, supplier, token, amount, request_hash, deadline)` — positions
`supplier@1` and `amount@3` are read by the policy-signer's `__check_auth`. A reorder
is caught by `guard_create_intent_arg_order` in `policy-account/src/test.rs`.

## CLI serialization conventions

`stellar contract invoke` reads/writes JSON with these encodings — the Python
`chain/soroban_client.py` serializer must match:

- **`i128` / `u64` / `u128`** → JSON **string** (e.g. `"1000"`), never a JSON number.
  Large integers lose precision as JSON numbers; the CLI always emits/accepts strings.
- **Unit enum variants** (`Status::Funded`, `AttestKind::Shipped`, `Attestation::None`)
  → bare **string** of the variant name (e.g. `"Funded"`, `"Shipped"`).
- **`BytesN<32>`** (e.g. `request_hash`) → hex string, no `0x` prefix.
- **`Address`** → `G...` / `C...` strkey string.
