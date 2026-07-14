import hashlib
from pathlib import Path

import pytest

from lumo import pipeline
from lumo.config import Config
from lumo.llm.mock import MockProvider

from conftest import load_invoice

ROOT = Path(__file__).parent.parent
STROOP = pipeline.STROOP

SECTIONS = [
    "Integrate in 5 lines",
    "Call from any language",
    "Use from any AI agent",
    "Target any chain",
    "Monitor it",
    "Pick a trust tier",
]


def test_profile_strict():
    cfg = Config.profile("strict")
    assert cfg.injection_scan is True
    assert cfg.policy_engine is True
    assert cfg.policy_signer is True
    assert cfg.require_attestation is True
    assert cfg.k_of_n == 3
    assert cfg.human_cosign_threshold == 100 * STROOP
    assert cfg.proof_of_compute is True


def test_profile_balanced():
    cfg = Config.profile("balanced")
    assert cfg.injection_scan is True
    assert cfg.policy_engine is True
    assert cfg.policy_signer is True
    assert cfg.require_attestation is True
    assert cfg.k_of_n == 1
    assert cfg.human_cosign_threshold == 0
    assert cfg.proof_of_compute is False


def test_profile_fast():
    cfg = Config.profile("fast")
    assert cfg.injection_scan is True
    assert cfg.policy_engine is True
    assert cfg.policy_signer is False
    assert cfg.require_attestation is False
    assert cfg.k_of_n == 1
    assert cfg.human_cosign_threshold == 0
    assert cfg.proof_of_compute is False


def test_profile_unknown_raises():
    with pytest.raises(ValueError):
        Config.profile("paranoid")


def test_profile_overrides_keep_preset():
    cfg = Config.profile("strict", db_path="/tmp/x.db", k_of_n=5)
    assert cfg.db_path == "/tmp/x.db"
    assert cfg.k_of_n == 5
    assert cfg.proof_of_compute is True


def test_profile_guard_chain_enablement():
    enabled = lambda name: [g.enabled for g in pipeline.build_guards(Config.profile(name))]
    assert enabled("strict") == [True] * 7
    assert enabled("balanced") == [True, True, True, True, False, False, False]
    assert enabled("fast") == [True, True, False, False, False, False, False]


def test_fast_profile_still_refuses_injection_and_over_cap(repo, db_path):
    cfg = Config.profile("fast", db_path=str(db_path))
    injected = pipeline.run(load_invoice("inject_override.txt"), repo, MockProvider(), cfg)
    assert injected.decision == "refused"

    over = pipeline.run(load_invoice("over_cap.txt"), repo, MockProvider(), cfg)
    assert over.decision == "refused"


def test_strict_profile_blocks_then_proposes_with_proofs(repo, db_path):
    cfg = Config.profile("strict", db_path=str(db_path))
    text = load_invoice("clean_in_policy.txt")

    blocked = pipeline.run(text, repo, MockProvider(), cfg)
    assert blocked.decision == "refused"
    assert pipeline.POC_RECEIPT_INVALID in blocked.codes
    assert pipeline.COSIGN_REQUIRED in blocked.codes

    receipt = {"payload": "run-1", "digest": hashlib.sha256(b"run-1").hexdigest()}
    ok = pipeline.run(
        text, repo, MockProvider(), cfg, cosign_token="OWNER-OK-1", compute_receipt=receipt
    )
    assert ok.decision == "proposed"


def test_readme_has_integration_sections():
    text = (ROOT / "README.md").read_text()
    for section in SECTIONS:
        assert section in text, f"README missing section: {section}"
    assert "Config.profile" in text


def test_docs_integration_covers_sections_and_profiles():
    text = (ROOT / "docs" / "integration.md").read_text()
    for section in SECTIONS:
        assert section in text, f"docs/integration.md missing section: {section}"
    for name in ("strict", "balanced", "fast"):
        assert name in text
