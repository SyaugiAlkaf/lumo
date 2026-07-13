import httpx

from amanah.llm.prompts import EXTRACTION_SCHEMA, extraction_messages
from amanah.models import ExtractedInvoice


class LlamaServerProvider:
    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: float = 120.0,
                 client: httpx.Client | None = None):
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def extract(self, invoice_text: str) -> ExtractedInvoice:
        resp = self.client.post(
            "/v1/chat/completions",
            json={
                "messages": extraction_messages(invoice_text),
                "temperature": 0,
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
