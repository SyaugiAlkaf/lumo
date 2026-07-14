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
    if config.dry_run:
        if row["status"] != "proposed":
            raise ValueError(f"intent {intent_id} is {row['status']}, expected proposed")
        return None

    # Atomic claim: exactly one caller moves proposed -> escrowed and proceeds to
    # submit. A retried or concurrent call gets False and returns without touching
    # the chain, so the same invoice is never double-escrowed.
    if not repo.claim_escrow(intent_id):
        return None

    supplier = repo.supplier_by_id(row["supplier_id"])
    rules = repo.rules()
    chain_id = None
    try:
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
        # Persist the chain id + tx BEFORE confirming. If the confirm read fails,
        # a retry reconciles against THIS escrow (via mapper.sync_status) instead
        # of creating a second one — the escrow contract has no request_hash
        # idempotency, so a re-submit would be a real double-escrow.
        repo.set_chain_intent(intent_id, chain_id)
        repo.add_chain_tx(intent_id, "create_intent", result.tx_hash)
    except Exception:
        # Only reopen for a clean retry if no on-chain escrow was created.
        if chain_id is None:
            repo.release_escrow_claim(intent_id)
        raise

    # Chain-wins confirmation. On failure the claim + chain id stay put (no
    # re-create on retry); reconciliation is mapper.sync_status.
    chain = client.get_status(chain_id)
    if chain is None:
        raise ChainError(f"chain intent {chain_id} not found after submit")
    if chain["request_hash"].lower() != row["request_hash"].lower():
        raise ChainError(f"chain intent {chain_id} request_hash mismatch")
    if variant_of(chain["status"]) != "Funded":
        raise ChainError(f"chain intent {chain_id} not Funded")

    repo.record_decision(
        decision="approved",
        codes=["ESCROWED_ONCHAIN"],
        request_hash=row["request_hash"],
        intent_id=intent_id,
        detail=result.tx_hash,
    )
    return chain_id


def _chain_intent_id(repo: Repo, intent_id: str) -> int:
    row = repo.intent(intent_id)
    if row is None:
        raise ValueError(f"unknown intent {intent_id}")
    if row["chain_intent_id"] is None:
        raise ValueError(f"intent {intent_id} has no on-chain escrow yet")
    return int(row["chain_intent_id"])


def attest(
    repo: Repo,
    client: ChainAdapter,
    intent_id: str,
    kind: str,
    oracle_address: str,
    oracle_source: str,
    oracle: AttestationSource | None = None,
) -> None:
    chain_intent_id = _chain_intent_id(repo, intent_id)
    row = repo.intent(intent_id)
    result = client.attest(chain_intent_id, oracle_address, kind, source=oracle_source)
    repo.add_chain_tx(intent_id, f"attest_{kind.lower()}", result.tx_hash)
    if oracle is not None:
        oracle.submit(repo, intent_id, kind, row["request_hash"])


def release(
    repo: Repo, client: ChainAdapter, intent_id: str, source: str, config: Config
) -> str:
    chain_intent_id = _chain_intent_id(repo, intent_id)
    row = repo.intent(intent_id)
    release_check(repo, config, row)
    result = client.release(chain_intent_id, source=source)
    repo.add_chain_tx(intent_id, "release", result.tx_hash)
    status = mapper.sync_status(repo, client, intent_id)
    if status == "released":
        build_anchor(config).cash_out(repo, intent_id)
    return status


def revert(repo: Repo, client: ChainAdapter, intent_id: str, source: str) -> str:
    chain_intent_id = _chain_intent_id(repo, intent_id)
    result = client.refund(chain_intent_id, source=source)
    repo.add_chain_tx(intent_id, "refund", result.tx_hash)
    return mapper.sync_status(repo, client, intent_id)
