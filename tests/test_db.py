import pytest

from amanah.chain.request_hash import canonical_json, request_hash
from amanah.db import migrate, ulid
from amanah.db.connection import connect


def test_connection_enables_wal_and_foreign_keys(db_path):
    conn = connect(db_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migrate_up_creates_schema(conn):
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "suppliers",
        "policy_rules",
        "intents",
        "decisions",
        "chain_txs",
        "anchor_payouts",
    } <= tables
    assert migrate.applied(conn) == [
        "0001_registry",
        "0002_intents_audit",
        "0003_chain_anchor",
        "0004_trust_pipeline",
        "0005_events",
    ]


def test_migrate_down_reverts_all(db_path):
    conn = connect(db_path)
    migrate.up(conn)
    migrate.down(conn, steps=5)
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert tables == {"schema_migrations"}
    assert migrate.applied(conn) == []


def test_intents_request_hash_unique(conn):
    supplier = conn.execute("SELECT id FROM suppliers LIMIT 1").fetchone()
    row = (ulid.new(), "h" * 64, supplier["id"], "100", "C" * 56, 1, "proposed")
    conn.execute(
        "INSERT INTO intents (id, request_hash, supplier_id, amount, token, deadline, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO intents (id, request_hash, supplier_id, amount, token, deadline, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ulid.new(), *row[1:]),
        )


def test_ulid_shape_and_alphabet():
    value = ulid.new()
    assert len(value) == 26
    assert set(value) <= set(ulid.ALPHABET)


def test_ulid_sorts_by_timestamp_and_roundtrips():
    early = ulid.new(timestamp_ms=1_000_000)
    late = ulid.new(timestamp_ms=2_000_000)
    assert early < late
    assert ulid.timestamp_ms(early) == 1_000_000
    assert ulid.timestamp_ms(late) == 2_000_000


def test_request_hash_key_order_invariant():
    a = request_hash({"sme": "G1", "supplier": "G2", "amount": "100"})
    b = request_hash({"amount": "100", "supplier": "G2", "sme": "G1"})
    assert a == b
    assert len(a) == 64
    int(a, 16)


def test_request_hash_changes_with_content():
    base = {"sme": "G1", "supplier": "G2", "amount": "100"}
    assert request_hash(base) != request_hash({**base, "amount": "101"})


def test_canonical_json_is_compact_and_sorted():
    assert canonical_json({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'
