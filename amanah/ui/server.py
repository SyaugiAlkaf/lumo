import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from amanah.config import PROFILES, Config
from amanah.monitor import metrics

INDEX = Path(__file__).parent / "index.html"

TRUST_FLAGS = (
    "injection_scan",
    "policy_engine",
    "policy_signer",
    "require_attestation",
    "k_of_n",
    "human_cosign_threshold",
    "proof_of_compute",
)


def trust_state() -> dict:
    config = Config.from_env()
    flags = {name: getattr(config, name) for name in TRUST_FLAGS}
    profile = next(
        (name for name, p in PROFILES.items() if all(flags[k] == v for k, v in p.items())),
        "custom",
    )
    return {"flags": flags, "profile": profile, "profiles": PROFILES}


def connect_ro(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def read_state(db_path: str) -> dict:
    conn = connect_ro(db_path)
    try:
        state = {
            "suppliers": [dict(r) for r in conn.execute("SELECT * FROM suppliers")],
            "rules": {
                r["key"]: r["value"] for r in conn.execute("SELECT * FROM policy_rules")
            },
            "intents": [
                dict(r)
                for r in conn.execute(
                    "SELECT i.*, s.name AS supplier_name FROM intents i "
                    "JOIN suppliers s ON s.id = i.supplier_id ORDER BY i.created_at"
                )
            ],
            "decisions": [
                dict(r)
                for r in conn.execute("SELECT * FROM decisions ORDER BY created_at")
            ],
            "chain_txs": [
                dict(r)
                for r in conn.execute("SELECT * FROM chain_txs ORDER BY created_at")
            ],
            "anchor_payouts": [
                dict(r)
                for r in conn.execute("SELECT * FROM anchor_payouts ORDER BY created_at")
            ],
        }
    finally:
        conn.close()
    state["trust"] = trust_state()
    return state


def read_events(db_path: str, limit: int = 100) -> list[dict]:
    conn = connect_ro(db_path)
    try:
        return [
            {
                "name": r["name"],
                "payload": json.loads(r["payload"]),
                "created_at": r["created_at"],
            }
            for r in conn.execute(
                "SELECT * FROM events ORDER BY rowid DESC LIMIT ?", (limit,)
            )
        ]
    finally:
        conn.close()


def read_metrics(db_path: str) -> dict:
    conn = connect_ro(db_path)
    try:
        return metrics.snapshot(conn)
    finally:
        conn.close()


class StateHandler(BaseHTTPRequestHandler):
    db_path = "amanah.db"

    def do_GET(self):
        try:
            if self.path == "/api/state":
                self._json(read_state(self.db_path))
            elif self.path == "/api/events":
                self._json(read_events(self.db_path))
            elif self.path == "/api/metrics":
                self._json(read_metrics(self.db_path))
            elif self.path == "/metrics":
                body = metrics.render_prometheus(read_metrics(self.db_path)).encode()
                self._reply(200, "text/plain; version=0.0.4; charset=utf-8", body)
            elif self.path in ("/", "/index.html"):
                self._reply(200, "text/html; charset=utf-8", INDEX.read_bytes())
            else:
                self._reply(404, "text/plain", b"not found")
        except sqlite3.Error as exc:
            self._reply(500, "application/json", json.dumps({"error": str(exc)}).encode())

    def _json(self, data):
        self._reply(200, "application/json", json.dumps(data).encode())

    def _reply(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(db_path: str, port: int = 8787):
    handler = type("Handler", (StateHandler,), {"db_path": db_path})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"amanah ui on http://127.0.0.1:{port} (db={db_path})")
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="amanah.db")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    serve(args.db, args.port)
