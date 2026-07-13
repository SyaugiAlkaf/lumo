import pytest

from amanah import pipeline
from amanah.llm.mock import COMPROMISED, MockProvider
from amanah.policy import engine
from amanah.security import injection

from conftest import ATTACKER_ADDRESS, load_invoice

INJECT_FIXTURES = [
    "inject_override.txt",
    "inject_zero_width.txt",
    "inject_homoglyph.txt",
    "inject_role_tag.txt",
    "inject_address_swap.txt",
]


@pytest.mark.parametrize("fixture", INJECT_FIXTURES)
def test_t8_injected_invoice_refused_and_flagged(fixture, repo, config):
    result = pipeline.run(load_invoice(fixture), repo, MockProvider(), config)
    assert result.decision == "refused"
    assert engine.INJECTION_SUSPECTED in result.codes
    assert result.flags
    assert result.tx_plan is None
    assert repo.intent_count() == 0


def test_t8_compromised_llm_still_cannot_move_money(repo, config):
    text = load_invoice("inject_address_swap.txt")
    provider = MockProvider(mode=COMPROMISED)
    extracted = provider.extract(text)
    assert extracted.payment_address == ATTACKER_ADDRESS

    result = pipeline.run(text, repo, provider, config)
    assert result.decision == "refused"
    assert engine.INJECTION_SUSPECTED in result.codes
    assert engine.ADDRESS_MISMATCH in result.codes
    assert result.tx_plan is None
    assert repo.intent_count() == 0
    decisions = repo.decision_rows()
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "refused"


def test_t8_clean_fixture_zero_false_positives(repo, config):
    text = load_invoice("clean_control.txt")
    assert injection.scan(text).flags == []
    result = pipeline.run(text, repo, MockProvider(), config)
    assert result.decision == "proposed"
    assert engine.INJECTION_SUSPECTED not in result.codes
