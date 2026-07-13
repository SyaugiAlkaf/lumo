import json
from pathlib import Path
from unittest.mock import patch

import pytest

from amanah.chain import soroban_client
from amanah.chain.soroban_client import (
    CREATE_INTENT_ARG_ORDER,
    InvokeResult,
    SorobanClient,
    build_invoke_cmd,
    encode_enum,
    encode_i128,
    variant_of,
)

BINDINGS = Path(__file__).parent.parent / "bindings" / "escrow.json"


def test_unit_enum_encodes_as_bare_json_string():
    assert encode_enum("Shipped") == '"Shipped"'
    assert encode_enum("Failed") == '"Failed"'


def test_scalar_enum_encodes_as_bare_scalar_not_array():
    # Known-good Padala invocation: --lock '{"Time":1782672147}'.
    # The array form {"Time":[...]} fails CLI parsing ("Expected type vector").
    assert encode_enum("Time", 1782672147) == '{"Time":1782672147}'


def test_i128_encodes_as_string():
    assert encode_i128(20_000_000_000) == "20000000000"
    assert encode_i128(12_500_000_000) == "12500000000"


def test_create_intent_arg_order_matches_frozen_binding():
    spec = json.loads(BINDINGS.read_text())
    create = next(
        e["function_v0"]
        for e in spec
        if "function_v0" in e and e["function_v0"]["name"] == "create_intent"
    )
    assert tuple(i["name"] for i in create["inputs"]) == CREATE_INTENT_ARG_ORDER


def test_build_invoke_cmd_shape():
    cmd = build_invoke_cmd(
        "CESCROW", "amanah-sme", "local", "attest",
        [("intent_id", "1"), ("oracle", "GORACLE"), ("kind", '"Shipped"')],
    )
    assert cmd == [
        "stellar", "contract", "invoke",
        "--id", "CESCROW",
        "--source-account", "amanah-sme",
        "--network", "local",
        "--", "attest",
        "--intent_id", "1",
        "--oracle", "GORACLE",
        "--kind", '"Shipped"',
    ]


def test_create_intent_invocation_matches_known_good_form():
    client = SorobanClient("CESCROW", network="local", source="amanah-sme")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class P:
            returncode = 0
            stdout = "1\n"
            stderr = "Transaction hash is " + "ab" * 32

        return P()

    with patch.object(soroban_client.subprocess, "run", fake_run):
        result = client.create_intent(
            sme="GSME",
            supplier="GSUPPLIER",
            token="CTOKEN",
            amount=12_500_000_000,
            request_hash="cd" * 32,
            deadline=1782672147,
        )

    assert result == InvokeResult(value=1, tx_hash="ab" * 32)
    tail = captured["cmd"][captured["cmd"].index("--") + 1 :]
    assert tail == [
        "create_intent",
        "--sme", "GSME",
        "--supplier", "GSUPPLIER",
        "--token", "CTOKEN",
        "--amount", "12500000000",
        "--request_hash", "cd" * 32,
        "--deadline", "1782672147",
    ]


def test_variant_of_handles_bare_string_and_single_key_map():
    assert variant_of("Funded") == "Funded"
    assert variant_of({"Released": []}) == "Released"
    with pytest.raises(soroban_client.SorobanError):
        variant_of({"A": 1, "B": 2})
