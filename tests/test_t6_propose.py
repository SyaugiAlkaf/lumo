from lumo import cli, pipeline
from lumo.db import seed
from lumo.llm.mock import MockProvider

from conftest import FIXTURES, load_invoice

BATIK_ADDRESS = dict(seed.SUPPLIERS)["CV Batik Nusantara"]


def test_t6_in_policy_invoice_proposes(repo, config):
    result = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    assert result.decision == "proposed"
    assert result.codes == ["OK"]
    assert result.flags == []
    assert result.intent_id is not None
    assert repo.intent_count() == 1
    row = repo.conn.execute("SELECT * FROM intents").fetchone()
    assert row["status"] == "proposed"
    assert row["request_hash"] == result.request_hash
    decisions = repo.decision_rows()
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "proposed"


def test_t6_tx_plan_shape_matches_escrow_binding(repo, config):
    result = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    plan = result.tx_plan
    assert plan.function == "create_intent"
    args = plan.args.model_dump()
    assert set(args) == {"sme", "supplier", "token", "amount", "request_hash", "deadline"}
    assert args["sme"] == seed.SME_ADDRESS
    assert args["supplier"] == BATIK_ADDRESS
    assert args["token"] == seed.TOKEN_ADDRESS
    assert args["amount"] == str(1_250 * seed.STROOP)
    assert isinstance(args["amount"], str)
    assert args["request_hash"] == result.request_hash
    assert len(args["request_hash"]) == 64
    assert isinstance(args["deadline"], int)


def test_t6_registry_address_wins_when_invoice_omits_address(repo, config):
    text = "\n".join(
        line
        for line in load_invoice("clean_in_policy.txt").splitlines()
        if not line.startswith("Payment address:")
    )
    result = pipeline.run(text, repo, MockProvider(), config)
    assert result.decision == "proposed"
    assert result.tx_plan.args.supplier == BATIK_ADDRESS


def test_t6_cli_exit_0_on_propose(db_path):
    assert cli.main(["--db", str(db_path), "init"]) == 0
    rc = cli.main(["--db", str(db_path), "propose", str(FIXTURES / "clean_in_policy.txt")])
    assert rc == 0
