import re
import threading
from http.server import HTTPServer

import httpx
import pytest

from lumo.chain.mock_chain import MockChainAdapter
from lumo.config import Config
from lumo.db.seed import SME_ADDRESS, TOKEN_ADDRESS
from lumo.testtool import EXPLORER_TX, run_invoice
from lumo.ui.server import StateHandler

from conftest import load_invoice

HASH_RX = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture
def adapter():
    chain = MockChainAdapter()
    chain.fund(TOKEN_ADDRESS, SME_ADDRESS, 10_000_000_000_000)
    return chain


@pytest.fixture
def mock_config(db_path):
    return Config(db_path=str(db_path), chain_adapter="mock")


def test_clean_invoice_proposes_with_full_tx_trail(conn, mock_config, adapter):
    result = run_invoice(load_invoice("clean_in_policy.txt"), mock_config, adapter=adapter)
    assert result["decision"] == "proposed"
    assert result["codes"] == ["OK"]
    assert [tx["step"] for tx in result["txs"]] == ["create_intent", "attest", "release"]
    for tx in result["txs"]:
        assert HASH_RX.match(tx["hash"])
        assert tx["url"] == EXPLORER_TX + tx["hash"]


def test_over_cap_invoice_refused_with_no_tx(conn, mock_config, adapter):
    result = run_invoice(load_invoice("over_cap.txt"), mock_config, adapter=adapter)
    assert result["decision"] == "refused"
    assert "OVER_TX_CAP" in result["codes"]
    assert result["txs"] == []
    assert adapter.intents == {}


def test_injection_invoice_blocked_with_flags_and_no_tx(conn, mock_config, adapter):
    result = run_invoice(load_invoice("inject_override.txt"), mock_config, adapter=adapter)
    assert result["decision"] == "refused"
    assert "INJECTION_SUSPECTED" in result["codes"]
    assert result["flags"]
    assert result["txs"] == []
    assert adapter.intents == {}


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
    yield client
    client.close()
    server.shutdown()


def test_testnet_run_endpoint_clean(testnet_client):
    resp = testnet_client.post(
        "/testnet/run", json={"invoice_text": load_invoice("clean_in_policy.txt")}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "proposed"
    assert [tx["step"] for tx in data["txs"]] == ["create_intent", "attest", "release"]
    assert all(HASH_RX.match(tx["hash"]) for tx in data["txs"])


def test_testnet_run_endpoint_refuses_injection(testnet_client):
    resp = testnet_client.post(
        "/testnet/run", json={"invoice_text": load_invoice("inject_override.txt")}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "refused"
    assert "INJECTION_SUSPECTED" in data["codes"]
    assert data["txs"] == []


def test_testnet_run_endpoint_rejects_empty_body(testnet_client):
    resp = testnet_client.post("/testnet/run", json={})
    assert resp.status_code == 400


def test_testnet_page_and_info(testnet_client):
    page = testnet_client.get("/testnet")
    assert page.status_code == 200
    assert "Run on Stellar testnet" in page.text

    info = testnet_client.get("/testnet/info").json()
    assert info["chain_adapter"] == "mock"
    assert info["sme_address"] == SME_ADDRESS
    assert info["suppliers"][0]["name"] == "CV Batik Nusantara"
