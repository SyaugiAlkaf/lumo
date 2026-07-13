CREATE TABLE chain_txs (
    id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES intents(id),
    action TEXT NOT NULL,
    tx_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE anchor_payouts (
    id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES intents(id),
    ref TEXT NOT NULL UNIQUE,
    amount TEXT NOT NULL,
    address TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
