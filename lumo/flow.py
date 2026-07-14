from lumo.anchor.adapter import build_anchor
from lumo.chain import ChainError, mapper
from lumo.chain.adapter import ChainAdapter
from lumo.chain.soroban_client import variant_of
from lumo.config import Config
from lumo.db.repo import Repo
from lumo.oracle.adapter import AttestationSource
from lumo.pipeline import release_check


def execute(
    repo: Repo, client: ChainAdapter, intent_id: str, sme_source: str, config: Config
) -> int | None:
    row = repo.intent(intent_id)
    if row is None:
        raise ValueError(f"unknown intent {intent_id}")
    if row["status"] != "proposed":
        raise ValueError(f"intent {intent_id} is {row['status']}, expected proposed")
    if config.dry_run:
        return None

    supplier = repo.supplier_by_id(row["supplier_id"])
    rules = repo.rules()
    result = client.create_intent(
        sme=rules["sme_address"],
        supplier=supplier["address"],
        token=row["token"],
        amount=int(row["amount"]),
        request_hash=row["request_hash"],
        deadline=int(row["deadline"]),
        source=sme_source,
    )
    chain_id = int(result.value)

    # Never trust the client success claim: escrowed is written only after the
    # chain read confirms the funded intent binds our exact request_hash.
    chain = client.get_status(chain_id)
    if chain is None:
        raise ChainError(f"chain intent {chain_id} not found after submit")
    if chain["request_hash"].lower() != row["request_hash"].lower():
        raise ChainError(f"chain intent {chain_id} request_hash mismatch")
    if variant_of(chain["status"]) != "Funded":
        raise ChainError(f"chain intent {chain_id} not Funded")

    repo.set_chain_intent(intent_id, chain_id)
    repo.add_chain_tx(intent_id, "create_intent", result.tx_hash)
    repo.record_decision(
        decision="approved",
        codes=["ESCROWED_ONCHAIN"],
        request_hash=row["request_hash"],
        intent_id=intent_id,
        detail=result.tx_hash,
    )
    return chain_id


def attest(
    repo: Repo,
    client: ChainAdapter,
    intent_id: str,
    kind: str,
    oracle_address: str,
    oracle_source: str,
    oracle: AttestationSource | None = None,
) -> None:
    row = repo.intent(intent_id)
    result = client.attest(
        int(row["chain_intent_id"]), oracle_address, kind, source=oracle_source
    )
    repo.add_chain_tx(intent_id, f"attest_{kind.lower()}", result.tx_hash)
    if oracle is not None:
        oracle.submit(repo, intent_id, kind, row["request_hash"])


def release(
    repo: Repo, client: ChainAdapter, intent_id: str, source: str, config: Config
) -> str:
    row = repo.intent(intent_id)
    release_check(repo, config, row)
    result = client.release(int(row["chain_intent_id"]), source=source)
    repo.add_chain_tx(intent_id, "release", result.tx_hash)
    status = mapper.sync_status(repo, client, intent_id)
    if status == "released":
        build_anchor(config).cash_out(repo, intent_id)
    return status


def revert(repo: Repo, client: ChainAdapter, intent_id: str, source: str) -> str:
    row = repo.intent(intent_id)
    result = client.refund(int(row["chain_intent_id"]), source=source)
    repo.add_chain_tx(intent_id, "refund", result.tx_hash)
    return mapper.sync_status(repo, client, intent_id)
