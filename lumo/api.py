import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lumo.config import Config
from lumo.models import PipelineResult
from lumo.monitor.webhooks import HttpSink, WebhookDispatcher
from lumo.sdk import ATTEST_KINDS, LumoClient

INTENT_PATH = re.compile(r"^/v1/intents/([^/]+)$")
ATTEST_PATH = re.compile(r"^/v1/intents/([^/]+)/attest$")

MAX_BODY_BYTES = 1024 * 1024


class _PayloadTooLarge(Exception):
    pass


OPENAPI = {
    "openapi": "3.0.3",
    "info": {
        "title": "Lumo API",
        "version": "0.1.0",
        "description": "Propose invoice payments through the Lumo guard chain.",
    },
    "paths": {
        "/v1/intents": {
            "post": {
                "summary": "Run an invoice through the pipeline and record a decision",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"invoice": {"type": "string"}},
                                "required": ["invoice"],
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Decision (proposed, held, or refused)",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Decision"}
                            }
                        },
                    }
                },
            }
        },
        "/v1/intents/{intent_id}": {
            "get": {
                "summary": "Fetch a stored intent",
                "parameters": [
                    {
                        "name": "intent_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {"description": "Intent row"},
                    "404": {"description": "Unknown intent"},
                },
            }
        },
        "/v1/intents/{intent_id}/attest": {
            "post": {
                "summary": "Record an oracle attestation for an intent",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "kind": {"type": "string", "enum": list(ATTEST_KINDS)}
                                },
                                "required": ["kind"],
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Attestation recorded"},
                    "404": {"description": "Unknown intent"},
                },
            }
        },
        "/v1/metrics": {
            "get": {"summary": "Counters and gauges snapshot", "responses": {"200": {"description": "Metrics"}}}
        },
        "/v1/webhooks": {
            "post": {
                "summary": "Register a webhook URL for pipeline events",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"url": {"type": "string"}},
                                "required": ["url"],
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "Registered URLs"}},
            }
        },
    },
    "components": {"schemas": {"Decision": PipelineResult.model_json_schema()}},
}


class ApiHandler(BaseHTTPRequestHandler):
    config: Config | None = None
    client: LumoClient | None = None
    dispatcher: WebhookDispatcher | None = None
    sink = None

    def _client(self) -> LumoClient:
        cls = type(self)
        if cls.client is None:
            cls.client = LumoClient(cls.config)
        return cls.client

    def _dispatcher(self) -> WebhookDispatcher:
        cls = type(self)
        if cls.dispatcher is None:
            cls.dispatcher = WebhookDispatcher([], cls.sink or HttpSink())
            self._client().on_event(cls.dispatcher)
        return cls.dispatcher

    def _body(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length header is required")
        try:
            length = int(raw_length)
        except ValueError:
            raise ValueError("Content-Length must be an integer") from None
        if length < 0:
            raise ValueError("Content-Length must not be negative")
        if length > MAX_BODY_BYTES:
            raise _PayloadTooLarge(f"body exceeds {MAX_BODY_BYTES} byte limit")
        raw = self.rfile.read(length)
        body = json.loads(raw) if raw else {}
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        return body

    def do_GET(self):
        if self.path == "/v1/metrics":
            return self._json(200, self._client().metrics())
        if self.path == "/v1/openapi.json":
            return self._json(200, OPENAPI)
        match = INTENT_PATH.match(self.path)
        if match:
            row = self._client().status(match.group(1))
            if row is None:
                return self._json(404, {"error": "unknown intent"})
            return self._json(200, row)
        self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = self._body()
        except _PayloadTooLarge as exc:
            return self._json(413, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": str(exc)})

        try:
            if self.path == "/v1/intents":
                invoice = body.get("invoice")
                if not isinstance(invoice, str) or not invoice:
                    return self._json(400, {"error": "invoice (string) is required"})
                decision = self._client().propose(invoice)
                return self._json(200, decision.model_dump())

            if self.path == "/v1/webhooks":
                url = body.get("url")
                if not isinstance(url, str) or not url:
                    return self._json(400, {"error": "url (string) is required"})
                dispatcher = self._dispatcher()
                if url not in dispatcher.urls:
                    dispatcher.urls.append(url)
                return self._json(200, {"urls": dispatcher.urls})

            match = ATTEST_PATH.match(self.path)
            if match:
                kind = body.get("kind")
                if kind not in ATTEST_KINDS:
                    return self._json(400, {"error": f"kind must be one of {list(ATTEST_KINDS)}"})
                intent_id = match.group(1)
                if self._client().status(intent_id) is None:
                    return self._json(404, {"error": "unknown intent"})
                self._client().attest(intent_id, kind)
                return self._json(200, {"intent_id": intent_id, "attested": kind})

            self._json(404, {"error": "not found"})
        except Exception:
            self._json(500, {"error": "internal server error"})

    def _json(self, code: int, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(config: Config | None = None):
    config = config or Config.from_env()
    handler = type("Handler", (ApiHandler,), {"config": config})
    server = ThreadingHTTPServer((config.api_host, config.api_port), handler)
    print(f"lumo api on http://{config.api_host}:{config.api_port} (db={config.db_path})")
    server.serve_forever()


if __name__ == "__main__":
    serve()
