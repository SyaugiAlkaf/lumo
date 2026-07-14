import pytest

from lumo.config import Config
from lumo.monitor.events import Event
from lumo.monitor.webhooks import (
    MockSink,
    WebhookDispatcher,
    WebhookURLError,
    build_webhooks,
)

BLOCKED_URLS = [
    "http://127.0.0.1/hook",
    "http://localhost/hook",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/hook",
    "file:///etc/passwd",
]

PUBLIC_URL = "http://8.8.8.8/hook"


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_registration_rejects_blocked_url(url):
    dispatcher = WebhookDispatcher([], MockSink())
    with pytest.raises(WebhookURLError):
        dispatcher.register(url)
    assert url not in dispatcher.urls


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_build_webhooks_rejects_blocked_url(url):
    with pytest.raises(WebhookURLError):
        build_webhooks(Config(webhook_urls=url), sink=MockSink())


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_dispatch_never_delivers_to_blocked_url(url):
    sink = MockSink()
    # bypass register() so dispatch-time validation is what's actually under test
    dispatcher = WebhookDispatcher([url], sink)
    dispatcher(Event(name="intent.proposed", payload={"intent_id": "01J"}))

    assert sink.deliveries == []
    assert sink.attempts == 0


def test_registration_allows_public_url():
    dispatcher = WebhookDispatcher([], MockSink())
    dispatcher.register(PUBLIC_URL)
    assert dispatcher.urls == [PUBLIC_URL]


def test_dispatch_delivers_to_public_url():
    sink = MockSink()
    dispatcher = WebhookDispatcher([PUBLIC_URL], sink)
    dispatcher(Event(name="intent.proposed", payload={"intent_id": "01J"}))

    assert sink.attempts == 1
    assert len(sink.deliveries) == 1
    url, body = sink.deliveries[0]
    assert url == PUBLIC_URL
    assert body["name"] == "intent.proposed"
    assert body["payload"]["intent_id"] == "01J"


def test_build_webhooks_allows_public_url():
    sink = MockSink()
    dispatcher = build_webhooks(Config(webhook_urls=PUBLIC_URL), sink=sink)
    assert dispatcher.urls == [PUBLIC_URL]
