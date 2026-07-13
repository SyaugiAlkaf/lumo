import os
import time

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new(timestamp_ms: int | None = None) -> str:
    ts = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    value = (ts << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for shift in range(125, -1, -5):
        chars.append(ALPHABET[(value >> shift) & 0x1F])
    return "".join(chars)


def timestamp_ms(ulid: str) -> int:
    value = 0
    for ch in ulid:
        value = (value << 5) | ALPHABET.index(ch)
    return value >> 80
