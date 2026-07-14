PRAGMA foreign_keys=OFF;

DROP TABLE attestations;

DELETE FROM decisions WHERE decision = 'held';
DELETE FROM intents WHERE status = 'held';

CREATE TABLE intents_old (
    id TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL UNIQUE,
    supplier_id TEXT NOT NULL REFERENCES suppliers(id),
    amount TEXT NOT NULL,
    token TEXT NOT NULL,
    deadline INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed', 'escrowed', 'released', 'reverted')),
    chain_intent_id INTEGER,
    invoice_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO intents_old SELECT * FROM intents;
DROP TABLE intents;
ALTER TABLE intents_old RENAME TO intents;

CREATE TABLE decisions_old (
    id TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK (decision IN ('proposed', 'approved', 'refused', 'reverted')),
    codes TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    intent_id TEXT REFERENCES intents(id),
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO decisions_old SELECT * FROM decisions;
DROP TABLE decisions;
ALTER TABLE decisions_old RENAME TO decisions;

PRAGMA foreign_keys=ON;
