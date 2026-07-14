from typing import Protocol, runtime_checkable

from lumo.chain.soroban_client import InvokeResult, SorobanClient
from lumo.config import Config


@runtime_checkable
class ChainAdapter(Protocol):
    def deploy(self) -> str: ...

    def create_intent(
        self,
        *,
        sme: str,
        supplier: str,
        token: str,
        amount: int,
        request_hash: str,
        deadline: int,
        source: str | None = None,
    ) -> InvokeResult: ...

    def attest(
        self, chain_intent_id: int, oracle: str, kind: str, source: str | None = None
    ) -> InvokeResult: ...

    def release(self, chain_intent_id: int, source: str | None = None) -> InvokeResult: ...

    def refund(self, chain_intent_id: int, source: str | None = None) -> InvokeResult: ...

    def get_status(self, chain_intent_id: int) -> dict | None: ...


class SorobanAdapter:
    def __init__(self, client: SorobanClient):
        self.client = client

    def deploy(self) -> str:
        raise NotImplementedError("soroban deploy is scripted: scripts/deploy_local.sh")

    def create_intent(
        self,
        *,
        sme: str,
        supplier: str,
        token: str,
        amount: int,
        request_hash: str,
        deadline: int,
        source: str | None = None,
    ) -> InvokeResult:
        return self.client.create_intent(
            sme=sme,
            supplier=supplier,
            token=token,
            amount=amount,
            request_hash=request_hash,
            deadline=deadline,
            source=source,
        )

    def attest(
        self, chain_intent_id: int, oracle: str, kind: str, source: str | None = None
    ) -> InvokeResult:
        return self.client.attest(chain_intent_id, oracle, kind, source=source)

    def release(self, chain_intent_id: int, source: str | None = None) -> InvokeResult:
        return self.client.release(chain_intent_id, source=source)

    def refund(self, chain_intent_id: int, source: str | None = None) -> InvokeResult:
        return self.client.refund(chain_intent_id, source=source)

    def get_status(self, chain_intent_id: int) -> dict | None:
        return self.client.get_intent(chain_intent_id)


class EvmAdapter:
    def deploy(self) -> str:
        raise NotImplementedError("roadmap: EVM/x402")

    def create_intent(
        self,
        *,
        sme: str,
        supplier: str,
        token: str,
        amount: int,
        request_hash: str,
        deadline: int,
        source: str | None = None,
    ) -> InvokeResult:
        raise NotImplementedError("roadmap: EVM/x402")

    def attest(
        self, chain_intent_id: int, oracle: str, kind: str, source: str | None = None
    ) -> InvokeResult:
        raise NotImplementedError("roadmap: EVM/x402")

    def release(self, chain_intent_id: int, source: str | None = None) -> InvokeResult:
        raise NotImplementedError("roadmap: EVM/x402")

    def refund(self, chain_intent_id: int, source: str | None = None) -> InvokeResult:
        raise NotImplementedError("roadmap: EVM/x402")

    def get_status(self, chain_intent_id: int) -> dict | None:
        raise NotImplementedError("roadmap: EVM/x402")


def build_chain_adapter(config: Config) -> ChainAdapter:
    if config.chain_adapter == "soroban":
        return SorobanAdapter(
            SorobanClient(config.escrow_id, network=config.network, source=config.sme_source)
        )
    if config.chain_adapter == "mock":
        from lumo.chain.mock_chain import MockChainAdapter

        return MockChainAdapter()
    if config.chain_adapter == "evm":
        return EvmAdapter()
    raise ValueError(f"unknown chain_adapter {config.chain_adapter!r}")
