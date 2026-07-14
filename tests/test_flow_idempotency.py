import pytest

from lumo import flow
from lumo.chain import ChainError, mapper
from lumo.chain.mock_chain import ESCROW_VAULT, MockChainAdapter
from lumo.db.seed import SME_ADDRESS, TOKEN_ADDRESS
from lumo.models import IntentDraft

AMOUNT = 12_500_000_000


class CountingChain(MockChainAdapter):
    def __init__(self):
        super().__init__()
        self.create_calls = 0

    def create_intent(self, **kwargs):
        self.create_calls += 1
        return super().create_intent(**kwargs)


class FlakyConfirmChain(CountingChain):
    """create_intent succeeds on-chain but the first confirm read fails —
    exactly the window where a naive release-on-failure would let a retry
    double-escrow."""

    def __init__(self):
        super().__init__()
        self.fail_confirms = 1

    def get_status(self, chain_intent_id):
        if self.fail_confirms:
            self.fail_confirms -= 1
            return None
        return super().get_status(chain_intent_id)


def proposed_intent(repo, ref="INV-IDEM"):
    supplier = repo.supplier_by_name("CV Batik Nusantara")
    outcome = repo.record_decision(
        decision="proposed",
        codes=["OK"],
        request_hash=f"{ref:0<64}",
        intent=IntentDraft(
            supplier_id=supplier["id"],
            amount=AMOUNT,
            token=TOKEN_ADDRESS,
            deadline=1_800_000_000,
            invoice_ref=ref,
            request_hash=f"{ref:0<64}",
        ),
    )
    return outcome.intent_id, supplier["address"]


def funded(chain):
    chain.fund(TOKEN_ADDRESS, SME_ADDRESS, 10 * AMOUNT)
    return chain


def test_retried_execute_escrows_exactly_once(repo, config):
    chain = funded(CountingChain())
    intent_id, _ = proposed_intent(repo)

    assert flow.execute(repo, chain, intent_id, "sme", config) == 1
    # A retry (same proposed intent) must be a no-op, never a second submit.
    assert flow.execute(repo, chain, intent_id, "sme", config) is None

    assert chain.create_calls == 1
    assert list(chain.intents) == [1]
    assert chain.balance(TOKEN_ADDRESS, ESCROW_VAULT) == AMOUNT
    row = repo.intent(intent_id)
    assert row["status"] == "escrowed"
    assert row["chain_intent_id"] == 1
    creates = [t for t in repo.chain_txs(intent_id) if t["action"] == "create_intent"]
    assert len(creates) == 1


def test_failed_confirm_then_retry_never_double_escrows(repo, config):
    chain = funded(FlakyConfirmChain())
    intent_id, _ = proposed_intent(repo)

    # First run: the on-chain escrow is created, but the confirm read fails.
    with pytest.raises(ChainError):
        flow.execute(repo, chain, intent_id, "sme", config)

    # The escrow exists and is RECORDED; the claim is NOT released (a retry must
    # reconcile against this escrow, not create a second one).
    assert chain.create_calls == 1
    assert list(chain.intents) == [1]
    assert chain.balance(TOKEN_ADDRESS, ESCROW_VAULT) == AMOUNT
    row = repo.intent(intent_id)
    assert row["status"] == "escrowed"
    assert row["chain_intent_id"] == 1
    assert [t["action"] for t in repo.chain_txs(intent_id)] == ["create_intent"]

    # The retry does NOT create a second escrow — this is the core money-safety
    # property (the escrow contract has no request_hash idempotency of its own).
    assert flow.execute(repo, chain, intent_id, "sme", config) is None
    assert chain.create_calls == 1
    assert list(chain.intents) == [1]
    assert chain.balance(TOKEN_ADDRESS, ESCROW_VAULT) == AMOUNT


def test_sync_status_persists_funded_intent_to_escrowed(repo):
    chain = funded(MockChainAdapter())
    intent_id, supplier_address = proposed_intent(repo)
    result = chain.create_intent(
        sme=SME_ADDRESS,
        supplier=supplier_address,
        token=TOKEN_ADDRESS,
        amount=AMOUNT,
        request_hash=repo.intent(intent_id)["request_hash"],
        deadline=1_800_000_000,
    )
    repo.set_chain_intent(intent_id, int(result.value))

    # Crash-recovery: chain is Funded but the local row lagged at 'proposed'.
    assert mapper.sync_status(repo, chain, intent_id) == "escrowed"
    assert repo.intent(intent_id)["status"] == "escrowed"
    approved = [d for d in repo.decision_rows() if d["decision"] == "approved"]
    assert len(approved) == 1
    assert approved[0]["intent_id"] == intent_id
