import tomllib
from pathlib import Path

import pytest

from lumo.config import Config

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def test_invalid_chain_adapter_raises_at_construction():
    with pytest.raises(ValueError, match="chain_adapter"):
        Config(chain_adapter="cosmos")


def test_invalid_chain_adapter_raises_at_file_load(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('chain_adapter = "cosmos"\n')
    with pytest.raises(ValueError, match="chain_adapter"):
        Config.from_file(bad)


def test_valid_configs_still_load(tmp_path):
    assert Config().chain_adapter == "soroban"
    assert Config(chain_adapter="mock").chain_adapter == "mock"
    assert Config(chain_adapter="evm").chain_adapter == "evm"
    good = tmp_path / "good.toml"
    good.write_text('chain_adapter = "soroban"\nk_of_n = 1\n')
    assert Config.from_file(good).chain_adapter == "soroban"


def test_out_of_range_numeric_field_raises():
    with pytest.raises(ValueError, match="api_port"):
        Config(api_port=0)
    with pytest.raises(ValueError, match="k_of_n"):
        Config(k_of_n=0)


def test_pyproject_pins_pydantic_and_httpx_with_bounds():
    deps = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    pydantic_spec = next(d for d in deps if d.startswith("pydantic"))
    httpx_spec = next(d for d in deps if d.startswith("httpx"))
    for spec in (pydantic_spec, httpx_spec):
        assert "<" in spec, f"{spec!r} has no upper bound"
        assert ">=" in spec or "==" in spec, f"{spec!r} has no lower bound"
