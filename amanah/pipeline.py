import time
from decimal import Decimal, InvalidOperation

from amanah.chain.request_hash import request_hash
from amanah.config import Config
from amanah.db.repo import Repo
from amanah.llm.provider import ExtractionProvider
from amanah.models import (
    IntentDraft,
    PaymentRequest,
    PipelineResult,
    PolicyContext,
    TxArgs,
    TxPlan,
)
from amanah.policy import engine
from amanah.security import injection

STROOP = 10_000_000


def to_stroops(amount: str | None) -> int | None:
    if amount is None:
        return None
    try:
        stroops = Decimal(amount) * STROOP
    except InvalidOperation:
        return None
    if stroops != stroops.to_integral_value():
        return None
    return int(stroops)


def run(invoice_text: str, repo: Repo, provider: ExtractionProvider, config: Config) -> PipelineResult:
    scan = injection.scan(invoice_text)
    extracted = provider.extract(invoice_text)

    supplier = (
        repo.supplier_by_name(extracted.supplier_name) if extracted.supplier_name else None
    )
    registry_address = supplier["address"] if supplier else None
    amount_stroops = to_stroops(extracted.amount)
    rules = repo.rules()
    deadline = int(time.time()) + config.deadline_secs

    rhash = request_hash(
        {
            "sme": rules["sme_address"],
            "supplier": registry_address or "",
            "token": rules["token_address"],
            "amount": str(amount_stroops or 0),
            "invoice_ref": extracted.invoice_ref or "",
        }
    )

    foreign = [a for a in scan.addresses if a != registry_address]
    req = PaymentRequest(
        supplier_name=extracted.supplier_name,
        registry_address=registry_address,
        invoice_address=foreign[0] if foreign else extracted.payment_address,
        amount_stroops=amount_stroops,
        request_hash=rhash,
        injection_flags=scan.flags,
    )
    ctx = PolicyContext(
        cap_per_tx=int(rules["cap_per_tx"]),
        cap_daily=int(rules["cap_daily"]),
        prior_intents=repo.intents_today(),
        known_request_hashes=repo.known_request_hashes(),
    )
    evaluation = engine.evaluate(req, ctx)

    if not evaluation.allowed:
        repo.record_decision(
            decision="refused",
            codes=evaluation.codes,
            request_hash=rhash,
            detail=extracted.invoice_ref,
        )
        return PipelineResult(
            decision="refused",
            codes=evaluation.codes,
            flags=scan.flags,
            request_hash=rhash,
        )

    tx_plan = TxPlan(
        function="create_intent",
        args=TxArgs(
            sme=rules["sme_address"],
            supplier=registry_address,
            token=rules["token_address"],
            amount=str(amount_stroops),
            request_hash=rhash,
            deadline=deadline,
        ),
    )
    outcome = repo.record_decision(
        decision="proposed",
        codes=evaluation.codes,
        request_hash=rhash,
        intent=IntentDraft(
            supplier_id=supplier["id"],
            amount=amount_stroops,
            token=rules["token_address"],
            deadline=deadline,
            invoice_ref=extracted.invoice_ref,
            request_hash=rhash,
        ),
    )
    return PipelineResult(
        decision="proposed",
        codes=evaluation.codes,
        flags=scan.flags,
        request_hash=rhash,
        tx_plan=tx_plan,
        intent_id=outcome.intent_id,
    )
