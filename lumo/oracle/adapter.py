import sqlite3
from typing import Protocol, runtime_checkable

from lumo.config import Config
from lumo.db.repo import Repo


@runtime_checkable
class AttestationSource(Protocol):
    def submit(
        self, repo: Repo, intent_id: str, kind: str, request_hash: str
    ) -> list[str]: ...

    def collect(self, repo: Repo, intent_id: str) -> list[sqlite3.Row]: ...


class LocalSignerSet:
    def __init__(self, signers: list[str]):
        self.signers = signers

    def submit(self, repo: Repo, intent_id: str, kind: str, request_hash: str) -> list[str]:
        for signer in self.signers:
            repo.add_attestation(intent_id, signer, kind, request_hash)
        return list(self.signers)

    def collect(self, repo: Repo, intent_id: str) -> list[sqlite3.Row]:
        return repo.attestations(intent_id)


class ShipmentApiOracle:
    def submit(self, repo: Repo, intent_id: str, kind: str, request_hash: str) -> list[str]:
        raise NotImplementedError("roadmap: shipment-tracking API oracle")

    def collect(self, repo: Repo, intent_id: str) -> list[sqlite3.Row]:
        raise NotImplementedError("roadmap: shipment-tracking API oracle")


def build_oracle(config: Config) -> AttestationSource | None:
    if config.oracle_adapter == "":
        return None
    if config.oracle_adapter == "local":
        signers = [s.strip() for s in config.oracle_signers.split(",") if s.strip()]
        return LocalSignerSet(signers or [config.oracle_address])
    if config.oracle_adapter == "shipment_api":
        return ShipmentApiOracle()
    raise ValueError(f"unknown oracle_adapter {config.oracle_adapter!r}")
