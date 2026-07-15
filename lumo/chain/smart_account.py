"""Submit create_intent through the policy-account smart account, authorized by
the owner's ed25519 signature via the contract's __check_auth. This is what puts
the on-chain policy (per-tx cap + approved-supplier + recipient binding) in the
money path of every real payment: the escrow's create_intent calls
sme.require_auth() and token.transfer(sme, escrow, amount), and when sme is the
policy-account BOTH auth contexts run through __check_auth.

The stellar CLI cannot produce the contract's custom Ed25519Signature, so this
path uses stellar-sdk (imported lazily — the mock/CLI paths never need it).
"""
import hashlib
import subprocess

from lumo.chain.soroban_client import InvokeResult

_RPC = {"testnet": "https://soroban-testnet.stellar.org"}


def _secret(identity: str) -> str:
    proc = subprocess.run(
        ["stellar", "keys", "show", identity], capture_output=True, text=True, timeout=30
    )
    if proc.returncode != 0:
        raise RuntimeError(f"could not load key for {identity!r}: {proc.stderr.strip()[-200:]}")
    return proc.stdout.strip()


class SmartAccountClient:
    def __init__(self, escrow_id: str, smart_account: str, owner_source: str, network: str = "testnet"):
        self.escrow_id = escrow_id
        self.smart_account = smart_account
        self.owner_source = owner_source
        self.network = network

    def create_intent(
        self,
        *,
        sme: str,
        supplier: str,
        token: str,
        amount: int,
        request_hash: str,
        deadline: int,
        source: str | None = None,
    ) -> InvokeResult:
        from stellar_sdk import Keypair, Network, SorobanServer, TransactionBuilder, scval
        from stellar_sdk import xdr as x
        from stellar_sdk.address import Address
        from stellar_sdk.auth import authorize_entry
        from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus

        rpc = _RPC.get(self.network)
        if rpc is None:
            raise RuntimeError(f"smart-account mode is testnet-only, got network {self.network!r}")
        passphrase = Network.TESTNET_NETWORK_PASSPHRASE
        owner = Keypair.from_secret(_secret(self.owner_source))
        server = SorobanServer(rpc)

        def owner_signature(preimage: "x.HashIDPreimage") -> "x.SCVal":
            payload = hashlib.sha256(preimage.to_xdr_bytes()).digest()
            return scval.to_struct({
                "public_key": scval.to_bytes(owner.raw_public_key()),
                "signature": scval.to_bytes(owner.sign(payload)),
            })

        account = server.load_account(owner.public_key)
        tx = (
            TransactionBuilder(account, passphrase, base_fee=1_000_000)
            .set_timeout(120)
            .append_invoke_contract_function_op(
                contract_id=self.escrow_id,
                function_name="create_intent",
                parameters=[
                    scval.to_address(sme),
                    scval.to_address(supplier),
                    scval.to_address(token),
                    scval.to_int128(amount),
                    scval.to_bytes(bytes.fromhex(request_hash)),
                    scval.to_uint64(deadline),
                ],
            )
            .build()
        )

        recorded = server.simulate_transaction(tx)
        if recorded.error or not recorded.results:
            raise RuntimeError(f"create_intent simulate failed: {recorded.error}")

        valid_until = server.get_latest_ledger().sequence + 100
        op = tx.transaction.operations[0]
        op.auth = [
            authorize_entry(entry, owner_signature, valid_until, passphrase)
            if (entry.credentials.type == x.SorobanCredentialsType.SOROBAN_CREDENTIALS_ADDRESS
                and Address.from_xdr_sc_address(entry.credentials.address.address).address
                == self.smart_account)
            else entry
            for entry in map(x.SorobanAuthorizationEntry.from_xdr, recorded.results[0].auth)
        ]

        # Re-simulate with the signed auth so the resource budget covers the
        # __check_auth ed25519_verify (recording mode ignores it).
        enforced = server.simulate_transaction(tx)
        if enforced.error:
            raise RuntimeError(f"create_intent re-simulate failed: {enforced.error}")
        tx.transaction.soroban_data = x.SorobanTransactionData.from_xdr(enforced.transaction_data)
        tx.transaction.fee += enforced.min_resource_fee
        tx.sign(owner)

        resp = server.send_transaction(tx)
        if resp.status == SendTransactionStatus.ERROR:
            raise RuntimeError(f"create_intent submit rejected: {resp.error_result_xdr}")
        result = server.poll_transaction(resp.hash, max_attempts=40, sleep_strategy=lambda n: 1)
        if result.status != GetTransactionStatus.SUCCESS:
            raise RuntimeError(
                f"create_intent rejected on-chain: {getattr(result, 'result_xdr', '')}"
            )
        meta = x.TransactionMeta.from_xdr(result.result_meta_xdr)
        soroban = meta.v4.soroban_meta if meta.v == 4 else meta.v3.soroban_meta
        if soroban is None or soroban.return_value is None:
            raise RuntimeError("create_intent succeeded but returned no intent id")
        return InvokeResult(value=int(scval.to_native(soroban.return_value)), tx_hash=resp.hash)
