PRAGMA foreign_keys=OFF;

CREATE TABLE attestations (
    id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES intents(id),
    oracle_address TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('Shipped', 'Failed')),
    request_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE intents_new (
    id TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL UNIQUE,
    supplier_id TEXT NOT NULL REFERENCES suppliers(id),
    amount TEXT NOT NULL,
    token TEXT NOT NULL,
    deadline INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed', 'held', 'escrowed', 'released', 'reverted')),
    chain_intent_id INTEGER,
    invoice_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO intents_new SELECT * FROM intents;
DROP TABLE intents;
ALTER TABLE intents_new RENAME TO intents;

CREATE TABLE decisions_new (
    id TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK (decision IN ('proposed', 'held', 'approved', 'refused', 'reverted')),
    codes TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    intent_id TEXT REFERENCES intents(id),
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO decisions_new SELECT * FROM decisions;
DROP TABLE decisions;
ALTER TABLE decisions_new RENAME TO decisions;

PRAGMA foreign_keys=ON;
