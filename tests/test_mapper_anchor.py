import pytest

from amanah.anchor import mock_anchor
from amanah.chain import mapper
from amanah.models import IntentDraft


class FakeClient:
    def __init__(self, chain_intent):
        self.chain_intent = chain_intent

    def get_status(self, chain_intent_id):
        return self.chain_intent


def proposed_intent(repo, ref="INV-1"):
    supplier = repo.supplier_by_name("CV Batik Nusantara")
    outcome = repo.record_decision(
        decision="proposed",
        codes=["OK"],
        request_hash=f"{ref:0<64}",
        intent=IntentDraft(
            supplier_id=supplier["id"],
            amount=12_500_000_000,
            token="CTOKEN",
            deadline=1782672147,
            invoice_ref=ref,
            request_hash=f"{ref:0<64}",
        ),
    )
    return outcome.intent_id


def escrowed_intent(repo, ref="INV-1"):
    intent_id = proposed_intent(repo, ref)
    repo.set_chain_intent(intent_id, 1)
    repo.record_decision(
        decision="approved",
        codes=["ESCROWED_ONCHAIN"],
        request_hash=f"{ref:0<64}",
        intent_id=intent_id,
    )
    return intent_id


def chain_row(status):
    return {"status": status, "request_hash": "aa" * 32}


def test_sync_released_written_only_from_chain_read(repo):
    intent_id = escrowed_intent(repo)
    assert mapper.sync_status(repo, FakeClient(chain_row("Released")), intent_id) == "released"
    assert repo.intent(intent_id)["status"] == "released"


def test_sync_refunded_writes_reverted_audit_row(repo):
    intent_id = escrowed_intent(repo)
    assert mapper.sync_status(repo, FakeClient(chain_row("Refunded")), intent_id) == "reverted"
    assert repo.intent(intent_id)["status"] == "reverted"
    reverted = [r for r in repo.decision_rows() if r["decision"] == "reverted"]
    assert len(reverted) == 1
    assert reverted[0]["intent_id"] == intent_id


def test_sync_funded_keeps_escrowed_and_missing_chain_row_never_promotes(repo):
    intent_id = escrowed_intent(repo)
    assert mapper.sync_status(repo, FakeClient(chain_row("Funded")), intent_id) == "escrowed"
    assert mapper.sync_status(repo, FakeClient(None), intent_id) == "escrowed"
    assert repo.intent(intent_id)["status"] == "escrowed"


def test_sync_before_chain_submit_is_noop(repo):
    intent_id = proposed_intent(repo)
    assert mapper.sync_status(repo, FakeClient(chain_row("Released")), intent_id) == "proposed"
    assert repo.intent(intent_id)["status"] == "proposed"


def test_cash_out_writes_mock_payout_with_matching_amount(repo):
    intent_id = escrowed_intent(repo)
    mapper.sync_status(repo, FakeClient(chain_row("Released")), intent_id)
    receipt = mock_anchor.cash_out(repo, intent_id)

    payouts = repo.anchor_payouts()
    assert len(payouts) == 1
    assert payouts[0]["intent_id"] == intent_id
    assert payouts[0]["ref"].startswith("MOCK-")
    assert len(payouts[0]["ref"]) == len("MOCK-") + 26
    assert payouts[0]["amount"] == "12500000000"
    assert receipt["transaction"]["id"] == payouts[0]["ref"]
    assert receipt["transaction"]["status"] == "completed"
    assert receipt["transaction"]["amount_out"] == "1250.00"


def test_cash_out_refuses_unreleased_intent(repo):
    intent_id = escrowed_intent(repo)
    with pytest.raises(ValueError):
        mock_anchor.cash_out(repo, intent_id)
    assert repo.anchor_payouts() == []
