import httpx

from amanah.config import Config
from amanah.monitor.events import Event

ATTEMPTS = 3


class MockSink:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.attempts = 0
        self.deliveries: list[tuple[str, dict]] = []

    def post(self, url: str, body: dict) -> None:
        self.attempts += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("mock sink failure")
        self.deliveries.append((url, body))


class HttpSink:
    def post(self, url: str, body: dict) -> None:
        httpx.post(url, json=body, timeout=5.0).raise_for_status()


class WebhookDispatcher:
    def __init__(self, urls: list[str], sink):
        self.urls = urls
        self.sink = sink

    def __call__(self, event: Event) -> None:
        body = {"name": event.name, "payload": event.payload, "at": event.at}
        for url in self.urls:
            # delivery failure must never block the money path: retry, then drop
            for _ in range(ATTEMPTS):
                try:
                    self.sink.post(url, body)
                    break
                except Exception:
                    continue


def build_webhooks(config: Config, sink=None) -> WebhookDispatcher | None:
    urls = [u.strip() for u in config.webhook_urls.split(",") if u.strip()]
    if not urls:
        return None
    return WebhookDispatcher(urls, sink or HttpSink())
