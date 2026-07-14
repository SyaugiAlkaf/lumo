import hashlib
from dataclasses import dataclass

from lumo.chain import ChainError
from lumo.chain.soroban_client import InvokeResult

ESCROW_VAULT = "MOCK-ESCROW-VAULT"


@dataclass
class MockIntent:
    sme: str
    supplier: str
    token: str
    amount: int
    request_hash: str
    deadline: int
    status: str = "Funded"
    attestation: str | None = None


class MockChainAdapter:
    def __init__(self, now: int = 0):
        self.now = now
        self.contract_id: str | None = None
        self.intents: dict[int, MockIntent] = {}
        self.balances: dict[tuple[str, str], int] = {}
        self._tx_count = 0

    def _tx_hash(self, action: str) -> str:
        self._tx_count += 1
        return hashlib.sha256(f"{action}:{self._tx_count}".encode()).hexdigest()

    def fund(self, token: str, address: str, amount: int) -> None:
        self.balances[(token, address)] = self.balance(token, address) + amount

    def balance(self, token: str, address: str) -> int:
        return self.balances.get((token, address), 0)

    def _move(self, token: str, src: str, dst: str, amount: int) -> None:
        if self.balance(token, src) < amount:
            raise ChainError(f"InsufficientBalance: {src} holds < {amount}")
        self.balances[(token, src)] -= amount
        self.balances[(token, dst)] = self.balance(token, dst) + amount

    def _funded(self, chain_intent_id: int) -> MockIntent:
        intent = self.intents.get(chain_intent_id)
        if intent is None:
            raise ChainError(f"IntentNotFound: {chain_intent_id}")
        if intent.status != "Funded":
            raise ChainError(f"NotFunded: intent {chain_intent_id} is {intent.status}")
        return intent

    def deploy(self) -> str:
        self.contract_id = "C" + hashlib.sha256(b"lumo-mock-escrow").hexdigest()[:31].upper()
        return self.contract_id

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
        self._move(token, sme, ESCROW_VAULT, amount)
        chain_intent_id = len(self.intents) + 1
        self.intents[chain_intent_id] = MockIntent(
            sme=sme,
            supplier=supplier,
            token=token,
            amount=amount,
            request_hash=request_hash,
            deadline=deadline,
        )
        return InvokeResult(value=chain_intent_id, tx_hash=self._tx_hash("create_intent"))

    def attest(
        self, chain_intent_id: int, oracle: str, kind: str, source: str | None = None
    ) -> InvokeResult:
        intent = self._funded(chain_intent_id)
        if intent.attestation is None:
            intent.attestation = kind
        return InvokeResult(value=None, tx_hash=self._tx_hash(f"attest_{kind}"))

    def release(self, chain_intent_id: int, source: str | None = None) -> InvokeResult:
        intent = self._funded(chain_intent_id)
        if intent.attestation != "Shipped":
            raise ChainError("NotShipped: release requires a Shipped attestation")
        self._move(intent.token, ESCROW_VAULT, intent.supplier, intent.amount)
        intent.status = "Released"
        return InvokeResult(value=None, tx_hash=self._tx_hash("release"))

    def refund(self, chain_intent_id: int, source: str | None = None) -> InvokeResult:
        intent = self._funded(chain_intent_id)
        if intent.attestation == "Shipped":
            raise ChainError("ShippedBeatsDeadline: refund blocked by Shipped attestation")
        if intent.attestation != "Failed" and self.now < intent.deadline:
            raise ChainError("DeadlineNotReached: refund needs Failed attestation or deadline")
        self._move(intent.token, ESCROW_VAULT, intent.sme, intent.amount)
        intent.status = "Refunded"
        return InvokeResult(value=None, tx_hash=self._tx_hash("refund"))

    def get_status(self, chain_intent_id: int) -> dict | None:
        intent = self.intents.get(chain_intent_id)
        if intent is None:
            return None
        return {
            "status": intent.status,
            "request_hash": intent.request_hash,
            "sme": intent.sme,
            "supplier": intent.supplier,
            "token": intent.token,
            "amount": str(intent.amount),
            "deadline": intent.deadline,
        }
