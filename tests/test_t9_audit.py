import json

import pytest

from lumo.db import seed
from lumo.models import IntentDraft


def make_draft(repo, request_hash):
    supplier = repo.supplier_by_name("CV Batik Nusantara")
    return IntentDraft(
        supplier_id=supplier["id"],
        amount=100 * seed.STROOP,
        token=seed.TOKEN_ADDRESS,
        deadline=1_800_000_000,
        invoice_ref="INV-T9",
        request_hash=request_hash,
    )


def audit_count(repo):
    return len(repo.decision_rows())


def test_t9_each_decision_writes_exactly_one_audit_row(repo):
    rhash = "a" * 64

    outcome = repo.record_decision(
        decision="proposed", codes=["OK"], request_hash=rhash,
        intent=make_draft(repo, rhash),
    )
    assert audit_count(repo) == 1
    assert repo.intent_count() == 1

    repo.record_decision(
        decision="approved", codes=["OK"], request_hash=rhash,
        intent_id=outcome.intent_id,
    )
    assert audit_count(repo) == 2
    status = repo.conn.execute(
        "SELECT status FROM intents WHERE id = ?", (outcome.intent_id,)
    ).fetchone()["status"]
    assert status == "escrowed"

    repo.record_decision(
        decision="refused", codes=["OVER_TX_CAP"], request_hash="b" * 64,
    )
    assert audit_count(repo) == 3
    assert repo.intent_count() == 1

    repo.record_decision(
        decision="reverted", codes=["OK"], request_hash=rhash,
        intent_id=outcome.intent_id,
    )
    assert audit_count(repo) == 4
    status = repo.conn.execute(
        "SELECT status FROM intents WHERE id = ?", (outcome.intent_id,)
    ).fetchone()["status"]
    assert status == "reverted"

    decisions = [r["decision"] for r in repo.decision_rows()]
    assert sorted(decisions) == ["approved", "proposed", "refused", "reverted"]


def test_t9_codes_persist_as_json(repo):
    repo.record_decision(
        decision="refused", codes=["OVER_TX_CAP", "ADDRESS_MISMATCH"],
        request_hash="c" * 64,
    )
    row = repo.decision_rows()[0]
    assert json.loads(row["codes"]) == ["OVER_TX_CAP", "ADDRESS_MISMATCH"]


def test_t9_chokepoint_rejects_malformed_calls(repo):
    with pytest.raises(ValueError):
        repo.record_decision(decision="paid", codes=[], request_hash="d" * 64)
    with pytest.raises(ValueError):
        repo.record_decision(decision="proposed", codes=[], request_hash="d" * 64)
    with pytest.raises(ValueError):
        repo.record_decision(decision="approved", codes=[], request_hash="d" * 64)
    with pytest.raises(ValueError):
        repo.record_decision(
            decision="refused", codes=[], request_hash="d" * 64, intent_id="X"
        )
    assert audit_count(repo) == 0
