import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from lumo.config import Config
from lumo.monitor.events import Event

ATTEMPTS = 3


class WebhookURLError(ValueError):
    """A webhook URL that is unsafe to call — bad scheme or a non-public host.

    Webhooks POST to a user-supplied URL on every event; without this an operator
    (or an injected config) could point them at localhost, 169.254.169.254, or an
    internal service and turn the event bus into a blind SSRF / exfil channel.
    """


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise WebhookURLError(f"unsupported scheme: {url!r}")
    host = parsed.hostname
    if not host:
        raise WebhookURLError(f"no host in url: {url!r}")
    try:
        infos = socket.getaddrinfo(host, parsed.port or None)
    except socket.gaierror as exc:
        raise WebhookURLError(f"cannot resolve host: {host!r}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise WebhookURLError(f"non-public address {ip} for {url!r}")


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
        self.urls = list(urls)
        self.sink = sink

    def register(self, url: str) -> None:
        _validate_url(url)
        self.urls.append(url)

    def __call__(self, event: Event) -> None:
        body = {"name": event.name, "payload": event.payload, "at": event.at}
        for url in self.urls:
            # Validate at dispatch too: a URL that slipped in some other way is
            # still never delivered to.
            try:
                _validate_url(url)
            except WebhookURLError:
                continue
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
    for url in urls:
        _validate_url(url)
    return WebhookDispatcher(urls, sink or HttpSink())
