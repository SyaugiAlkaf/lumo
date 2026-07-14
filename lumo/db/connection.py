import sqlite3
from pathlib import Path


def connect(path: str | Path, check_same_thread: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
