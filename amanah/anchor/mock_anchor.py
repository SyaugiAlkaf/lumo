"""SEP-24-shaped cash-out receipt. Structurally mocked: zero network, no anchor
credentials, refs are MOCK-<ulid>. Real anchor integration is a human-gated STOP."""

from amanah.db import ulid
from amanah.db.repo import Repo

STROOP = 10_000_000


def cash_out(repo: Repo, intent_id: str) -> dict:
    row = repo.intent(intent_id)
    if row is None or row["status"] != "released":
        raise ValueError(f"cash_out requires a released intent, got {intent_id}")

    supplier = repo.supplier_by_id(row["supplier_id"])
    ref = f"MOCK-{ulid.new()}"
    repo.add_anchor_payout(intent_id, ref, amount=row["amount"], address=supplier["address"])

    usdc = int(row["amount"]) / STROOP
    return {
        "transaction": {
            "id": ref,
            "kind": "withdrawal",
            "status": "completed",
            "amount_in": f"{usdc:.2f}",
            "amount_in_asset": "stellar:USDC",
            "amount_out": f"{usdc:.2f}",
            "amount_out_asset": "iso4217:IDR (MOCK)",
            "to": supplier["address"],
            "external_transaction_id": ref,
        }
    }
