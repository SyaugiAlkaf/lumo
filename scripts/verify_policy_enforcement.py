#!/usr/bin/env python3
"""Verify — against the LIVE deployed policy-account on Stellar testnet — that a
correctly owner-signed instruction still cannot move money outside policy.

The policy-account is a custom smart account: it authorizes a USDC transfer only
when (1) the recipient is the one bound escrow and (2) the amount is within the
per-tx cap. This script signs a genuine owner authorization (the SME's ed25519
key, via the contract's Ed25519Signature type) for three transfers and runs each
through enforce-mode simulation, so the RPC actually invokes __check_auth:

    wrong recipient, in-cap   -> RecipientNotAllowed   (money can't be redirected)
    bound escrow, over cap    -> OverCap                (money can't exceed the cap)
    bound escrow, in-cap      -> authorized             (the legitimate payment)

A rejected authorization never mines a transaction, so simulation is the honest
way to observe the on-chain __check_auth verdict without spending fees.

Run:
    export SME_SECRET=$(stellar keys show lumo-sme)
    export DEPLOYER_SECRET=$(stellar keys show lumo-deployer)
    .venv/bin/python scripts/verify_policy_enforcement.py

Exits non-zero if any transfer is authorized or rejected against expectation.
Requires the `verify` extra: pip install -e '.[verify]'

The default deployed policy-account already holds test USDC on testnet, so it
runs as-is. Point it at your own deployment (POLICY_ID=...) and you must first
mint test USDC to that account for the recording pass to reach __check_auth.
"""
import hashlib
import os
import sys

from stellar_sdk import Keypair, Network, SorobanServer, TransactionBuilder, scval
from stellar_sdk import xdr as x
from stellar_sdk.address import Address
from stellar_sdk.auth import authorize_entry

RPC = os.environ.get("LUMO_RPC", "https://soroban-testnet.stellar.org")
PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE

POLICY = os.environ.get("POLICY_ID", "CD2EIG3V4TBGHSGLZYCIZRHVFVQFUA3NL2KG7SZFF3SIEGL7MMV4PF5L")
USDC = os.environ.get("USDC_SAC", "CDWS5VFOIDNU7X3O4CXNF2I5TMGT5RKLB4GDHU24VOO7FRGGI3XYTQC7")
ESCROW = os.environ.get("ESCROW_ID", "CARKYFTVFVUX2Y3OZJUPYBBZKTVVIHC3APSFAQOVL6DGKWU6D6ZGJJMK")
CAP = int(os.environ.get("POLICY_CAP", "20000000000"))  # 2,000 USDC in stroops
# A non-escrow contract stands in for an attacker sink (a contract holds a SAC
# balance without a trustline, so the recording pass doesn't trip on one).
NON_ESCROW = os.environ.get("NON_ESCROW", "CBY6WBJTUVEOGZVP65AUIUZFKYS5LKMH7MMD2TQX2HZXP67XVW6T7MGS")

ERRORS = {1: "FnNotAllowed", 2: "OverCap", 3: "SupplierNotApproved",
          4: "BadSignature", 5: "InvalidArgs", 6: "RecipientNotAllowed"}

server = SorobanServer(RPC)
owner = Keypair.from_secret(os.environ["SME_SECRET"])
source_kp = Keypair.from_secret(os.environ["DEPLOYER_SECRET"])


def owner_signature(preimage: x.HashIDPreimage) -> x.SCVal:
    payload = hashlib.sha256(preimage.to_xdr_bytes()).digest()
    return scval.to_struct({
        "public_key": scval.to_bytes(owner.raw_public_key()),
        "signature": scval.to_bytes(owner.sign(payload)),
    })


def check_auth_verdict(to_addr: str, amount: int) -> str:
    """Return the __check_auth error name, or 'AUTHORIZED' if it passed."""
    account = server.load_account(source_kp.public_key)
    tx = (
        TransactionBuilder(account, PASSPHRASE, base_fee=1_000_000)
        .set_timeout(120)
        .append_invoke_contract_function_op(
            contract_id=USDC,
            function_name="transfer",
            parameters=[
                scval.to_address(POLICY),
                scval.to_address(to_addr),
                scval.to_int128(amount),
            ],
        )
        .build()
    )
    recorded = server.simulate_transaction(tx)
    if recorded.error or not recorded.results:
        raise SystemExit(f"could not record auth footprint: {recorded.error}")

    valid_until = server.get_latest_ledger().sequence + 100
    op = tx.transaction.operations[0]
    op.auth = [
        authorize_entry(entry, owner_signature, valid_until, PASSPHRASE)
        if _is_policy_entry(entry) else entry
        for entry in map(x.SorobanAuthorizationEntry.from_xdr, recorded.results[0].auth)
    ]

    enforced = server.simulate_transaction(tx)
    if not enforced.error:
        return "AUTHORIZED"
    for code, name in ERRORS.items():
        if f", #{code})" in enforced.error:
            return name
    return f"rejected: {enforced.error}"


def _is_policy_entry(entry: x.SorobanAuthorizationEntry) -> bool:
    return (
        entry.credentials.type == x.SorobanCredentialsType.SOROBAN_CREDENTIALS_ADDRESS
        and Address.from_xdr_sc_address(entry.credentials.address.address).address == POLICY
    )


CASES = [
    ("wrong recipient, in-cap", NON_ESCROW, CAP // 2, "RecipientNotAllowed"),
    ("bound escrow, over cap", ESCROW, CAP + 1, "OverCap"),
    ("bound escrow, in-cap", ESCROW, 100_000_000, "AUTHORIZED"),
]

print(f"policy  {POLICY}")
print(f"escrow  {ESCROW}  (the only recipient the account may fund)")
print(f"cap     {CAP} stroops\n")

failures = 0
for label, to_addr, amount, expected in CASES:
    verdict = check_auth_verdict(to_addr, amount)
    ok = verdict == expected
    failures += not ok
    mark = "ok " if ok else "FAIL"
    print(f"[{mark}] {label:24} -> {verdict}  (expected {expected})")

sys.exit(1 if failures else 0)
