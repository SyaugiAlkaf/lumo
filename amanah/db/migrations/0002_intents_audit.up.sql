CREATE TABLE intents (
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

CREATE TABLE decisions (
    id TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK (decision IN ('proposed', 'approved', 'refused', 'reverted')),
    codes TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    intent_id TEXT REFERENCES intents(id),
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
