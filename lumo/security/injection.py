import unicodedata

from lumo.models import ScanResult
from lumo.security.patterns import PATTERNS, STELLAR_ADDRESS, ZERO_WIDTH

# Cyrillic look-alikes NFKC leaves untouched (distinct script, not a
# compatibility decomposition) but attackers use to dodge ASCII-literal
# keyword matching, e.g. "ignоre" rendering identically to "ignore".
_HOMOGLYPHS = str.maketrans(
    {
        "а": "a", "А": "A",
        "е": "e", "Е": "E",
        "о": "o", "О": "O",
        "р": "p", "Р": "P",
        "с": "c", "С": "C",
        "х": "x", "Х": "X",
        "у": "y", "У": "Y",
        "і": "i", "І": "I",
        "ѕ": "s", "Ѕ": "S",
        "ј": "j", "Ј": "J",
    }
)


def normalize(text: str) -> tuple[str, bool]:
    nfkc = unicodedata.normalize("NFKC", text)
    stripped = nfkc.translate({ord(c): None for c in ZERO_WIDTH})
    had_hidden = stripped != nfkc
    folded = stripped.translate(_HOMOGLYPHS)
    return folded, had_hidden


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
