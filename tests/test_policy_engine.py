from lumo.models import PaymentRequest, PolicyContext, PriorIntent
from lumo.policy import engine

SUPPLIER = "G" + "B" * 55


def make_request(**overrides):
    fields = dict(
        supplier_name="CV Batik Nusantara",
        registry_address=SUPPLIER,
        invoice_address=SUPPLIER,
        amount_stroops=1_000,
        request_hash="a" * 64,
        injection_flags=[],
    )
    fields.update(overrides)
    return PaymentRequest(**fields)


def make_context(**overrides):
    fields = dict(cap_per_tx=2_000, cap_daily=5_000)
    fields.update(overrides)
    return PolicyContext(**fields)


def test_in_policy_allows():
    ev = engine.evaluate(make_request(), make_context())
    assert ev.allowed
    assert ev.codes == [engine.OK]


def test_tx_cap_boundary_exact_amount_passes():
    ev = engine.evaluate(make_request(amount_stroops=2_000), make_context())
    assert ev.allowed


def test_tx_cap_boundary_plus_one_refuses():
    ev = engine.evaluate(make_request(amount_stroops=2_001), make_context())
    assert not ev.allowed
    assert engine.OVER_TX_CAP in ev.codes


def test_unknown_supplier_refuses():
    ev = engine.evaluate(
        make_request(registry_address=None, invoice_address=None), make_context()
    )
    assert not ev.allowed
    assert engine.UNKNOWN_SUPPLIER in ev.codes


def test_address_mismatch_refuses():
    ev = engine.evaluate(
        make_request(invoice_address="G" + "A" * 55), make_context()
    )
    assert not ev.allowed
    assert engine.ADDRESS_MISMATCH in ev.codes


def test_duplicate_request_refuses():
    ev = engine.evaluate(
        make_request(), make_context(known_request_hashes={"a" * 64})
    )
    assert not ev.allowed
    assert engine.DUPLICATE_REQUEST in ev.codes


def test_invalid_amount_refuses():
    for amount in (None, 0, -5):
        ev = engine.evaluate(make_request(amount_stroops=amount), make_context())
        assert not ev.allowed
        assert engine.INVALID_AMOUNT in ev.codes


def test_injection_flags_refuse():
    ev = engine.evaluate(
        make_request(injection_flags=["OVERRIDE_PHRASE"]), make_context()
    )
    assert not ev.allowed
    assert engine.INJECTION_SUSPECTED in ev.codes


def test_daily_cap_accumulation_refuses_third_in_policy_tx():
    priors = [
        PriorIntent(amount=2_000, status="proposed"),
        PriorIntent(amount=2_000, status="escrowed"),
    ]
    ev = engine.evaluate(
        make_request(amount_stroops=1_500),
        make_context(prior_intents=priors),
    )
    assert not ev.allowed
    assert ev.codes == [engine.OVER_DAILY_CAP]


def test_daily_cap_ignores_reverted_priors():
    priors = [
        PriorIntent(amount=2_000, status="reverted"),
        PriorIntent(amount=2_000, status="proposed"),
    ]
    ev = engine.evaluate(
        make_request(amount_stroops=1_500),
        make_context(prior_intents=priors),
    )
    assert ev.allowed


def test_daily_cap_boundary_exact_total_passes():
    priors = [PriorIntent(amount=3_000, status="escrowed")]
    ev = engine.evaluate(
        make_request(amount_stroops=2_000),
        make_context(prior_intents=priors),
    )
    assert ev.allowed
    ev = engine.evaluate(
        make_request(amount_stroops=2_000),
        make_context(prior_intents=[PriorIntent(amount=3_001, status="escrowed")]),
    )
    assert not ev.allowed
    assert engine.OVER_DAILY_CAP in ev.codes


def test_code_set_is_exactly_eight():
    assert len(engine.CODES) == 8
