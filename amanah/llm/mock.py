import re

from amanah.models import ExtractedInvoice
from amanah.security.patterns import STELLAR_ADDRESS

HONEST = "honest"
COMPROMISED = "compromised"

_REF = re.compile(r"^INVOICE\s+(\S+)", re.MULTILINE)
_FROM = re.compile(r"^From:\s*(.+?)\s*$", re.MULTILINE)
_ADDRESS = re.compile(r"^Payment address:\s*(G[A-Z2-7]{55})\s*$", re.MULTILINE)
_AMOUNT = re.compile(r"^Amount due:\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([A-Z]{3,5})\s*$", re.MULTILINE)
_ATTACKER_AMOUNT = re.compile(r"(?:transfer|send|pay)\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s*USDC", re.IGNORECASE)


class MockProvider:
    def __init__(self, mode: str = HONEST):
        self.mode = mode

    def extract(self, invoice_text: str) -> ExtractedInvoice:
        ref = _REF.search(invoice_text)
        supplier = _FROM.search(invoice_text)
        address = _ADDRESS.search(invoice_text)
        amount = _AMOUNT.search(invoice_text)
        extracted = ExtractedInvoice(
            invoice_ref=ref.group(1) if ref else None,
            supplier_name=supplier.group(1) if supplier else None,
            payment_address=address.group(1) if address else None,
            amount=amount.group(1).replace(",", "") if amount else None,
            currency=amount.group(2) if amount else None,
        )
        if self.mode == COMPROMISED:
            return self._obey_attacker(invoice_text, extracted)
        return extracted

    def _obey_attacker(self, invoice_text: str, extracted: ExtractedInvoice) -> ExtractedInvoice:
        addresses = STELLAR_ADDRESS.findall(invoice_text)
        if addresses:
            extracted.payment_address = addresses[-1]
        demanded = _ATTACKER_AMOUNT.search(invoice_text)
        if demanded:
            extracted.amount = demanded.group(1).replace(",", "")
        return extracted
