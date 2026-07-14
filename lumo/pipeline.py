import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from lumo.chain.request_hash import request_hash
from lumo.config import Config
from lumo.db.repo import Repo
from lumo.llm.provider import ExtractionProvider
from lumo.models import (
    IntentDraft,
    PaymentRequest,
    PipelineResult,
    PolicyContext,
    ScanResult,
    TxArgs,
    TxPlan,
)
from lumo.policy import engine
from lumo.security import injection

STROOP = 10_000_000

SIGNER_SUPPLIER_NOT_ALLOWED = "SIGNER_SUPPLIER_NOT_ALLOWED"
SIGNER_OVER_CAP = "SIGNER_OVER_CAP"
ATTESTATION_MISSING = "ATTESTATION_MISSING"
KOFN_UNMET = "KOFN_UNMET"
COSIGN_REQUIRED = "COSIGN_REQUIRED"
POC_RECEIPT_INVALID = "POC_RECEIPT_INVALID"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"

_AMOUNT_TOKEN_RE = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")
# A human-formatted currency amount: a US-grouped number with an optional
# trailing currency code/symbol ("1,250.00 USDC"). Anchored on both ends so it
# never salvages scientific notation ("1E9999") or an embedded letter run into a
# number — those must stay unparseable and fail closed.
_HUMAN_AMOUNT_RE = re.compile(r"\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*[A-Za-z$€£¥]*\s*")


class GuardRefused(Exception):
    def __init__(self, codes: list[str]):
        super().__init__(f"blocked by guard chain: {', '.join(codes)}")
        self.codes = codes


@dataclass
class GuardResult:
    outcome: str
    codes: list[str] = field(default_factory=list)
    reason: str = ""


PASS = GuardResult("pass")


@dataclass
class GuardContext:
    stage: str
    config: Config
    repo: Repo
    request: PaymentRequest | None = None
    policy: PolicyContext | None = None
    supplier_addresses: frozenset[str] = frozenset()
    cosign_token: str | None = None
    compute_receipt: dict | None = None
    intent: sqlite3.Row | None = None
    invoice_text: str = ""


class Guard:
    stage = "propose"

    def __init__(self, enabled: bool):
        self.enabled = enabled


class InjectionGuard(Guard):
    def check(self, ctx: GuardContext) -> GuardResult:
        if ctx.request.injection_flags:
            return GuardResult(
                "refuse", [engine.INJECTION_SUSPECTED], "injection heuristics flagged invoice"
            )
        return PASS


def _amount_matches_text(amount_stroops: int, text: str) -> bool:
    target = Decimal(amount_stroops) / STROOP
    for token in _AMOUNT_TOKEN_RE.findall(text):
        try:
            value = Decimal(token.replace(",", ""))
        except InvalidOperation:
            continue
        if value == target:
            return True
    return False


class AmountCrossCheckGuard(Guard):
    def check(self, ctx: GuardContext) -> GuardResult:
        amount = ctx.request.amount_stroops
        if amount is None:
            # Unparseable / non-finite amount: refuse here (independent of the
            # policy engine) so a None amount never reaches tx-plan building and
            # crashes it.
            return GuardResult(
                "refuse", [engine.INVALID_AMOUNT], "amount could not be parsed"
            )
        if _amount_matches_text(amount, ctx.invoice_text):
            return PASS
        return GuardResult(
            "refuse", [AMOUNT_MISMATCH], "extracted amount not found in raw invoice text"
        )


class PolicyEngineGuard(Guard):
    def check(self, ctx: GuardContext) -> GuardResult:
        evaluation = engine.evaluate(ctx.request, ctx.policy)
        if evaluation.allowed:
            return PASS
        return GuardResult("refuse", evaluation.codes, "policy engine refused")


class PolicySignerGuard(Guard):
    def check(self, ctx: GuardContext) -> GuardResult:
        codes = []
        req = ctx.request
        if req.registry_address is None or req.registry_address not in ctx.supplier_addresses:
            codes.append(SIGNER_SUPPLIER_NOT_ALLOWED)
        if req.amount_stroops is not None and req.amount_stroops > ctx.policy.cap_per_tx:
            codes.append(SIGNER_OVER_CAP)
        if codes:
            return GuardResult("refuse", codes, "policy-signer allowlist mirror refused")
        return PASS


def _shipped_oracles(ctx: GuardContext) -> set[str]:
    return {
        row["oracle_address"]
        for row in ctx.repo.attestations(ctx.intent["id"])
        if row["kind"] == "Shipped" and row["request_hash"] == ctx.intent["request_hash"]
    }


class AttestationGuard(Guard):
    stage = "release"

    def check(self, ctx: GuardContext) -> GuardResult:
        if _shipped_oracles(ctx):
            return PASS
        return GuardResult("refuse", [ATTESTATION_MISSING], "no Shipped attestation recorded")


class KofNOracleGuard(Guard):
    stage = "release"

    def __init__(self, enabled: bool, k: int):
        super().__init__(enabled)
        self.k = k

    def check(self, ctx: GuardContext) -> GuardResult:
        oracles = _shipped_oracles(ctx)
        if len(oracles) >= self.k:
            return PASS
        return GuardResult(
            "refuse", [KOFN_UNMET], f"{len(oracles)}/{self.k} distinct oracle attestations"
        )


class HumanCosignGuard(Guard):
    def __init__(self, enabled: bool, threshold: int):
        super().__init__(enabled)
        self.threshold = threshold

    def check(self, ctx: GuardContext) -> GuardResult:
        amount = ctx.request.amount_stroops
        if amount is not None and amount > self.threshold and not ctx.cosign_token:
            return GuardResult(
                "hold", [COSIGN_REQUIRED], f"amount exceeds cosign threshold {self.threshold}"
            )
        return PASS


class ProofOfComputeGuard(Guard):
    def check(self, ctx: GuardContext) -> GuardResult:
        receipt = ctx.compute_receipt
        if receipt and receipt.get("digest") == hashlib.sha256(
            str(receipt.get("payload", "")).encode()
        ).hexdigest():
            return PASS
        return GuardResult("refuse", [POC_RECEIPT_INVALID], "missing or invalid compute receipt")


def build_guards(config: Config) -> list[Guard]:
    return [
        InjectionGuard(config.injection_scan),
        PolicyEngineGuard(config.policy_engine),
        PolicySignerGuard(config.policy_signer),
        AttestationGuard(config.require_attestation),
        KofNOracleGuard(config.k_of_n > 1, config.k_of_n),
        HumanCosignGuard(config.human_cosign_threshold > 0, config.human_cosign_threshold),
        ProofOfComputeGuard(config.proof_of_compute),
    ]


def run_guards(guards: list[Guard], ctx: GuardContext) -> tuple[str, list[str]]:
    codes: list[str] = []
    refused = held = False
    for guard in guards:
        if not guard.enabled or guard.stage != ctx.stage:
            continue
        result = guard.check(ctx)
        if result.outcome != "pass":
            ctx.repo.emit(
                "guard.tripped",
                name=type(guard).__name__,
                outcome=result.outcome,
                codes=result.codes,
            )
            if isinstance(guard, InjectionGuard):
                ctx.repo.emit("injection.blocked", codes=result.codes)
        if result.outcome == "refuse":
            refused = True
        elif result.outcome == "hold":
            held = True
        codes.extend(c for c in result.codes if c not in codes)
    if refused:
        return "refuse", codes
    if held:
        return "hold", codes
    return "pass", [engine.OK]


def release_check(repo: Repo, config: Config, intent_row: sqlite3.Row) -> None:
    ctx = GuardContext(stage="release", config=config, repo=repo, intent=intent_row)
    verdict, codes = run_guards(build_guards(config), ctx)
    if verdict != "pass":
        raise GuardRefused(codes)


def _normalize_amount(amount: str) -> str | None:
    # Drop a trailing currency word/symbol and thousands separators a real
    # extractor tends to include ("1,250.00 USDC" -> "1250.00"). Returns None
    # unless the whole string is exactly one clean number + optional currency.
    match = _HUMAN_AMOUNT_RE.fullmatch(amount)
    return match.group(1).replace(",", "") if match else None


def to_stroops(amount: str | None) -> int | None:
    if amount is None:
        return None
    # Try the raw string first (so "1E9999..." still overflows -> refuse, and a
    # clean "1250.00" is unchanged), then a currency-stripped fallback for the
    # human-formatted amounts a real LLM returns.
    for candidate in (amount, _normalize_amount(amount)):
        if candidate is None:
            continue
        try:
            value = Decimal(candidate)
        except (InvalidOperation, ArithmeticError):
            continue
        if not value.is_finite():
            return None
        try:
            stroops = value * STROOP
            if stroops != stroops.to_integral_value():
                return None
            return int(stroops)
        except (InvalidOperation, OverflowError, ArithmeticError):
            return None
    return None


def run(
    invoice_text: str,
    repo: Repo,
    provider: ExtractionProvider,
    config: Config,
    cosign_token: str | None = None,
    compute_receipt: dict | None = None,
) -> PipelineResult:
    if config.injection_scan:
        scan = injection.scan(invoice_text)
    else:
        scan = ScanResult(flags=[], normalized_text=invoice_text, addresses=[])
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
    policy_ctx = PolicyContext(
        cap_per_tx=int(rules["cap_per_tx"]),
        cap_daily=int(rules["cap_daily"]),
        prior_intents=repo.intents_today(),
        known_request_hashes=repo.known_request_hashes(),
    )
    ctx = GuardContext(
        stage="propose",
        config=config,
        repo=repo,
        request=req,
        policy=policy_ctx,
        supplier_addresses=frozenset(repo.supplier_addresses()),
        cosign_token=cosign_token,
        compute_receipt=compute_receipt,
        invoice_text=scan.normalized_text,
    )
    # The amount integrity check (cross-check vs. the raw text + reject an
    # unparseable amount) is a deterministic anti-injection guard: it runs
    # ALWAYS, not only when the policy engine is enabled.
    guards = build_guards(config) + [AmountCrossCheckGuard(True)]
    verdict, codes = run_guards(guards, ctx)

    if verdict == "refuse":
        repo.record_decision(
            decision="refused",
            codes=codes,
            request_hash=rhash,
            detail=extracted.invoice_ref,
        )
        return PipelineResult(
            decision="refused",
            codes=codes,
            flags=scan.flags,
            request_hash=rhash,
        )

    draft = IntentDraft(
        supplier_id=supplier["id"],
        amount=amount_stroops,
        token=rules["token_address"],
        deadline=deadline,
        invoice_ref=extracted.invoice_ref,
        request_hash=rhash,
    )

    if verdict == "hold":
        outcome = repo.record_decision(
            decision="held", codes=codes, request_hash=rhash, intent=draft
        )
        return PipelineResult(
            decision="held",
            codes=codes,
            flags=scan.flags,
            request_hash=rhash,
            intent_id=outcome.intent_id,
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
        codes=codes,
        request_hash=rhash,
        intent=draft,
    )
    return PipelineResult(
        decision="proposed",
        codes=codes,
        flags=scan.flags,
        request_hash=rhash,
        tx_plan=tx_plan,
        intent_id=outcome.intent_id,
    )
