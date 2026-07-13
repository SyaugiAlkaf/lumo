import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

ENV_NAMES = {"db_path": "AMANAH_DB"}

TRUTHY = ("1", "true", "yes", "on")


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
    injection_scan: bool = True
    policy_engine: bool = True
    policy_signer: bool = True
    require_attestation: bool = False
    k_of_n: int = 1
    human_cosign_threshold: int = 0
    proof_of_compute: bool = False
    dry_run: bool = False

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
