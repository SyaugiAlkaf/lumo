import json
import socket
import threading
from http.server import ThreadingHTTPServer

import pytest

from lumo import api
from lumo.api import ApiHandler
from lumo.config import Config


def _raw_post(port, path, headers, body=b""):
    lines = [f"POST {path} HTTP/1.1", f"Host: 127.0.0.1:{port}", "Connection: close"]
    for key, value in headers.items():
        lines.append(f"{key}: {value}")
    head = "\r\n".join(lines) + "\r\n\r\n"
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(head.encode() + body)
        sock.settimeout(5)
        chunks = []
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except (socket.timeout, ConnectionResetError):
            pass
    return b"".join(chunks)


def _status_and_json(raw):
    header_part, _, body_part = raw.partition(b"\r\n\r\n")
    status_line = header_part.split(b"\r\n")[0].decode()
    code = int(status_line.split()[1])
    parsed = json.loads(body_part) if body_part else None
    return code, parsed


@pytest.fixture
def server(db_path):
    handler = type("Handler", (ApiHandler,), {"config": Config(db_path=str(db_path))})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    thread.join(timeout=5)
    if handler.client is not None:
        handler.client.close()


def test_oversized_content_length_rejected_413(server):
    port = server.server_address[1]
    raw = _raw_post(
        port,
        "/v1/intents",
        {"Content-Type": "application/json", "Content-Length": str(2 * 1024 * 1024)},
    )
    code, _ = _status_and_json(raw)
    assert code == 413


def test_non_integer_content_length_rejected_400(server):
    port = server.server_address[1]
    raw = _raw_post(
        port,
        "/v1/intents",
        {"Content-Type": "application/json", "Content-Length": "not-a-number"},
    )
    code, _ = _status_and_json(raw)
    assert code == 400


def test_negative_content_length_rejected_400(server):
    port = server.server_address[1]
    raw = _raw_post(
        port,
        "/v1/intents",
        {"Content-Type": "application/json", "Content-Length": "-1"},
    )
    code, _ = _status_and_json(raw)
    assert code == 400


def test_pipeline_error_returns_generic_500_without_leaking_details(db_path):
    leak_marker = "internal-detail-should-not-appear"

    class ExplodingClient:
        def propose(self, invoice):
            raise RuntimeError(leak_marker)

    class ExplodingHandler(ApiHandler):
        config = Config(db_path=str(db_path))

        def _client(self):
            return ExplodingClient()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ExplodingHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        body = json.dumps({"invoice": "irrelevant"}).encode()
        raw = _raw_post(
            port,
            "/v1/intents",
            {"Content-Type": "application/json", "Content-Length": str(len(body))},
            body,
        )
        code, parsed = _status_and_json(raw)
        assert code == 500
        assert leak_marker not in raw.decode(errors="replace")
        assert "Traceback" not in raw.decode(errors="replace")
        assert isinstance(parsed, dict)
        assert leak_marker not in parsed.get("error", "")
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def test_serve_constructs_threading_http_server(monkeypatch, tmp_path):
    calls = {}

    class FakeServer:
        def __init__(self, address, handler):
            calls["address"] = address
            calls["handler"] = handler

        def serve_forever(self):
            calls["served"] = True

    monkeypatch.setattr(api, "ThreadingHTTPServer", FakeServer)
    cfg = Config(db_path=str(tmp_path / "lumo.db"), api_host="127.0.0.1", api_port=18788)
    api.serve(cfg)

    assert calls["served"] is True
    assert calls["address"] == ("127.0.0.1", 18788)
