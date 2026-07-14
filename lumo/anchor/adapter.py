from typing import Protocol, runtime_checkable

from lumo.anchor import mock_anchor
from lumo.config import Config
from lumo.db.repo import Repo


@runtime_checkable
class AnchorAdapter(Protocol):
    def cash_out(self, repo: Repo, intent_id: str) -> dict: ...


class MockAnchor:
    def cash_out(self, repo: Repo, intent_id: str) -> dict:
        return mock_anchor.cash_out(repo, intent_id)


class GCashAnchor:
    def cash_out(self, repo: Repo, intent_id: str) -> dict:
        raise NotImplementedError("roadmap: GCash anchor cash-out")


class PdaxAnchor:
    def cash_out(self, repo: Repo, intent_id: str) -> dict:
        raise NotImplementedError("roadmap: PDAX anchor cash-out")


def build_anchor(config: Config) -> AnchorAdapter:
    if config.anchor_adapter == "mock":
        return MockAnchor()
    if config.anchor_adapter == "gcash":
        return GCashAnchor()
    if config.anchor_adapter == "pdax":
        return PdaxAnchor()
    raise ValueError(f"unknown anchor_adapter {config.anchor_adapter!r}")
