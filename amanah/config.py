import os
from dataclasses import dataclass


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

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            db_path=os.environ.get("AMANAH_DB", cls.db_path),
            provider=os.environ.get("AMANAH_PROVIDER", cls.provider),
            mock_mode=os.environ.get("AMANAH_MOCK_MODE", cls.mock_mode),
            llama_url=os.environ.get("AMANAH_LLAMA_URL", cls.llama_url),
            deadline_secs=int(os.environ.get("AMANAH_DEADLINE_SECS", cls.deadline_secs)),
            escrow_id=os.environ.get("AMANAH_ESCROW_ID", cls.escrow_id),
            network=os.environ.get("AMANAH_NETWORK", cls.network),
            sme_source=os.environ.get("AMANAH_SME_SOURCE", cls.sme_source),
            oracle_source=os.environ.get("AMANAH_ORACLE_SOURCE", cls.oracle_source),
            oracle_address=os.environ.get("AMANAH_ORACLE_ADDRESS", cls.oracle_address),
        )
