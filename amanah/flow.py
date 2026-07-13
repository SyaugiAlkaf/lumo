from amanah.models import TxPlan


def submit_proposal(intent_id: str, tx_plan: TxPlan) -> int:
    raise NotImplementedError("P3: submit via chain.soroban_client, returns chain intent id")


def sync_status(intent_id: str) -> str:
    raise NotImplementedError("P3: chain-wins status sync via chain.mapper")
