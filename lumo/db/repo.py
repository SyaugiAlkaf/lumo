import json
import sqlite3
from dataclasses import dataclass

from lumo.db import ulid
from lumo.models import IntentDraft, PriorIntent
from lumo.monitor.events import Event, EventBus

DECISIONS = ("proposed", "held", "approved", "refused", "reverted")

DECISION_EVENTS = {
    "proposed": "intent.proposed",
    "held": "intent.held",
    "refused": "intent.refused",
    "approved": "intent.escrowed",
    "reverted": "intent.reverted",
}


@dataclass
class DecisionOutcome:
    decision_id: str
    intent_id: str | None


class Repo:
    def __init__(self, conn: sqlite3.Connection, bus: EventBus | None = None):
        self.conn = conn
        self.bus = bus or EventBus()

    def emit(self, name: str, /, **payload) -> None:
        if not self.bus.enabled:
            return
        self.conn.execute(
            "INSERT INTO events (id, name, payload) VALUES (?, ?, ?)",
            (ulid.new(), name, json.dumps(payload)),
        )
        self.conn.commit()
        self.bus.publish(Event(name=name, payload=payload))

    def events(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events ORDER BY rowid DESC LIMIT ?", (limit,)
        ).fetchall()

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

    def intent(self, intent_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM intents WHERE id = ?", (intent_id,)
        ).fetchone()

    def supplier_by_id(self, supplier_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM suppliers WHERE id = ?", (supplier_id,)
        ).fetchone()

    def claim_escrow(self, intent_id: str) -> bool:
        """Atomically reserve a proposed intent for on-chain escrow.

        Returns True only if this call transitioned the intent from 'proposed'
        to 'escrowed'. A concurrent or retried caller gets False and must not
        submit again — this single conditional UPDATE is what prevents a double
        on-chain escrow of the same invoice. ('escrowed' doubles as the in-flight
        marker; the status CHECK constraint has no distinct 'escrowing' state.)
        """
        with self.conn:
            cur = self.conn.execute(
                "UPDATE intents SET status = 'escrowed' "
                "WHERE id = ? AND status = 'proposed'",
                (intent_id,),
            )
        return cur.rowcount == 1

    def release_escrow_claim(self, intent_id: str) -> None:
        """Return a claimed-but-not-submitted intent to 'proposed' so a genuine
        retry can proceed. Reopens only when no chain intent exists — once an
        on-chain escrow was created the claim is never released (a retry must
        reconcile against that escrow, not create a second one)."""
        with self.conn:
            self.conn.execute(
                "UPDATE intents SET status = 'proposed' "
                "WHERE id = ? AND status = 'escrowed' AND chain_intent_id IS NULL",
                (intent_id,),
            )

    def set_chain_intent(self, intent_id: str, chain_intent_id: int) -> None:
        self.conn.execute(
            "UPDATE intents SET chain_intent_id = ? WHERE id = ?",
            (chain_intent_id, intent_id),
        )
        self.conn.commit()

    def mark_released(self, intent_id: str) -> None:
        self.conn.execute(
            "UPDATE intents SET status = 'released' WHERE id = ?", (intent_id,)
        )
        self.conn.commit()
        self.emit("intent.released", intent_id=intent_id)

    def add_chain_tx(self, intent_id: str, action: str, tx_hash: str | None) -> None:
        self.conn.execute(
            "INSERT INTO chain_txs (id, intent_id, action, tx_hash) VALUES (?, ?, ?, ?)",
            (ulid.new(), intent_id, action, tx_hash),
        )
        self.conn.commit()

    def chain_txs(self, intent_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM chain_txs WHERE intent_id = ? ORDER BY created_at",
            (intent_id,),
        ).fetchall()

    def add_anchor_payout(
        self, intent_id: str, ref: str, amount: str, address: str
    ) -> None:
        self.conn.execute(
            "INSERT INTO anchor_payouts (id, intent_id, ref, amount, address) "
            "VALUES (?, ?, ?, ?, ?)",
            (ulid.new(), intent_id, ref, amount, address),
        )
        self.conn.commit()

    def anchor_payouts(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM anchor_payouts ORDER BY created_at"
        ).fetchall()

    def supplier_addresses(self) -> set[str]:
        rows = self.conn.execute("SELECT address FROM suppliers").fetchall()
        return {r["address"] for r in rows}

    def add_attestation(
        self, intent_id: str, oracle_address: str, kind: str, request_hash: str
    ) -> None:
        self.conn.execute(
            "INSERT INTO attestations (id, intent_id, oracle_address, kind, request_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (ulid.new(), intent_id, oracle_address, kind, request_hash),
        )
        self.conn.commit()

    def attestations(self, intent_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM attestations WHERE intent_id = ? ORDER BY created_at",
            (intent_id,),
        ).fetchall()

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
        if decision in ("proposed", "held") and intent is None:
            raise ValueError(f"{decision} requires an intent draft")
        if decision in ("approved", "reverted") and intent_id is None:
            raise ValueError(f"{decision} requires an intent_id")
        if decision == "refused" and (intent is not None or intent_id is not None):
            raise ValueError("refused must not carry an intent")

        decision_id = ulid.new()
        with self.conn:
            if decision in ("proposed", "held"):
                intent_id = ulid.new()
                self.conn.execute(
                    "INSERT INTO intents (id, request_hash, supplier_id, amount, "
                    "token, deadline, status, invoice_ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        intent_id,
                        intent.request_hash,
                        intent.supplier_id,
                        str(intent.amount),
                        intent.token,
                        intent.deadline,
                        decision,
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
        self.emit(
            DECISION_EVENTS[decision],
            decision_id=decision_id,
            intent_id=intent_id,
            request_hash=request_hash,
            codes=codes,
        )
        return DecisionOutcome(decision_id=decision_id, intent_id=intent_id)
