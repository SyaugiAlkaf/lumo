import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _ensure_tracking(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "id TEXT PRIMARY KEY, "
        "applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
    )


def applied(conn: sqlite3.Connection) -> list[str]:
    _ensure_tracking(conn)
    rows = conn.execute("SELECT id FROM schema_migrations ORDER BY id").fetchall()
    return [r["id"] for r in rows]


def available() -> list[str]:
    return sorted(p.name.removesuffix(".up.sql") for p in MIGRATIONS_DIR.glob("*.up.sql"))


def up(conn: sqlite3.Connection) -> list[str]:
    done = set(applied(conn))
    ran = []
    for mig in available():
        if mig in done:
            continue
        sql = (MIGRATIONS_DIR / f"{mig}.up.sql").read_text()
        with conn:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations (id) VALUES (?)", (mig,))
        ran.append(mig)
    return ran


def down(conn: sqlite3.Connection, steps: int = 1) -> list[str]:
    ran = []
    for mig in reversed(applied(conn)[-steps:] if steps else []):
        sql = (MIGRATIONS_DIR / f"{mig}.down.sql").read_text()
        with conn:
            conn.executescript(sql)
            conn.execute("DELETE FROM schema_migrations WHERE id = ?", (mig,))
        ran.append(mig)
    return ran
