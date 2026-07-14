import http.client
import threading
from http.server import HTTPServer

import httpx
import pytest

from lumo import mcp
from lumo.chain.mock_chain import MockChainAdapter
from lumo.config import Config
from lumo.db.seed import SME_ADDRESS, TOKEN_ADDRESS
from lumo.sdk import LumoClient
from lumo.ui import server as ui_server
from lumo.ui.server import StateHandler

from conftest import load_invoice


def rpc(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


@pytest.fixture
def sdk(db_path):
    client = LumoClient(Config(db_path=str(db_path)))
    yield client
    client.close()


def test_mcp_propose_payment_non_string_invoice_returns_error_not_crash(sdk):
    response = mcp.handle(
        rpc("tools/call", {"name": "lumo.propose_payment", "arguments": {"invoice_text": 12345}}),
        sdk,
    )
    assert response["result"]["isError"] is True
    assert "string" in response["result"]["content"][0]["text"]


def test_mcp_propose_payment_non_string_container_returns_error_not_crash(sdk):
    response = mcp.handle(
        rpc("tools/call", {"name": "lumo.propose_payment", "arguments": {"invoice_text": ["x"]}}),
        sdk,
    )
    assert response["result"]["isError"] is True


def test_mcp_call_arguments_not_object_returns_error_not_crash(sdk):
    response = mcp.handle(
        rpc("tools/call", {"name": "lumo.propose_payment", "arguments": "invoice_text"}),
        sdk,
    )
    assert response["result"]["isError"] is True


@pytest.fixture
def adapter():
    chain = MockChainAdapter()
    chain.fund(TOKEN_ADDRESS, SME_ADDRESS, 10_000_000_000_000)
    return chain


@pytest.fixture
def mock_config(db_path):
    return Config(db_path=str(db_path), chain_adapter="mock")


@pytest.fixture
def testnet_client(conn, db_path, mock_config, adapter):
    handler = type(
        "Handler",
        (StateHandler,),
        {"db_path": str(db_path), "config": mock_config, "chain_adapter": adapter},
    )
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{server.server_address[1]}", timeout=30
    )
    yield client, server.server_address[1]
    client.close()
    server.shutdown()


def test_testnet_run_internal_error_returns_generic_body(testnet_client, monkeypatch):
    client, _ = testnet_client
    leak_marker = "internal detail /etc/lumo/db path should-not-appear"

    def boom(*args, **kwargs):
        raise RuntimeError(leak_marker)

    monkeypatch.setattr(ui_server.testtool, "run_invoice", boom)

    resp = client.post(
        "/testnet/run", json={"invoice_text": load_invoice("clean_in_policy.txt")}
    )
    assert resp.status_code == 500
    assert leak_marker not in resp.text
    assert "RuntimeError" not in resp.text
    assert resp.json() == {"error": "internal error"}


def test_testnet_run_bad_content_length_returns_400_without_crashing(testnet_client):
    _, port = testnet_client

    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.putrequest("POST", "/testnet/run", skip_host=True)
    conn.putheader("Content-Length", "not-a-number")
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 400
    resp.read()
    conn.close()

    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.putrequest("POST", "/testnet/run", skip_host=True)
    conn.putheader("Content-Length", "999999999")
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 400
    resp.read()
    conn.close()

    client, _ = testnet_client
    resp = client.post(
        "/testnet/run", json={"invoice_text": load_invoice("clean_in_policy.txt")}
    )
    assert resp.status_code == 200
