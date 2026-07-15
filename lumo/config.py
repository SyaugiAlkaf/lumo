import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

ENV_NAMES = {"db_path": "LUMO_DB"}

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
    db_path: str = "lumo.db"
    provider: str = "mock"
    mock_mode: str = "honest"
    llama_url: str = "http://127.0.0.1:8080"
    deadline_secs: int = 3600
    escrow_id: str = ""
    network: str = "local"
    sme_source: str = "lumo-sme"
    # When set (a policy-account contract address), create_intent is routed
    # through that smart account and authorized by the sme_source owner key's
    # __check_auth signature — putting the on-chain policy in every payment's
    # money path. Empty = the legacy keypair path.
    sme_smart_account: str = ""
    oracle_source: str = "lumo-oracle"
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

    def __post_init__(self):
        # Fail fast on a bad config (env/TOML splat) rather than surfacing it as
        # an obscure error deep in the chain/pipeline later.
        if self.chain_adapter not in ("soroban", "mock", "evm"):
            raise ValueError(
                f"unknown chain_adapter {self.chain_adapter!r}, expected soroban|mock|evm"
            )
        if not (1 <= int(self.api_port) <= 65535):
            raise ValueError(f"api_port {self.api_port} out of range (1-65535)")
        if int(self.k_of_n) < 1:
            raise ValueError(f"k_of_n must be >= 1, got {self.k_of_n}")
        if int(self.deadline_secs) <= 0:
            raise ValueError(f"deadline_secs must be > 0, got {self.deadline_secs}")
        if self.mock_mode not in ("honest", "compromised"):
            raise ValueError(f"unknown mock_mode {self.mock_mode!r}, expected honest|compromised")
        # A whitespace-only env value must not silently route through the
        # smart-account path (and then fail deep in the SDK).
        self.sme_smart_account = self.sme_smart_account.strip()

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
        config_path = os.environ.get("LUMO_CONFIG", "lumo.toml")
        base = cls.from_file(config_path) if Path(config_path).exists() else cls()
        values = {}
        for f in fields(cls):
            raw = os.environ.get(ENV_NAMES.get(f.name, f"LUMO_{f.name.upper()}"))
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
