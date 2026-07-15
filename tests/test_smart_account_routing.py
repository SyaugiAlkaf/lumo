from dataclasses import replace

from lumo import flow
from lumo.chain.adapter import SorobanAdapter
from lumo.chain.mock_chain import MockChainAdapter
from lumo.chain.soroban_client import InvokeResult
from lumo.db.seed import SME_ADDRESS, TOKEN_ADDRESS
from lumo.models import IntentDraft

SMART = "CD2EIG3V4TBGHSGLZYCIZRHVFVQFUA3NL2KG7SZFF3SIEGL7MMV4PF5L"


class RecordingClient:
    def __init__(self):
        self.calls = []

    def create_intent(self, **kwargs):
        self.calls.append(kwargs)
        return InvokeResult(value=7, tx_hash="deadbeef")


def _args():
    return dict(
        sme="X", supplier="GSUP", token="CT", amount=100, request_hash="ab" * 32, deadline=1
    )


def test_adapter_routes_create_intent_to_smart_account_when_present():
    cli, smart = RecordingClient(), RecordingClient()
    adapter = SorobanAdapter(cli, smart_account_client=smart)

    result = adapter.create_intent(**_args())

    assert result.value == 7
    assert len(smart.calls) == 1
    assert cli.calls == []


def test_adapter_uses_cli_client_when_no_smart_account():
    cli = RecordingClient()
    adapter = SorobanAdapter(cli)

    adapter.create_intent(**_args())

    assert len(cli.calls) == 1


class SmeRecordingChain(MockChainAdapter):
    def __init__(self):
        super().__init__()
        self.seen_sme = None

    def create_intent(self, **kwargs):
        self.seen_sme = kwargs["sme"]
        return super().create_intent(**kwargs)


def _proposed(repo):
    supplier = repo.supplier_by_name("CV Batik Nusantara")
    outcome = repo.record_decision(
        decision="proposed",
        codes=["OK"],
        request_hash="c" * 64,
        intent=IntentDraft(
            supplier_id=supplier["id"],
            amount=1_000_000,
            token=TOKEN_ADDRESS,
            deadline=1_800_000_000,
            invoice_ref="INV-SA",
            request_hash="c" * 64,
        ),
    )
    return outcome.intent_id


def test_flow_execute_uses_smart_account_as_sme(repo, config):
    chain = SmeRecordingChain()
    chain.fund(TOKEN_ADDRESS, SMART, 10_000_000)
    intent_id = _proposed(repo)

    flow.execute(repo, chain, intent_id, "lumo-sme", replace(config, sme_smart_account=SMART))

    assert chain.seen_sme == SMART


def test_flow_execute_defaults_to_rules_sme_address_when_unset(repo, config):
    chain = SmeRecordingChain()
    chain.fund(TOKEN_ADDRESS, SME_ADDRESS, 10_000_000)
    intent_id = _proposed(repo)

    flow.execute(repo, chain, intent_id, "lumo-sme", config)

    assert chain.seen_sme == SME_ADDRESS
