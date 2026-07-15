"""Regression tests for the confirmed findings of the feature audit."""
import pytest

from lumo import flow, mcp, pipeline
from lumo.chain import ChainSubmittedUnconfirmed
from lumo.chain.mock_chain import MockChainAdapter
from lumo.config import Config
from lumo.db.seed import TOKEN_ADDRESS
from lumo.models import ExtractedInvoice, IntentDraft
from lumo.monitor.webhooks import WebhookDispatcher, WebhookURLError

SUPPLIER = "GBATIKYLX7IEOR2YJMNTPMKZCIWXT2PAX635P7ZDGB3DTLQLS263VNS3"


# ---- Finding 7: amount inflation via a decoy number planted in free text ----
class _CompromisedProvider:
    def __init__(self, amount):
        self._amount = amount

    def extract(self, invoice_text):
        return ExtractedInvoice(
            invoice_ref="INV-9", supplier_name="CV Batik Nusantara",
            payment_address=SUPPLIER, amount=self._amount, currency="USDC",
        )


def test_inflated_amount_matching_a_decoy_not_the_labeled_field_is_refused(repo, config):
    # Payable is 1,250 (labeled "Amount due"); attacker plants "2000" in a memo and
    # a compromised extractor returns 2000. Cross-check must bind to the label.
    text = (
        f"INVOICE INV-9\nFrom: CV Batik Nusantara\nPayment address: {SUPPLIER}\n"
        f"Amount due: 1,250.00 USDC\nMemo: reorder ref 2000 units\n"
    )
    result = pipeline.run(text, repo, _CompromisedProvider("2000"), config)
    assert result.decision == "refused"
    assert pipeline.AMOUNT_MISMATCH in result.codes


def test_labeled_amount_still_matches_the_correct_extraction(repo, config):
    text = (
        f"INVOICE INV-1\nFrom: CV Batik Nusantara\nPayment address: {SUPPLIER}\n"
        f"Amount due: 1,250.00 USDC\n"
    )
    result = pipeline.run(text, repo, _CompromisedProvider("1250.00"), config)
    assert pipeline.AMOUNT_MISMATCH not in result.codes


def test_unlabeled_invoice_falls_back_to_presence(repo, config):
    # No English/Indonesian payable label -> best-effort presence check still settles.
    text = f"Faktur\nCV Batik Nusantara\n{SUPPLIER}\nHarga 1250.00 USDC\n"
    result = pipeline.run(text, repo, _CompromisedProvider("1250.00"), config)
    assert pipeline.AMOUNT_MISMATCH not in result.codes


# ---- Finding 3: MCP tools/call with non-dict params must not crash ----
@pytest.mark.parametrize("bad", ["a string", None, [1, 2], 5])
def test_mcp_tools_call_non_dict_params_returns_error(bad):
    out = mcp.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": bad}, client=None
    )
    assert out["error"]["code"] == -32602


# ---- Findings 8/12/13: config validation ----
def test_config_rejects_nonpositive_deadline():
    with pytest.raises(ValueError):
        Config(deadline_secs=0)


def test_config_rejects_unknown_mock_mode():
    with pytest.raises(ValueError):
        Config(mock_mode="bogus")


def test_config_strips_whitespace_smart_account():
    assert Config(sme_smart_account="   ").sme_smart_account == ""


# ---- Findings 1/5: a submitted-but-unconfirmed create_intent must not release
#      the claim (a retry would double-escrow) ----
class _UnconfirmedChain(MockChainAdapter):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def create_intent(self, **kwargs):
        self.calls += 1
        raise ChainSubmittedUnconfirmed("abc123deadbeef", "poll timeout")


def _proposed(repo):
    supplier = repo.supplier_by_name("CV Batik Nusantara")
    return repo.record_decision(
        decision="proposed", codes=["OK"], request_hash="d" * 64,
        intent=IntentDraft(
            supplier_id=supplier["id"], amount=1_000_000, token=TOKEN_ADDRESS,
            deadline=1_800_000_000, invoice_ref="X", request_hash="d" * 64,
        ),
    ).intent_id


def test_unconfirmed_submit_keeps_claim_and_retry_never_double_escrows(repo, config):
    chain = _UnconfirmedChain()
    intent_id = _proposed(repo)

    with pytest.raises(ChainSubmittedUnconfirmed):
        flow.execute(repo, chain, intent_id, "lumo-sme", config)

    # Claim kept (escrowed), tx hash recorded for reconciliation.
    assert repo.intent(intent_id)["status"] == "escrowed"
    assert [t["action"] for t in repo.chain_txs(intent_id)] == ["create_intent"]

    # Retry is a no-op — never a second on-chain create_intent.
    assert flow.execute(repo, chain, intent_id, "lumo-sme", config) is None
    assert chain.calls == 1


# ---- Finding 14: webhook registration runs SSRF validation ----
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data",
    "http://127.0.0.1/hook",
    "ftp://example.com/x",
])
def test_webhook_register_rejects_disallowed_targets(url):
    dispatcher = WebhookDispatcher([], sink=lambda *a, **k: None)
    with pytest.raises(WebhookURLError):
        dispatcher.register(url)
