from pathlib import Path

from amanah import pipeline
from amanah.cli import build_provider
from amanah.config import Config
from amanah.db import migrate, seed
from amanah.db.connection import connect
from amanah.db.repo import Repo
from amanah.models import PipelineResult
from amanah.monitor import metrics
from amanah.monitor.events import EventBus, Subscriber
from amanah.monitor.webhooks import build_webhooks
from amanah.oracle.adapter import LocalSignerSet, build_oracle

Decision = PipelineResult

ATTEST_KINDS = ("Shipped", "Failed")


class AmanahClient:
    def __init__(self, config: Config | None = None):
        self.config = config or Config.from_env()
        # SDK clients get embedded in servers; sqlite access stays serialized
        # through Repo transactions, so cross-thread handles are safe here
        self.conn = connect(self.config.db_path, check_same_thread=False)
        migrate.up(self.conn)
        if not self.conn.execute("SELECT count(*) AS n FROM policy_rules").fetchone()["n"]:
            seed.seed(self.conn)
        self.bus = EventBus(enabled=self.config.monitoring)
        hooks = build_webhooks(self.config)
        if hooks:
            self.bus.subscribe(hooks)
        self.repo = Repo(self.conn, bus=self.bus)
        self.provider = build_provider(self.config)

    def propose(self, invoice: str | Path) -> Decision:
        text = invoice.read_text() if isinstance(invoice, Path) else invoice
        return pipeline.run(text, self.repo, self.provider, self.config)

    def status(self, intent_id: str) -> dict | None:
        row = self.repo.intent(intent_id)
        return dict(row) if row else None

    def attest(self, intent_id: str, kind: str) -> list[str]:
        if kind not in ATTEST_KINDS:
            raise ValueError(f"unknown attestation kind {kind!r}")
        row = self.repo.intent(intent_id)
        if row is None:
            raise ValueError(f"unknown intent {intent_id}")
        oracle = build_oracle(self.config) or LocalSignerSet(
            [self.config.oracle_address or "local-oracle"]
        )
        return oracle.submit(self.repo, intent_id, kind, row["request_hash"])

    def on_event(self, callback: Subscriber) -> None:
        self.bus.subscribe(callback)

    def metrics(self) -> dict:
        return metrics.snapshot(self.conn)

    def close(self) -> None:
        self.conn.close()
