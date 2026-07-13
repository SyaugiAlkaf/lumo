import unicodedata

from amanah.models import ScanResult
from amanah.security.patterns import PATTERNS, STELLAR_ADDRESS, ZERO_WIDTH


def normalize(text: str) -> tuple[str, bool]:
    nfkc = unicodedata.normalize("NFKC", text)
    stripped = nfkc.translate({ord(c): None for c in ZERO_WIDTH})
    return stripped, stripped != nfkc


def scan(text: str) -> ScanResult:
    normalized, had_hidden = normalize(text)
    flags = ["HIDDEN_UNICODE"] if had_hidden else []
    for flag, rx in PATTERNS:
        if rx.search(normalized):
            flags.append(flag)
    return ScanResult(
        flags=flags,
        normalized_text=normalized,
        addresses=STELLAR_ADDRESS.findall(normalized),
    )
