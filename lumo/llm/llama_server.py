import httpx
from pydantic import ValidationError

from lumo.llm.prompts import EXTRACTION_SCHEMA, extraction_messages
from lumo.models import ExtractedInvoice


class LlamaServerProvider:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        timeout: float = 120.0,
        client: httpx.Client | None = None,
    ):
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def extract(self, invoice_text: str) -> ExtractedInvoice:
        try:
            resp = self.client.post(
                "/v1/chat/completions",
                json={
                    "messages": extraction_messages(invoice_text),
                    "temperature": 0,
                    "max_tokens": 512,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "extracted_invoice",
                            "strict": True,
                            "schema": EXTRACTION_SCHEMA,
                        },
                    },
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return ExtractedInvoice.model_validate_json(content)
        except (httpx.HTTPError, KeyError, IndexError, ValueError, ValidationError):
            # Fail closed. A transport error or garbled / truncated / non-JSON
            # model response yields an EMPTY extraction, so the deterministic
            # policy layer refuses — the pipeline never crashes and never
            # proposes a payment on top of a broken model output.
            return ExtractedInvoice()
