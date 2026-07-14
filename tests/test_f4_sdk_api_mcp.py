import json
import os
import subprocess
import sys
import threading
from http.server import HTTPServer
from pathlib import Path

import httpx
import pytest

from lumo import LumoClient, Decision
from lumo import mcp
from lumo.api import ApiHandler
from lumo.config import Config
from lumo.monitor.webhooks import MockSink

from conftest import FIXTURES, load_invoice

ROOT = Path(__file__).parent.parent
ORACLE = "GORACLEA" + "A" * 48


@pytest.fixture
def sdk(db_path):
    client = LumoClient(Config(db_path=str(db_path), oracle_address=ORACLE))
    yield client
    client.close()


@pytest.fixture
def api(db_path):
    sink = MockSink()
    handler = type(
        "Handler",
        (ApiHandler,),
        {"config": Config(db_path=str(db_path), oracle_address=ORACLE), "sink": sink},
    )
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = httpx.Client(base_url=f"http://127.0.0.1:{server.server_address[1]}")
    yield client, sink, handler
    client.close()
    server.shutdown()
    if handler.client is not None:
        handler.client.close()


def rpc(method, params=None, id=1):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}}


def tool_call(client, name, arguments):
    return mcp.handle(
        rpc("tools/call", {"name": name, "arguments": arguments}), client
    )


def tool_text(response):
    result = response["result"]
    assert result["isError"] is False
    return json.loads(result["content"][0]["text"])


def test_sdk_propose_status_roundtrip(sdk):
    decision = sdk.propose(load_invoice("clean_in_policy.txt"))
    assert isinstance(decision, Decision)
    assert decision.decision == "proposed"
    assert decision.intent_id

    row = sdk.status(decision.intent_id)
    assert row["status"] == "proposed"
    assert row["request_hash"] == decision.request_hash


def test_sdk_propose_accepts_path(sdk):
    decision = sdk.propose(FIXTURES / "clean_in_policy.txt")
    assert decision.decision == "proposed"


def test_sdk_propose_refused_over_cap(sdk):
    decision = sdk.propose(load_invoice("over_cap.txt"))
    assert decision.decision == "refused"
    assert decision.codes
    assert decision.intent_id is None


def test_sdk_status_unknown_returns_none(sdk):
    assert sdk.status("01JNOSUCHINTENT") is None


def test_sdk_attest_records_attestation(sdk):
    decision = sdk.propose(load_invoice("clean_in_policy.txt"))
    sdk.attest(decision.intent_id, "Shipped")

    rows = sdk.repo.attestations(decision.intent_id)
    assert len(rows) == 1
    assert rows[0]["kind"] == "Shipped"
    assert rows[0]["oracle_address"] == ORACLE
    assert rows[0]["request_hash"] == decision.request_hash


def test_sdk_attest_unknown_intent_raises(sdk):
    with pytest.raises(ValueError):
        sdk.attest("01JNOSUCHINTENT", "Shipped")


def test_sdk_on_event(sdk):
    seen = []
    sdk.on_event(lambda e: seen.append(e.name))
    sdk.propose(load_invoice("clean_in_policy.txt"))
    assert "intent.proposed" in seen


def test_sdk_metrics(sdk):
    sdk.propose(load_invoice("clean_in_policy.txt"))
    sdk.propose(load_invoice("over_cap.txt"))

    snap = sdk.metrics()
    assert snap["counters"]["proposed"] == 1
    assert snap["counters"]["refused"] == 1
    assert snap["gauges"]["intents_open"] == 1


def test_sdk_monitoring_toggle_off(db_path):
    client = LumoClient(Config(db_path=str(db_path), monitoring=False))
    seen = []
    client.on_event(lambda e: seen.append(e))
    client.propose(load_invoice("clean_in_policy.txt"))

    assert seen == []
    assert client.repo.events() == []
    client.close()


def test_api_propose_and_get_roundtrip(api):
    client, _, _ = api
    res = client.post("/v1/intents", json={"invoice": load_invoice("clean_in_policy.txt")})
    assert res.status_code == 200
    body = res.json()
    assert body["decision"] == "proposed"
    assert body["intent_id"]

    res = client.get(f"/v1/intents/{body['intent_id']}")
    assert res.status_code == 200
    assert res.json()["status"] == "proposed"
    assert res.json()["request_hash"] == body["request_hash"]


def test_api_refused_invoice_returns_decision(api):
    client, _, _ = api
    body = client.post("/v1/intents", json={"invoice": load_invoice("over_cap.txt")}).json()
    assert body["decision"] == "refused"
    assert body["codes"]


def test_api_propose_missing_invoice_400(api):
    client, _, _ = api
    assert client.post("/v1/intents", json={}).status_code == 400


def test_api_bad_json_400(api):
    client, _, _ = api
    res = client.post(
        "/v1/intents", content=b"not json", headers={"Content-Type": "application/json"}
    )
    assert res.status_code == 400


def test_api_get_unknown_404(api):
    client, _, _ = api
    assert client.get("/v1/intents/01JNOSUCHINTENT").status_code == 404


def test_api_attest_roundtrip(api):
    client, _, handler = api
    body = client.post("/v1/intents", json={"invoice": load_invoice("clean_in_policy.txt")}).json()

    res = client.post(f"/v1/intents/{body['intent_id']}/attest", json={"kind": "Shipped"})
    assert res.status_code == 200
    assert res.json() == {"intent_id": body["intent_id"], "attested": "Shipped"}

    rows = handler.client.repo.attestations(body["intent_id"])
    assert [r["kind"] for r in rows] == ["Shipped"]


def test_api_attest_bad_kind_400(api):
    client, _, _ = api
    body = client.post("/v1/intents", json={"invoice": load_invoice("clean_in_policy.txt")}).json()
    res = client.post(f"/v1/intents/{body['intent_id']}/attest", json={"kind": "Teleported"})
    assert res.status_code == 400


def test_api_attest_unknown_intent_404(api):
    client, _, _ = api
    res = client.post("/v1/intents/01JNOSUCHINTENT/attest", json={"kind": "Shipped"})
    assert res.status_code == 404


def test_api_metrics_shape(api):
    client, _, _ = api
    client.post("/v1/intents", json={"invoice": load_invoice("clean_in_policy.txt")})
    body = client.get("/v1/metrics").json()

    assert set(body) == {"counters", "gauges"}
    assert body["counters"]["proposed"] == 1


def test_api_openapi_doc(api):
    client, _, _ = api
    res = client.get("/v1/openapi.json")
    assert res.status_code == 200
    doc = res.json()
    assert doc["openapi"].startswith("3.")
    assert set(doc["paths"]) >= {
        "/v1/intents",
        "/v1/intents/{intent_id}",
        "/v1/intents/{intent_id}/attest",
        "/v1/metrics",
        "/v1/webhooks",
    }
    assert "Decision" in doc["components"]["schemas"]


def test_api_webhook_register_and_fires(api):
    client, sink, _ = api
    res = client.post("/v1/webhooks", json={"url": "http://8.8.8.8/lumo"})
    assert res.status_code == 200
    assert res.json() == {"urls": ["http://8.8.8.8/lumo"]}

    client.post("/v1/intents", json={"invoice": load_invoice("clean_in_policy.txt")})
    assert any(
        url == "http://8.8.8.8/lumo" and body["name"] == "intent.proposed"
        for url, body in sink.deliveries
    )


def test_api_webhook_missing_url_400(api):
    client, _, _ = api
    assert client.post("/v1/webhooks", json={}).status_code == 400


def test_mcp_tool_schemas():
    names = [t["name"] for t in mcp.TOOLS]
    assert names == ["lumo.propose_payment", "lumo.get_status", "lumo.attest"]
    for tool in mcp.TOOLS:
        assert tool["description"]
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert set(schema["required"]) <= set(schema["properties"])
        for prop in schema["properties"].values():
            assert prop["type"] == "string"

    by_name = {t["name"]: t for t in mcp.TOOLS}
    assert by_name["lumo.propose_payment"]["inputSchema"]["required"] == ["invoice_text"]
    assert by_name["lumo.get_status"]["inputSchema"]["required"] == ["intent_id"]
    attest = by_name["lumo.attest"]["inputSchema"]
    assert set(attest["required"]) == {"intent_id", "kind"}
    assert attest["properties"]["kind"]["enum"] == ["Shipped", "Failed"]


def test_mcp_initialize_and_list(sdk):
    init = mcp.handle(rpc("initialize"), sdk)
    assert init["id"] == 1
    assert init["result"]["protocolVersion"]
    assert init["result"]["serverInfo"]["name"] == "lumo"
    assert "tools" in init["result"]["capabilities"]

    listed = mcp.handle(rpc("tools/list", id=2), sdk)
    assert listed["result"]["tools"] == mcp.TOOLS


def test_mcp_call_propose_then_status(sdk):
    decision = tool_text(
        tool_call(sdk, "lumo.propose_payment", {"invoice_text": load_invoice("clean_in_policy.txt")})
    )
    assert decision["decision"] == "proposed"
    assert sdk.repo.intent(decision["intent_id"]) is not None

    status = tool_text(
        tool_call(sdk, "lumo.get_status", {"intent_id": decision["intent_id"]})
    )
    assert status["status"] == "proposed"


def test_mcp_call_refused_is_valid_decision(sdk):
    decision = tool_text(
        tool_call(sdk, "lumo.propose_payment", {"invoice_text": load_invoice("over_cap.txt")})
    )
    assert decision["decision"] == "refused"


def test_mcp_call_attest(sdk):
    decision = tool_text(
        tool_call(sdk, "lumo.propose_payment", {"invoice_text": load_invoice("clean_in_policy.txt")})
    )
    body = tool_text(
        tool_call(sdk, "lumo.attest", {"intent_id": decision["intent_id"], "kind": "Shipped"})
    )
    assert body == {"intent_id": decision["intent_id"], "attested": "Shipped"}
    assert [r["kind"] for r in sdk.repo.attestations(decision["intent_id"])] == ["Shipped"]


def test_mcp_call_unknown_intent_is_error(sdk):
    response = tool_call(sdk, "lumo.get_status", {"intent_id": "01JNOSUCHINTENT"})
    assert response["result"]["isError"] is True


def test_mcp_unknown_tool_error(sdk):
    response = tool_call(sdk, "lumo.teleport_funds", {})
    assert response["error"]["code"] == -32602


def test_mcp_unknown_method_error(sdk):
    response = mcp.handle(rpc("resources/list"), sdk)
    assert response["error"]["code"] == -32601


def test_mcp_notification_returns_none(sdk):
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert mcp.handle(note, sdk) is None


def example_env(tmp_path):
    return {
        **os.environ,
        "LUMO_DB": str(tmp_path / "example.db"),
        "LUMO_CONFIG": str(tmp_path / "missing.toml"),
        "LUMO_PROVIDER": "mock",
        "PYTHONPATH": str(ROOT),
    }


def test_example_sdk_runs(tmp_path):
    proc = subprocess.run(
        [sys.executable, "examples/sdk_propose.py"],
        cwd=ROOT, env=example_env(tmp_path), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "proposed" in proc.stdout


def test_example_rest_api_curl_runs(tmp_path, api):
    client, _, _ = api
    env = {**example_env(tmp_path), "LUMO_API": str(client.base_url)}
    proc = subprocess.run(
        ["bash", "examples/rest_curl.sh"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "proposed" in proc.stdout


def test_example_mcp_runs(tmp_path):
    proc = subprocess.run(
        [sys.executable, "examples/mcp_tool_call.py"],
        cwd=ROOT, env=example_env(tmp_path), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "lumo.propose_payment" in proc.stdout
    assert "proposed" in proc.stdout
