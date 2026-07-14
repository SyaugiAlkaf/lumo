from lumo.models import Evaluation, PaymentRequest, PolicyContext

OK = "OK"
INJECTION_SUSPECTED = "INJECTION_SUSPECTED"
INVALID_AMOUNT = "INVALID_AMOUNT"
UNKNOWN_SUPPLIER = "UNKNOWN_SUPPLIER"
ADDRESS_MISMATCH = "ADDRESS_MISMATCH"
DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
OVER_TX_CAP = "OVER_TX_CAP"
OVER_DAILY_CAP = "OVER_DAILY_CAP"

CODES = (
    OK,
    INJECTION_SUSPECTED,
    INVALID_AMOUNT,
    UNKNOWN_SUPPLIER,
    ADDRESS_MISMATCH,
    DUPLICATE_REQUEST,
    OVER_TX_CAP,
    OVER_DAILY_CAP,
)

COUNTED_STATUSES = ("proposed", "escrowed", "released")


def evaluate(req: PaymentRequest, ctx: PolicyContext) -> Evaluation:
    codes = []
    if req.injection_flags:
        codes.append(INJECTION_SUSPECTED)
    if req.amount_stroops is None or req.amount_stroops <= 0:
        codes.append(INVALID_AMOUNT)
    if req.registry_address is None:
        codes.append(UNKNOWN_SUPPLIER)
    if (
        req.invoice_address is not None
        and req.registry_address is not None
        and req.invoice_address != req.registry_address
    ):
        codes.append(ADDRESS_MISMATCH)
    if req.request_hash in ctx.known_request_hashes:
        codes.append(DUPLICATE_REQUEST)
    if req.amount_stroops is not None and req.amount_stroops > 0:
        if req.amount_stroops > ctx.cap_per_tx:
            codes.append(OVER_TX_CAP)
        committed = sum(
            i.amount for i in ctx.prior_intents if i.status in COUNTED_STATUSES
        )
        if committed + req.amount_stroops > ctx.cap_daily:
            codes.append(OVER_DAILY_CAP)
    if codes:
        return Evaluation(allowed=False, codes=codes)
    return Evaluation(allowed=True, codes=[OK])
