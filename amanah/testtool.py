from amanah import flow
from amanah.chain.adapter import ChainAdapter, build_chain_adapter
from amanah.config import Config
from amanah.sdk import AmanahClient

EXPLORER_TX = "https://stellar.expert/explorer/testnet/tx/"

STEP_OF_ACTION = (
    ("create_intent", "create_intent"),
    ("attest_shipped", "attest"),
    ("release", "release"),
)


def run_invoice(
    invoice_text: str, config: Config, adapter: ChainAdapter | None = None
) -> dict:
    client = AmanahClient(config)
    try:
        result = client.propose(invoice_text)
        out = {
            "decision": result.decision,
            "codes": result.codes,
            "flags": result.flags,
            "request_hash": result.request_hash,
            "txs": [],
        }
        if result.decision != "proposed":
            return out

        chain = adapter or build_chain_adapter(config)
        flow.execute(client.repo, chain, result.intent_id, config.sme_source, config)
        flow.attest(
            client.repo,
            chain,
            result.intent_id,
            "Shipped",
            config.oracle_address,
            config.oracle_source,
        )
        flow.release(client.repo, chain, result.intent_id, config.sme_source, config)

        hashes = {r["action"]: r["tx_hash"] for r in client.repo.chain_txs(result.intent_id)}
        out["intent_id"] = result.intent_id
        out["txs"] = [
            {"step": step, "hash": hashes[action], "url": EXPLORER_TX + hashes[action]}
            for action, step in STEP_OF_ACTION
            if hashes.get(action)
        ]
        return out
    finally:
        client.close()
