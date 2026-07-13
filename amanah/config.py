import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

ENV_NAMES = {"db_path": "AMANAH_DB"}

TRUTHY = ("1", "true", "yes", "on")

PROFILES = {
    "strict": {
        "injection_scan": True,
        "policy_engine": True,
        "policy_signer": True,
        "require_attestation": True,
        "k_of_n": 3,
        "human_cosign_threshold": 1_000_000_000,
        "proof_of_compute": True,
    },
    "balanced": {
        "injection_scan": True,
        "policy_engine": True,
        "policy_signer": True,
        "require_attestation": True,
        "k_of_n": 1,
        "human_cosign_threshold": 0,
        "proof_of_compute": False,
    },
    "fast": {
        "injection_scan": True,
        "policy_engine": True,
        "policy_signer": False,
        "require_attestation": False,
        "k_of_n": 1,
        "human_cosign_threshold": 0,
        "proof_of_compute": False,
    },
}


@dataclass
class Config:
    db_path: str = "amanah.db"
    provider: str = "mock"
    mock_mode: str = "honest"
    llama_url: str = "http://127.0.0.1:8080"
    deadline_secs: int = 3600
    escrow_id: str = ""
    network: str = "local"
    sme_source: str = "amanah-sme"
    oracle_source: str = "amanah-oracle"
    oracle_address: str = ""
    chain_adapter: str = "soroban"
    anchor_adapter: str = "mock"
    oracle_adapter: str = ""
    oracle_signers: str = ""
    injection_scan: bool = True
    policy_engine: bool = True
    policy_signer: bool = True
    require_attestation: bool = False
    k_of_n: int = 1
    human_cosign_threshold: int = 0
    proof_of_compute: bool = False
    dry_run: bool = False
    monitoring: bool = True
    webhook_urls: str = ""
    api_host: str = "127.0.0.1"
    api_port: int = 8788

    @classmethod
    def profile(cls, name: str, **overrides) -> "Config":
        if name not in PROFILES:
            raise ValueError(f"unknown profile {name!r}, expected one of: {', '.join(PROFILES)}")
        return cls(**{**PROFILES[name], **overrides})

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        return cls(**tomllib.loads(Path(path).read_text()))

    @classmethod
    def from_env(cls) -> "Config":
        config_path = os.environ.get("AMANAH_CONFIG", "amanah.toml")
        base = cls.from_file(config_path) if Path(config_path).exists() else cls()
        values = {}
        for f in fields(cls):
            raw = os.environ.get(ENV_NAMES.get(f.name, f"AMANAH_{f.name.upper()}"))
            current = getattr(base, f.name)
            if raw is None:
                values[f.name] = current
            elif isinstance(current, bool):
                values[f.name] = raw.lower() in TRUTHY
            elif isinstance(current, int):
                values[f.name] = int(raw)
            else:
                values[f.name] = raw
        return cls(**values)
