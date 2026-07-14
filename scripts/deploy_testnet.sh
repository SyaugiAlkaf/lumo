#!/usr/bin/env bash
# scripts/deploy_testnet.sh — HUMAN-GATED STOP boundary.
#
# This script does not deploy anything. It prints the manual checklist for
# a real Stellar testnet deploy, then exits 1. No gate, Makefile target, or
# other script calls this file — a real testnet deploy is a deliberate,
# human-run action using the operator's own keys, never automated.
set -euo pipefail

cat <<'EOF'
======================================================================
 LUMO — testnet deploy checklist (human-run, NOT automated)
======================================================================

This script only prints the checklist below, then exits 1. Every
acceptance gate (P0-P4) and scripts/demo.sh only ever touch the local
Docker quickstart network — none of them call this file.

  1. Generate/verify your own testnet identity:
       stellar keys generate lumo-deployer --network testnet --fund
       stellar keys address lumo-deployer

  2. Build the contracts:
       cd contracts && stellar contract build

  3. Deploy the escrow (admin = your testnet identity):
       stellar contract deploy \
         --wasm contracts/target/wasm32v1-none/release/lumo_escrow.wasm \
         --source-account lumo-deployer --network testnet \
         -- --admin <ADMIN_ADDRESS>

  4. Deploy the policy-account (owner = the SME's ed25519 pubkey hex,
     cap_per_tx in stroops):
       stellar contract deploy \
         --wasm contracts/target/wasm32v1-none/release/lumo_policy_account.wasm \
         --source-account lumo-deployer --network testnet \
         -- --owner <SME_PUBKEY_HEX> --cap_per_tx <STROOPS>

  5. Get a testnet USDC SAC. Use an existing testnet USDC issuer, or your
     own test asset — never wrap a mainnet asset:
       stellar contract id asset --asset USDC:<ISSUER> --network testnet

  6. Register at least one oracle on the escrow:
       stellar contract invoke --id <ESCROW_ID> \
         --source-account lumo-deployer --network testnet \
         -- add_oracle --oracle <ORACLE_ADDRESS>

  7. Regenerate bindings against the deployed wasm (`make spec`) and diff
     them against the committed bindings/*.json — they must match exactly.

  8. Only after every step above is verified on-chain: add the deployed
     contract IDs to README.md under "Testnet deployment" — never before.

  9. This stays a LOCAL-network demo (scripts/demo.sh) until a human
     completes steps 1-8. Real anchor/off-ramp integration and mainnet
     deploy are separate, out-of-scope STOP items — lumo/anchor/mock_anchor.py
     stays structurally mocked (zero network calls) regardless.

======================================================================
EOF

exit 1
