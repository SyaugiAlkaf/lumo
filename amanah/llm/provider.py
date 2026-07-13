from typing import Protocol

from amanah.models import ExtractedInvoice


class ExtractionProvider(Protocol):
    def extract(self, invoice_text: str) -> ExtractedInvoice: ...
