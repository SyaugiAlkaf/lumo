from typing import Literal, Optional

from pydantic import BaseModel


class ExtractedInvoice(BaseModel):
    invoice_ref: Optional[str] = None
    supplier_name: Optional[str] = None
    payment_address: Optional[str] = None
    amount: Optional[str] = None
    currency: Optional[str] = None


class ScanResult(BaseModel):
    flags: list[str]
    normalized_text: str
    addresses: list[str]

    @property
    def suspicious(self) -> bool:
        return bool(self.flags)


class PriorIntent(BaseModel):
    amount: int
    status: Literal["proposed", "escrowed", "released", "reverted"]


class PaymentRequest(BaseModel):
    supplier_name: Optional[str]
    registry_address: Optional[str]
    invoice_address: Optional[str]
    amount_stroops: Optional[int]
    request_hash: str
    injection_flags: list[str] = []


class PolicyContext(BaseModel):
    cap_per_tx: int
    cap_daily: int
    prior_intents: list[PriorIntent] = []
    known_request_hashes: set[str] = set()


class Evaluation(BaseModel):
    allowed: bool
    codes: list[str]


class IntentDraft(BaseModel):
    supplier_id: str
    amount: int
    token: str
    deadline: int
    invoice_ref: Optional[str]
    request_hash: str


class TxArgs(BaseModel):
    sme: str
    supplier: str
    token: str
    amount: str
    request_hash: str
    deadline: int


class TxPlan(BaseModel):
    function: Literal["create_intent"]
    args: TxArgs


class PipelineResult(BaseModel):
    decision: Literal["proposed", "refused"]
    codes: list[str]
    flags: list[str]
    request_hash: str
    tx_plan: Optional[TxPlan] = None
    intent_id: Optional[str] = None
