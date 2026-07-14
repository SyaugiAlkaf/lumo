CREATE TABLE suppliers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    address TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE policy_rules (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
