import json
import re
import subprocess
from dataclasses import dataclass

TX_HASH = re.compile(r"\b([0-9a-f]{64})\b")

CREATE_INTENT_ARG_ORDER = ("sme", "supplier", "token", "amount", "request_hash", "deadline")


class SorobanError(RuntimeError):
    pass


@dataclass
class InvokeResult:
    value: object
    tx_hash: str | None


def encode_enum(variant: str, value=None) -> str:
    if value is None:
        return json.dumps(variant)
    return json.dumps({variant: value}, separators=(",", ":"))


def encode_i128(amount: int) -> str:
    return str(amount)


def encode_arg(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return str(value)


def build_invoke_cmd(
    contract_id: str,
    source: str,
    network: str,
    function: str,
    args: list[tuple[str, str]],
    send: str | None = None,
) -> list[str]:
    cmd = [
        "stellar",
        "contract",
        "invoke",
        "--id",
        contract_id,
        "--source-account",
        source,
        "--network",
        network,
    ]
    if send:
        cmd += ["--send", send]
    cmd += ["--", function]
    for name, value in args:
        cmd += [f"--{name}", value]
    return cmd


def variant_of(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and len(value) == 1:
        return next(iter(value))
    raise SorobanError(f"unrecognized enum shape: {value!r}")


class SorobanClient:
    def __init__(self, escrow_id: str, network: str = "local", source: str | None = None):
        self.escrow_id = escrow_id
        self.network = network
        self.source = source

    def invoke(
        self,
        function: str,
        args: list[tuple[str, str]],
        source: str | None = None,
        contract_id: str | None = None,
        send: str | None = None,
    ) -> InvokeResult:
        cmd = build_invoke_cmd(
            contract_id or self.escrow_id,
            source or self.source,
            self.network,
            function,
            args,
            send=send,
        )
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise SorobanError(
                f"{function} failed (exit {proc.returncode}): {proc.stderr.strip()[-500:]}"
            )
        out = proc.stdout.strip()
        value = json.loads(out) if out else None
        match = TX_HASH.search(proc.stderr)
        return InvokeResult(value=value, tx_hash=match.group(1) if match else None)

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
        values = {
            "sme": sme,
            "supplier": supplier,
            "token": token,
            "amount": encode_i128(amount),
            "request_hash": request_hash,
            "deadline": str(deadline),
        }
        args = [(name, values[name]) for name in CREATE_INTENT_ARG_ORDER]
        return self.invoke("create_intent", args, source=source)

    def attest(
        self, chain_intent_id: int, oracle: str, kind: str, source: str | None = None
    ) -> InvokeResult:
        args = [
            ("intent_id", str(chain_intent_id)),
            ("oracle", oracle),
            ("kind", encode_enum(kind)),
        ]
        return self.invoke("attest", args, source=source)

    def release(self, chain_intent_id: int, source: str | None = None) -> InvokeResult:
        return self.invoke("release", [("intent_id", str(chain_intent_id))], source=source)

    def refund(self, chain_intent_id: int, source: str | None = None) -> InvokeResult:
        return self.invoke("refund", [("intent_id", str(chain_intent_id))], source=source)

    def add_oracle(self, oracle: str, source: str | None = None) -> InvokeResult:
        return self.invoke("add_oracle", [("oracle", oracle)], source=source)

    def get_intent(self, chain_intent_id: int) -> dict | None:
        result = self.invoke(
            "get_intent", [("intent_id", str(chain_intent_id))], send="no"
        )
        return result.value

    def balance(self, token_id: str, address: str) -> int:
        result = self.invoke(
            "balance", [("id", address)], contract_id=token_id, send="no"
        )
        return int(result.value)
