import hashlib
import json


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def request_hash(intent_fields: dict) -> str:
    return hashlib.sha256(canonical_json(intent_fields)).hexdigest()
