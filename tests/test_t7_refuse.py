from amanah import cli, pipeline
from amanah.llm.mock import MockProvider
from amanah.policy import engine

from conftest import FIXTURES, load_invoice


def test_t7_over_cap_refused_no_tx(repo, config):
    result = pipeline.run(load_invoice("over_cap.txt"), repo, MockProvider(), config)
    assert result.decision == "refused"
    assert engine.OVER_TX_CAP in result.codes
    assert result.tx_plan is None
    assert result.intent_id is None
    assert repo.intent_count() == 0
    decisions = repo.decision_rows()
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "refused"
    assert decisions[0]["intent_id"] is None


def test_t7_unknown_supplier_refused_no_tx(repo, config):
    result = pipeline.run(load_invoice("unknown_supplier.txt"), repo, MockProvider(), config)
    assert result.decision == "refused"
    assert engine.UNKNOWN_SUPPLIER in result.codes
    assert result.tx_plan is None
    assert repo.intent_count() == 0


def test_t7_duplicate_proposal_refused(repo, config):
    first = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    assert first.decision == "proposed"
    second = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    assert second.decision == "refused"
    assert engine.DUPLICATE_REQUEST in second.codes
    assert repo.intent_count() == 1


def test_t7_cli_exit_2_on_refusal(db_path):
    assert cli.main(["--db", str(db_path), "init"]) == 0
    rc = cli.main(["--db", str(db_path), "propose", str(FIXTURES / "over_cap.txt")])
    assert rc == 2


def test_t7_cli_exit_3_on_error(db_path):
    assert cli.main(["--db", str(db_path), "init"]) == 0
    rc = cli.main(["--db", str(db_path), "propose", str(FIXTURES / "does_not_exist.txt")])
    assert rc == 3
