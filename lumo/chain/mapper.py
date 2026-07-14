from lumo.chain.adapter import ChainAdapter
from lumo.chain.soroban_client import variant_of
from lumo.db.repo import Repo

CHAIN_TO_LOCAL = {
    "Funded": "escrowed",
    "Released": "released",
    "Refunded": "reverted",
}


def sync_status(repo: Repo, client: ChainAdapter, intent_id: str) -> str:
    row = repo.intent(intent_id)
    if row is None:
        raise ValueError(f"unknown intent {intent_id}")
    if row["chain_intent_id"] is None:
        return row["status"]

    chain = client.get_status(int(row["chain_intent_id"]))
    if chain is None:
        return row["status"]

    mapped = CHAIN_TO_LOCAL[variant_of(chain["status"])]
    if mapped == row["status"]:
        return mapped

    if mapped == "escrowed":
        # Crash recovery: the chain shows Funded but the local row never advanced
        # (e.g. execute() died between submit and record_decision). Persist the
        # escrowed transition against the existing chain intent — never re-create.
        repo.record_decision(
            decision="approved",
            codes=["CHAIN_FUNDED"],
            request_hash=row["request_hash"],
            intent_id=intent_id,
        )
    elif mapped == "released":
        repo.mark_released(intent_id)
    elif mapped == "reverted":
        repo.record_decision(
            decision="reverted",
            codes=["CHAIN_REFUNDED"],
            request_hash=row["request_hash"],
            intent_id=intent_id,
        )
        repo.emit(
            "intent.refunded", intent_id=intent_id, request_hash=row["request_hash"]
        )
    return mapped
