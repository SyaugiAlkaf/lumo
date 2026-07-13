"""Build a fully-populated demo DB for the UI, entirely in-process.

Mock provider + mock chain, one adapter instance, so the whole Bu Sari story
lands in one SQLite file: proposal -> escrow -> attest -> release (+ mock
cash-out), a poisoned invoice refused by the injection guard, and a second
escrow that lapses past its deadline and reverts. No network, no Docker.
"""

import argparse
import json
import time
from pathlib import Path

from amanah import flow, pipeline
from amanah.chain.mock_chain import MockChainAdapter
from amanah.config import Config
from amanah.db import migrate, seed
from amanah.db.connection import connect
from amanah.llm.mock import MockProvider
from amanah.db.repo import Repo
from amanah.monitor import metrics

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "invoices"

STROOP = 10_000_000


def invoice(name: str) -> str:
    return (FIXTURES / name).read_text()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="amanah-demo.db")
    args = parser.parse_args()

    config = Config(db_path=args.db, provider="mock", chain_adapter="mock")
    conn = connect(config.db_path)
    migrate.up(conn)
    seed.seed(conn)
    repo = Repo(conn)
    provider = MockProvider()
    chain = MockChainAdapter(now=int(time.time()))
    rules = repo.rules()
    chain.fund(rules["token_address"], rules["sme_address"], 10_000 * STROOP)

    happy = pipeline.run(invoice("clean_in_policy.txt"), repo, provider, config)
    assert happy.decision == "proposed", happy
    flow.execute(repo, chain, happy.intent_id, config.sme_source, config)
    flow.attest(
        repo, chain, happy.intent_id, "Shipped", config.oracle_address, config.oracle_source
    )
    status = flow.release(repo, chain, happy.intent_id, config.sme_source, config)
    assert status == "released", status

    poisoned = pipeline.run(invoice("inject_address_swap.txt"), repo, provider, config)
    assert poisoned.decision == "refused", poisoned
    assert "INJECTION_SUSPECTED" in poisoned.codes, poisoned

    lapse = pipeline.run(invoice("clean_control.txt"), repo, provider, config)
    assert lapse.decision == "proposed", lapse
    flow.execute(repo, chain, lapse.intent_id, config.sme_source, config)
    chain.now = 2**62  # mock clock past the deadline: refund path, no time-travel on disk
    status = flow.revert(repo, chain, lapse.intent_id, config.sme_source)
    assert status == "reverted", status

    print(json.dumps(metrics.snapshot(conn)))
    conn.close()


if __name__ == "__main__":
    main()
