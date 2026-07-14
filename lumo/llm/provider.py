from typing import Protocol

from lumo.models import ExtractedInvoice


class ExtractionProvider(Protocol):
    def extract(self, invoice_text: str) -> ExtractedInvoice: ...
