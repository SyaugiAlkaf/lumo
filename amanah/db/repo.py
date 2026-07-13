import json
import sqlite3
from dataclasses import dataclass

from amanah.db import ulid
from amanah.models import IntentDraft, PriorIntent

DECISIONS = ("proposed", "approved", "refused", "reverted")


@dataclass
class DecisionOutcome:
    decision_id: str
    intent_id: str | None


class Repo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add_supplier(self, name: str, address: str) -> str:
        supplier_id = ulid.new()
        self.conn.execute(
            "INSERT INTO suppliers (id, name, address) VALUES (?, ?, ?)",
            (supplier_id, name, address),
        )
        self.conn.commit()
        return supplier_id

    def supplier_by_name(self, name: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM suppliers WHERE name = ?", (name,)
        ).fetchone()

    def set_rule(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO policy_rules (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def rule(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM policy_rules WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def rules(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM policy_rules").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def intents_today(self) -> list[PriorIntent]:
        rows = self.conn.execute(
            "SELECT amount, status FROM intents WHERE date(created_at) = date('now')"
        ).fetchall()
        return [PriorIntent(amount=int(r["amount"]), status=r["status"]) for r in rows]

    def known_request_hashes(self) -> set[str]:
        rows = self.conn.execute("SELECT request_hash FROM intents").fetchall()
        return {r["request_hash"] for r in rows}

    def intent_count(self) -> int:
        return self.conn.execute("SELECT count(*) AS n FROM intents").fetchone()["n"]

    def decision_rows(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM decisions ORDER BY created_at").fetchall()

    def record_decision(
        self,
        *,
        decision: str,
        codes: list[str],
        request_hash: str,
        intent: IntentDraft | None = None,
        intent_id: str | None = None,
        detail: str | None = None,
    ) -> DecisionOutcome:
        if decision not in DECISIONS:
            raise ValueError(f"unknown decision {decision!r}")
        if decision == "proposed" and intent is None:
            raise ValueError("proposed requires an intent draft")
        if decision in ("approved", "reverted") and intent_id is None:
            raise ValueError(f"{decision} requires an intent_id")
        if decision == "refused" and (intent is not None or intent_id is not None):
            raise ValueError("refused must not carry an intent")

        decision_id = ulid.new()
        with self.conn:
            if decision == "proposed":
                intent_id = ulid.new()
                self.conn.execute(
                    "INSERT INTO intents (id, request_hash, supplier_id, amount, "
                    "token, deadline, status, invoice_ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?)",
                    (
                        intent_id,
                        intent.request_hash,
                        intent.supplier_id,
                        str(intent.amount),
                        intent.token,
                        intent.deadline,
                        intent.invoice_ref,
                    ),
                )
            elif decision == "approved":
                self.conn.execute(
                    "UPDATE intents SET status = 'escrowed' WHERE id = ?", (intent_id,)
                )
            elif decision == "reverted":
                self.conn.execute(
                    "UPDATE intents SET status = 'reverted' WHERE id = ?", (intent_id,)
                )
            self.conn.execute(
                "INSERT INTO decisions (id, decision, codes, request_hash, intent_id, detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (decision_id, decision, json.dumps(codes), request_hash, intent_id, detail),
            )
        return DecisionOutcome(decision_id=decision_id, intent_id=intent_id)
