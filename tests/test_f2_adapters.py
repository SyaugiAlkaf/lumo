import pytest

from lumo import flow, pipeline
from lumo.anchor.adapter import (
    AnchorAdapter,
    GCashAnchor,
    MockAnchor,
    PdaxAnchor,
    build_anchor,
)
from lumo.chain import ChainError
from lumo.chain.adapter import (
    ChainAdapter,
    EvmAdapter,
    SorobanAdapter,
    build_chain_adapter,
)
from lumo.chain.mock_chain import MockChainAdapter
from lumo.chain.soroban_client import SorobanClient
from lumo.config import Config
from lumo.db.seed import SME_ADDRESS, SUPPLIERS, TOKEN_ADDRESS
from lumo.llm.mock import MockProvider
from lumo.oracle.adapter import (
    AttestationSource,
    LocalSignerSet,
    ShipmentApiOracle,
    build_oracle,
)

from conftest import load_invoice

AMOUNT = 12_500_000_000
FUNDING = 4 * AMOUNT
SUPPLIER_ADDRESS = dict(SUPPLIERS)["CV Batik Nusantara"]

ORACLE_A = "GORACLEA" + "A" * 48
ORACLE_B = "GORACLEB" + "B" * 48
ORACLE_C = "GORACLEC" + "C" * 48

CHAIN_METHODS = ("create_intent", "attest", "release", "refund", "get_status", "deploy")


def funded_mock_chain():
    chain = MockChainAdapter()
    chain.deploy()
    chain.fund(TOKEN_ADDRESS, SME_ADDRESS, FUNDING)
    return chain


def escrow_via_pipeline(repo, config, chain):
    result = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    assert result.decision == "proposed"
    chain_id = flow.execute(repo, chain, result.intent_id, "sme", config)
    return result.intent_id, chain_id


def test_chain_adapters_satisfy_protocol():
    adapters = [
        SorobanAdapter(SorobanClient("CESCROW")),
        MockChainAdapter(),
        EvmAdapter(),
    ]
    for adapter in adapters:
        assert isinstance(adapter, ChainAdapter)
        for method in CHAIN_METHODS:
            assert callable(getattr(adapter, method))


def test_anchor_adapters_satisfy_protocol():
    for adapter in (MockAnchor(), GCashAnchor(), PdaxAnchor()):
        assert isinstance(adapter, AnchorAdapter)


def test_oracle_adapters_satisfy_protocol():
    for adapter in (LocalSignerSet([ORACLE_A]), ShipmentApiOracle()):
        assert isinstance(adapter, AttestationSource)


def test_evm_stub_raises_roadmap_not_implemented():
    evm = EvmAdapter()
    with pytest.raises(NotImplementedError, match="roadmap: EVM/x402"):
        evm.deploy()
    with pytest.raises(NotImplementedError, match="roadmap: EVM/x402"):
        evm.create_intent(
            sme="0xSME",
            supplier="0xSUP",
            token="0xUSDC",
            amount=1,
            request_hash="a" * 64,
            deadline=1,
        )
    with pytest.raises(NotImplementedError, match="roadmap: EVM/x402"):
        evm.attest(1, "0xORACLE", "Shipped")
    with pytest.raises(NotImplementedError, match="roadmap: EVM/x402"):
        evm.release(1)
    with pytest.raises(NotImplementedError, match="roadmap: EVM/x402"):
        evm.refund(1)
    with pytest.raises(NotImplementedError, match="roadmap: EVM/x402"):
        evm.get_status(1)


def test_anchor_and_oracle_stubs_raise_roadmap(repo):
    with pytest.raises(NotImplementedError, match="roadmap"):
        GCashAnchor().cash_out(repo, "01J")
    with pytest.raises(NotImplementedError, match="roadmap"):
        PdaxAnchor().cash_out(repo, "01J")
    with pytest.raises(NotImplementedError, match="roadmap"):
        ShipmentApiOracle().submit(repo, "01J", "Shipped", "a" * 64)
    with pytest.raises(NotImplementedError, match="roadmap"):
        ShipmentApiOracle().collect(repo, "01J")


def test_defaults_select_current_stack():
    cfg = Config()
    assert cfg.chain_adapter == "soroban"
    assert cfg.anchor_adapter == "mock"
    assert cfg.oracle_adapter == ""
    assert isinstance(build_chain_adapter(cfg), SorobanAdapter)
    assert isinstance(build_anchor(cfg), MockAnchor)
    assert build_oracle(cfg) is None


def test_build_by_config_selects_adapter():
    assert isinstance(build_chain_adapter(Config(chain_adapter="mock")), MockChainAdapter)
    assert isinstance(build_chain_adapter(Config(chain_adapter="evm")), EvmAdapter)
    assert isinstance(build_anchor(Config(anchor_adapter="gcash")), GCashAnchor)
    assert isinstance(build_anchor(Config(anchor_adapter="pdax")), PdaxAnchor)
    oracle = build_oracle(
        Config(oracle_adapter="local", oracle_signers=f"{ORACLE_A}, {ORACLE_B}")
    )
    assert isinstance(oracle, LocalSignerSet)
    assert oracle.signers == [ORACLE_A, ORACLE_B]
    single = build_oracle(Config(oracle_adapter="local", oracle_address=ORACLE_C))
    assert single.signers == [ORACLE_C]
    assert isinstance(build_oracle(Config(oracle_adapter="shipment_api")), ShipmentApiOracle)
    with pytest.raises(ValueError):
        build_chain_adapter(Config(chain_adapter="cosmos"))
    with pytest.raises(ValueError):
        build_anchor(Config(anchor_adapter="wise"))
    with pytest.raises(ValueError):
        build_oracle(Config(oracle_adapter="carrier-pigeon"))


def test_mock_chain_deploy_is_deterministic():
    a, b = MockChainAdapter(), MockChainAdapter()
    assert a.deploy() == b.deploy()
    assert a.deploy().startswith("C")


def test_full_flow_release_path_on_mock_chain(repo, config):
    chain = funded_mock_chain()
    intent_id, chain_id = escrow_via_pipeline(repo, config, chain)

    assert repo.intent(intent_id)["status"] == "escrowed"
    assert chain.balance(TOKEN_ADDRESS, SME_ADDRESS) == FUNDING - AMOUNT
    assert chain.balance(TOKEN_ADDRESS, SUPPLIER_ADDRESS) == 0

    with pytest.raises(ChainError):
        flow.release(repo, chain, intent_id, "sme", config)
    assert repo.intent(intent_id)["status"] == "escrowed"

    flow.attest(repo, chain, intent_id, "Shipped", ORACLE_A, "oracle")
    assert flow.release(repo, chain, intent_id, "sme", config) == "released"

    assert repo.intent(intent_id)["status"] == "released"
    assert chain.balance(TOKEN_ADDRESS, SUPPLIER_ADDRESS) == AMOUNT
    assert chain.balance(TOKEN_ADDRESS, SME_ADDRESS) == FUNDING - AMOUNT

    payouts = repo.anchor_payouts()
    assert len(payouts) == 1
    assert payouts[0]["intent_id"] == intent_id
    assert payouts[0]["ref"].startswith("MOCK-")
    assert payouts[0]["amount"] == str(AMOUNT)

    actions = [t["action"] for t in repo.chain_txs(intent_id)]
    assert actions == ["create_intent", "attest_shipped", "release"]


def test_full_flow_refund_path_on_mock_chain(repo, config):
    chain = funded_mock_chain()
    intent_id, chain_id = escrow_via_pipeline(repo, config, chain)

    flow.attest(repo, chain, intent_id, "Failed", ORACLE_A, "oracle")
    assert flow.revert(repo, chain, intent_id, "sme") == "reverted"

    assert repo.intent(intent_id)["status"] == "reverted"
    assert chain.balance(TOKEN_ADDRESS, SME_ADDRESS) == FUNDING
    assert chain.balance(TOKEN_ADDRESS, SUPPLIER_ADDRESS) == 0
    reverted = [r for r in repo.decision_rows() if r["decision"] == "reverted"]
    assert len(reverted) == 1
    assert reverted[0]["intent_id"] == intent_id
    assert repo.anchor_payouts() == []


def test_mock_chain_shipped_beats_deadline():
    chain = funded_mock_chain()
    result = chain.create_intent(
        sme=SME_ADDRESS,
        supplier=SUPPLIER_ADDRESS,
        token=TOKEN_ADDRESS,
        amount=AMOUNT,
        request_hash="a" * 64,
        deadline=100,
    )
    chain_id = int(result.value)
    chain.attest(chain_id, ORACLE_A, "Shipped")
    chain.now = 200

    with pytest.raises(ChainError):
        chain.refund(chain_id)
    chain.release(chain_id)
    assert chain.get_status(chain_id)["status"] == "Released"


def test_mock_chain_attest_first_write_wins():
    chain = funded_mock_chain()
    result = chain.create_intent(
        sme=SME_ADDRESS,
        supplier=SUPPLIER_ADDRESS,
        token=TOKEN_ADDRESS,
        amount=AMOUNT,
        request_hash="a" * 64,
        deadline=100,
    )
    chain_id = int(result.value)
    chain.attest(chain_id, ORACLE_A, "Failed")
    chain.attest(chain_id, ORACLE_B, "Shipped")

    with pytest.raises(ChainError):
        chain.release(chain_id)
    chain.refund(chain_id)
    assert chain.get_status(chain_id)["status"] == "Refunded"


def test_mock_chain_deadline_refund_without_attestation():
    chain = funded_mock_chain()
    result = chain.create_intent(
        sme=SME_ADDRESS,
        supplier=SUPPLIER_ADDRESS,
        token=TOKEN_ADDRESS,
        amount=AMOUNT,
        request_hash="a" * 64,
        deadline=100,
    )
    chain_id = int(result.value)

    with pytest.raises(ChainError):
        chain.refund(chain_id)
    chain.now = 100
    chain.refund(chain_id)
    assert chain.balance(TOKEN_ADDRESS, SME_ADDRESS) == FUNDING


def test_local_signer_set_feeds_k_of_n_release_gate(repo, config):
    chain = funded_mock_chain()
    intent_id, chain_id = escrow_via_pipeline(repo, config, chain)
    cfg = Config(db_path=config.db_path, k_of_n=3)
    oracle = LocalSignerSet([ORACLE_A, ORACLE_B, ORACLE_C])

    flow.attest(repo, chain, intent_id, "Shipped", ORACLE_A, "oracle")
    with pytest.raises(pipeline.GuardRefused):
        flow.release(repo, chain, intent_id, "sme", cfg)

    flow.attest(repo, chain, intent_id, "Shipped", ORACLE_A, "oracle", oracle=oracle)
    assert len(oracle.collect(repo, intent_id)) == 3
    assert flow.release(repo, chain, intent_id, "sme", cfg) == "released"
