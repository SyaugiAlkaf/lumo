import os
from dataclasses import dataclass


@dataclass
class Config:
    db_path: str = "amanah.db"
    provider: str = "mock"
    mock_mode: str = "honest"
    llama_url: str = "http://127.0.0.1:8080"
    deadline_secs: int = 3600

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            db_path=os.environ.get("AMANAH_DB", cls.db_path),
            provider=os.environ.get("AMANAH_PROVIDER", cls.provider),
            mock_mode=os.environ.get("AMANAH_MOCK_MODE", cls.mock_mode),
            llama_url=os.environ.get("AMANAH_LLAMA_URL", cls.llama_url),
            deadline_secs=int(os.environ.get("AMANAH_DEADLINE_SECS", cls.deadline_secs)),
        )
