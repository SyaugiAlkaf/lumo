import re
import threading
from http.server import ThreadingHTTPServer

import httpx
import pytest

from lumo import flow, pipeline
from lumo.chain.mock_chain import MockChainAdapter
from lumo.config import Config
from lumo.db.repo import Repo
from lumo.db.seed import SME_ADDRESS, TOKEN_ADDRESS
from lumo.llm.mock import MockProvider
from lumo.monitor.events import Event, EventBus
from lumo.monitor.metrics import COUNTERS, Metrics, render_prometheus, snapshot
from lumo.monitor.webhooks import MockSink, WebhookDispatcher, build_webhooks
from lumo.ui.server import StateHandler

from conftest import load_invoice

AMOUNT = 12_500_000_000
FUNDING = 4 * AMOUNT

PROM_SAMPLE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]* -?[0-9]+(\.[0-9]+)?$")


def funded_mock_chain():
    chain = MockChainAdapter()
    chain.deploy()
    chain.fund(TOKEN_ADDRESS, SME_ADDRESS, FUNDING)
    return chain


def escrow_via_pipeline(repo, config, chain):
    result = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    assert result.decision == "proposed"
    flow.execute(repo, chain, result.intent_id, "sme", config)
    return result.intent_id


def event_names(repo):
    return [r["name"] for r in repo.events()]


def test_proposed_emits_event(repo, config):
    seen = []
    repo.bus.subscribe(lambda e: seen.append(e))
    result = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)

    assert "intent.proposed" in event_names(repo)
    proposed = [e for e in seen if e.name == "intent.proposed"]
    assert len(proposed) == 1
    assert proposed[0].payload["request_hash"] == result.request_hash
    assert proposed[0].payload["intent_id"] == result.intent_id


def test_refusal_emits_refused_and_guard_tripped(repo, config):
    result = pipeline.run(load_invoice("over_cap.txt"), repo, MockProvider(), config)
    assert result.decision == "refused"

    names = event_names(repo)
    assert "intent.refused" in names
    tripped = [r for r in repo.events() if r["name"] == "guard.tripped"]
    assert any("PolicyEngineGuard" in r["payload"] for r in tripped)


def test_injection_emits_injection_blocked(repo, config):
    result = pipeline.run(load_invoice("inject_override.txt"), repo, MockProvider(), config)
    assert result.decision == "refused"

    names = event_names(repo)
    assert "injection.blocked" in names
    assert "intent.refused" in names


def test_held_emits_event(repo, db_path):
    config = Config(db_path=str(db_path), human_cosign_threshold=1)
    result = pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    assert result.decision == "held"
    assert "intent.held" in event_names(repo)


def test_flow_transitions_emit_events(repo, config):
    chain = funded_mock_chain()
    intent_id = escrow_via_pipeline(repo, config, chain)
    assert "intent.escrowed" in event_names(repo)

    flow.attest(repo, chain, intent_id, "Shipped", "GORACLEA" + "A" * 48, "oracle")
    assert flow.release(repo, chain, intent_id, "sme", config) == "released"
    assert "intent.released" in event_names(repo)


def test_revert_emits_reverted_and_refunded(repo, config):
    chain = funded_mock_chain()
    intent_id = escrow_via_pipeline(repo, config, chain)

    flow.attest(repo, chain, intent_id, "Failed", "GORACLEA" + "A" * 48, "oracle")
    assert flow.revert(repo, chain, intent_id, "sme") == "reverted"

    names = event_names(repo)
    assert "intent.reverted" in names
    assert "intent.refunded" in names


def test_monitoring_toggle_off_emits_nothing(conn, config):
    repo = Repo(conn, bus=EventBus(enabled=False))
    seen = []
    repo.bus.subscribe(lambda e: seen.append(e))
    pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)

    assert repo.events() == []
    assert seen == []


def test_metrics_counters_increment(repo, config):
    metrics = Metrics()
    repo.bus.subscribe(metrics)
    pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    pipeline.run(load_invoice("over_cap.txt"), repo, MockProvider(), config)
    pipeline.run(load_invoice("inject_override.txt"), repo, MockProvider(), config)

    assert metrics.counters["proposed"] == 1
    assert metrics.counters["refused"] == 2
    assert metrics.counters["injection_blocked"] == 1
    assert metrics.counters["held"] == 0
    assert metrics.counters["released"] == 0


def test_snapshot_counters_and_gauges(repo, config, conn):
    chain = funded_mock_chain()
    intent_id = escrow_via_pipeline(repo, config, chain)

    snap = snapshot(conn)
    assert set(snap["counters"]) == set(COUNTERS)
    assert snap["counters"]["proposed"] == 1
    assert snap["gauges"]["escrowed_value"] == AMOUNT
    assert snap["gauges"]["intents_open"] == 1

    flow.attest(repo, chain, intent_id, "Shipped", "GORACLEA" + "A" * 48, "oracle")
    flow.release(repo, chain, intent_id, "sme", config)
    snap = snapshot(conn)
    assert snap["counters"]["released"] == 1
    assert snap["gauges"]["escrowed_value"] == 0
    assert snap["gauges"]["intents_open"] == 0


def test_render_prometheus_valid_text(conn, repo, config):
    pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    text = render_prometheus(snapshot(conn))

    assert "lumo_intents_proposed_total 1" in text
    assert "lumo_intents_open" in text
    for line in text.strip().splitlines():
        if line.startswith("# HELP ") or line.startswith("# TYPE "):
            continue
        assert PROM_SAMPLE.match(line), f"bad prometheus sample line: {line!r}"


def test_webhook_retries_then_delivers():
    sink = MockSink(fail_times=2)
    dispatcher = WebhookDispatcher(["http://8.8.8.8/lumo"], sink)
    dispatcher(Event(name="intent.proposed", payload={"intent_id": "01J"}))

    assert sink.attempts == 3
    assert len(sink.deliveries) == 1
    url, body = sink.deliveries[0]
    assert url == "http://8.8.8.8/lumo"
    assert body["name"] == "intent.proposed"
    assert body["payload"]["intent_id"] == "01J"


def test_webhook_gives_up_after_retries():
    sink = MockSink(fail_times=10)
    dispatcher = WebhookDispatcher(["http://8.8.8.8/lumo"], sink)
    dispatcher(Event(name="intent.refused", payload={}))
    assert sink.deliveries == []


def test_build_webhooks_config_driven():
    assert build_webhooks(Config()) is None
    sink = MockSink()
    dispatcher = build_webhooks(
        Config(webhook_urls="http://8.8.8.8/a, http://8.8.4.4/b"), sink=sink
    )
    assert dispatcher.urls == ["http://8.8.8.8/a", "http://8.8.4.4/b"]


def test_webhook_fires_on_pipeline_event(repo, config):
    sink = MockSink()
    repo.bus.subscribe(
        build_webhooks(Config(webhook_urls="http://8.8.8.8/lumo"), sink=sink)
    )
    pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)

    assert any(body["name"] == "intent.proposed" for _, body in sink.deliveries)


@pytest.fixture
def ui_client(db_path, conn):
    handler = type("Handler", (StateHandler,), {"db_path": str(db_path)})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = httpx.Client(base_url=f"http://127.0.0.1:{server.server_address[1]}")
    yield client
    client.close()
    server.shutdown()


def test_metrics_endpoint_prometheus(repo, config, ui_client):
    pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    res = ui_client.get("/metrics")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    assert "lumo_intents_proposed_total 1" in res.text


def test_api_metrics_json_shape(repo, config, ui_client):
    pipeline.run(load_invoice("clean_in_policy.txt"), repo, MockProvider(), config)
    body = ui_client.get("/api/metrics").json()

    assert set(body) == {"counters", "gauges"}
    assert set(body["counters"]) == {
        "proposed", "refused", "injection_blocked", "held",
        "released", "reverted", "refunded",
    }
    assert set(body["gauges"]) == {"escrowed_value", "intents_open"}
    assert all(isinstance(v, int) for v in body["counters"].values())
    assert all(isinstance(v, int) for v in body["gauges"].values())


def test_api_events_recent(repo, config, ui_client):
    pipeline.run(load_invoice("over_cap.txt"), repo, MockProvider(), config)
    events = ui_client.get("/api/events").json()

    assert isinstance(events, list)
    assert events, "expected recent events"
    assert set(events[0]) == {"name", "payload", "created_at"}
    assert events[0]["name"] == "intent.refused"
    assert any(e["name"] == "guard.tripped" for e in events)
