import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

INDEX = Path(__file__).parent / "index.html"


def read_state(db_path: str) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
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
    return state


class StateHandler(BaseHTTPRequestHandler):
    db_path = "amanah.db"

    def do_GET(self):
        if self.path == "/api/state":
            try:
                body = json.dumps(read_state(self.db_path)).encode()
                self._reply(200, "application/json", body)
            except sqlite3.Error as exc:
                self._reply(500, "application/json", json.dumps({"error": str(exc)}).encode())
        elif self.path in ("/", "/index.html"):
            self._reply(200, "text/html; charset=utf-8", INDEX.read_bytes())
        else:
            self._reply(404, "text/plain", b"not found")

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
