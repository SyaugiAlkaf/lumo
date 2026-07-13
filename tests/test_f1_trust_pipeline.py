import hashlib
from types import SimpleNamespace

import pytest

from amanah import flow, pipeline
from amanah.config import Config
from amanah.llm.mock import MockProvider
from amanah.models import IntentDraft

from conftest import load_invoice

STROOP = pipeline.STROOP

ORACLE_A = "GORACLEA" + "A" * 48
ORACLE_B = "GORACLEB" + "B" * 48
ORACLE_C = "GORACLEC" + "C" * 48


class ExplodingClient:
    def __getattr__(self, name):
        raise AssertionError(f"chain call {name} during dry_run")


class FakeChainClient:
    def __init__(self, request_hash):
        self.request_hash = request_hash
        self.released = False

    def release(self, chain_intent_id, source=None):
        self.released = True
        return SimpleNamespace(tx_hash="f" * 64, value=None)

    def get_status(self, chain_intent_id):
        status = "Released" if self.released else "Funded"
        return {"status": status, "request_hash": self.request_hash}


def escrowed_intent(repo, ref="INV-F1"):
    rhash = f"{ref:0<64}"
    supplier = repo.supplier_by_name("CV Batik Nusantara")
    outcome = repo.record_decision(
        decision="proposed",
        codes=["OK"],
        request_hash=rhash,
        intent=IntentDraft(
            supplier_id=supplier["id"],
            amount=12_500_000_000,
            token="CTOKEN",
            deadline=1_800_000_000,
            invoice_ref=ref,
            request_hash=rhash,
        ),
    )
    repo.set_chain_intent(outcome.intent_id, 1)
    repo.record_decision(
        decision="approved",
        codes=["ESCROWED_ONCHAIN"],
        request_hash=rhash,
        intent_id=outcome.intent_id,
    )
    return outcome.intent_id, rhash


def test_config_from_file_then_env_overrides(tmp_path, monkeypatch):
    toml = tmp_path / "amanah.toml"
    toml.write_text(
        "k_of_n = 3\nproof_of_compute = true\nhuman_cosign_threshold = 5\n"
    )
    cfg = Config.from_file(toml)
    assert cfg.k_of_n == 3
    assert cfg.proof_of_compute is True
    assert cfg.human_cosign_threshold == 5
    assert cfg.injection_scan is True
    assert cfg.policy_engine is True
    assert cfg.policy_signer is True
    assert cfg.require_attestation is False
    assert cfg.dry_run is False

    monkeypatch.setenv("AMANAH_CONFIG", str(toml))
    monkeypatch.setenv("AMANAH_K_OF_N", "2")
    monkeypatch.setenv("AMANAH_DRY_RUN", "true")
    cfg = Config.from_env()
    assert cfg.k_of_n == 2
    assert cfg.proof_of_compute is True
    assert cfg.dry_run is True


def test_injection_scan_toggle_changes_decision(repo, config):
    text = load_invoice("inject_override.txt")
    on = pipeline.run(text, repo, MockProvider(), config)
    assert on.decision == "refused"

    off = pipeline.run(
        text, repo, MockProvider(), Config(db_path=config.db_path, injection_scan=False)
    )
    assert off.decision == "proposed"
    assert off.flags == []


def test_policy_engine_toggle_changes_decision(repo, config):
    text = load_invoice("over_cap.txt")
    on = pipeline.run(text, repo, MockProvider(), config)
    assert on.decision == "refused"

    off = pipeline.run(
        text,
        repo,
        MockProvider(),
        Config(db_path=config.db_path, policy_engine=False, policy_signer=False),
    )
    assert off.decision == "proposed"


def test_policy_signer_refuses_over_cap_when_engine_off(repo, config):
    text = load_invoice("over_cap.txt")
    signer_only = pipeline.run(
        text, repo, MockProvider(), Config(db_path=config.db_path, policy_engine=False)
    )
    assert signer_only.decision == "refused"
    assert pipeline.SIGNER_OVER_CAP in signer_only.codes


def test_cosign_holds_above_threshold(repo, config):
    cfg = Config(db_path=config.db_path, human_cosign_threshold=1_000 * STROOP)
    result = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), cfg)
    assert result.decision == "held"
    assert pipeline.COSIGN_REQUIRED in result.codes
    assert result.tx_plan is None
    assert result.intent_id is not None
    assert repo.intent(result.intent_id)["status"] == "held"
    decisions = repo.decision_rows()
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "held"


def test_cosign_passes_below_threshold(repo, config):
    cfg = Config(db_path=config.db_path, human_cosign_threshold=2_000 * STROOP)
    result = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), cfg)
    assert result.decision == "proposed"


def test_cosign_token_clears_hold(repo, config):
    cfg = Config(db_path=config.db_path, human_cosign_threshold=1_000 * STROOP)
    result = pipeline.run(
        load_invoice("clean_in_policy.txt"),
        repo,
        MockProvider(),
        cfg,
        cosign_token="OWNER-OK-1",
    )
    assert result.decision == "proposed"


def test_proof_of_compute_toggle_and_receipt_verification(repo, config):
    cfg = Config(db_path=config.db_path, proof_of_compute=True)
    text = load_invoice("clean_in_policy.txt")

    missing = pipeline.run(text, repo, MockProvider(), cfg)
    assert missing.decision == "refused"
    assert pipeline.POC_RECEIPT_INVALID in missing.codes

    tampered = pipeline.run(
        text, repo, MockProvider(), cfg, compute_receipt={"payload": "run-1", "digest": "0" * 64}
    )
    assert tampered.decision == "refused"
    assert pipeline.POC_RECEIPT_INVALID in tampered.codes

    receipt = {
        "payload": "run-1",
        "digest": hashlib.sha256(b"run-1").hexdigest(),
    }
    valid = pipeline.run(text, repo, MockProvider(), cfg, compute_receipt=receipt)
    assert valid.decision == "proposed"


def test_dry_run_proposes_but_never_submits(repo, config):
    cfg = Config(db_path=config.db_path, dry_run=True)
    result = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), cfg)
    assert result.decision == "proposed"
    assert result.tx_plan is not None

    assert flow.execute(repo, ExplodingClient(), result.intent_id, "sme", cfg) is None
    assert repo.intent(result.intent_id)["status"] == "proposed"
    assert repo.chain_txs(result.intent_id) == []
    assert [d["decision"] for d in repo.decision_rows()] == ["proposed"]


def test_require_attestation_blocks_release_until_attested(repo, config):
    intent_id, rhash = escrowed_intent(repo)
    cfg = Config(db_path=config.db_path, require_attestation=True)
    client = FakeChainClient(rhash)

    with pytest.raises(pipeline.GuardRefused):
        flow.release(repo, client, intent_id, "sme", cfg)
    assert client.released is False
    assert repo.intent(intent_id)["status"] == "escrowed"

    repo.add_attestation(intent_id, ORACLE_A, "Shipped", rhash)
    assert flow.release(repo, client, intent_id, "sme", cfg) == "released"
    assert client.released is True


def test_release_default_config_needs_no_local_attestation(repo, config):
    intent_id, rhash = escrowed_intent(repo)
    client = FakeChainClient(rhash)
    assert flow.release(repo, client, intent_id, "sme", config) == "released"


def test_k_of_n_requires_k_distinct_oracles(repo, config):
    intent_id, rhash = escrowed_intent(repo)
    cfg = Config(db_path=config.db_path, k_of_n=3)
    client = FakeChainClient(rhash)

    repo.add_attestation(intent_id, ORACLE_A, "Shipped", rhash)
    repo.add_attestation(intent_id, ORACLE_A, "Shipped", rhash)
    repo.add_attestation(intent_id, ORACLE_B, "Shipped", rhash)
    repo.add_attestation(intent_id, ORACLE_C, "Failed", rhash)
    repo.add_attestation(intent_id, ORACLE_C, "Shipped", "e" * 64)

    with pytest.raises(pipeline.GuardRefused):
        flow.release(repo, client, intent_id, "sme", cfg)
    assert client.released is False

    repo.add_attestation(intent_id, ORACLE_C, "Shipped", rhash)
    assert flow.release(repo, client, intent_id, "sme", cfg) == "released"


def test_record_decision_held_is_audited_at_chokepoint(repo):
    supplier = repo.supplier_by_name("CV Batik Nusantara")
    outcome = repo.record_decision(
        decision="held",
        codes=[pipeline.COSIGN_REQUIRED],
        request_hash="a" * 64,
        intent=IntentDraft(
            supplier_id=supplier["id"],
            amount=100,
            token="CTOKEN",
            deadline=1_800_000_000,
            invoice_ref="INV-HOLD",
            request_hash="a" * 64,
        ),
    )
    assert repo.intent(outcome.intent_id)["status"] == "held"
    rows = repo.decision_rows()
    assert len(rows) == 1
    assert rows[0]["decision"] == "held"

    with pytest.raises(ValueError):
        repo.record_decision(decision="held", codes=[], request_hash="b" * 64)


def test_default_chain_order_and_flags():
    guards = pipeline.build_guards(Config())
    assert [type(g).__name__ for g in guards] == [
        "InjectionGuard",
        "PolicyEngineGuard",
        "PolicySignerGuard",
        "AttestationGuard",
        "KofNOracleGuard",
        "HumanCosignGuard",
        "ProofOfComputeGuard",
    ]
    enabled = [g.enabled for g in guards]
    assert enabled == [True, True, True, False, False, False, False]
