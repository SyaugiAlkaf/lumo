import argparse
import json
import sys
from pathlib import Path

from amanah import flow, pipeline
from amanah.chain import mapper
from amanah.chain.adapter import build_chain_adapter
from amanah.config import Config
from amanah.db import migrate, seed
from amanah.db.connection import connect
from amanah.db.repo import Repo
from amanah.llm.llama_server import LlamaServerProvider
from amanah.llm.mock import MockProvider
from amanah.monitor.events import EventBus
from amanah.monitor.webhooks import build_webhooks
from amanah.oracle.adapter import build_oracle

EXIT_PROPOSED = 0
EXIT_REFUSED = 2
EXIT_ERROR = 3


def build_provider(config: Config):
    if config.provider == "mock":
        return MockProvider(mode=config.mock_mode)
    if config.provider == "llama":
        return LlamaServerProvider(base_url=config.llama_url)
    raise ValueError(f"unknown provider {config.provider!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="amanah")
    parser.add_argument("--db", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    propose = sub.add_parser("propose")
    propose.add_argument("invoice", type=Path)
    execute = sub.add_parser("execute")
    execute.add_argument("intent_id")
    attest = sub.add_parser("attest")
    attest.add_argument("intent_id")
    attest.add_argument("--kind", choices=["Shipped", "Failed"], required=True)
    release = sub.add_parser("release")
    release.add_argument("intent_id")
    revert = sub.add_parser("revert")
    revert.add_argument("intent_id")
    sync = sub.add_parser("sync")
    sync.add_argument("intent_id")
    args = parser.parse_args(argv)

    config = Config.from_env()
    if args.db:
        config.db_path = args.db

    try:
        conn = connect(config.db_path)
        if args.command == "init":
            migrate.up(conn)
            seed.seed(conn)
            print(f"initialized {config.db_path}")
            return EXIT_PROPOSED
        bus = EventBus(enabled=config.monitoring)
        hooks = build_webhooks(config)
        if hooks:
            bus.subscribe(hooks)
        repo = Repo(conn, bus=bus)

        if args.command == "propose":
            invoice_text = args.invoice.read_text()
            result = pipeline.run(invoice_text, repo, build_provider(config), config)
            print(json.dumps(result.model_dump(), indent=2))
            return EXIT_PROPOSED if result.decision == "proposed" else EXIT_REFUSED

        client = build_chain_adapter(config)
        if args.command == "execute":
            chain_id = flow.execute(repo, client, args.intent_id, config.sme_source, config)
            print(json.dumps({"intent_id": args.intent_id, "chain_intent_id": chain_id}))
        elif args.command == "attest":
            flow.attest(
                repo,
                client,
                args.intent_id,
                args.kind,
                config.oracle_address,
                config.oracle_source,
                oracle=build_oracle(config),
            )
            print(json.dumps({"intent_id": args.intent_id, "attested": args.kind}))
        elif args.command == "release":
            status = flow.release(repo, client, args.intent_id, config.sme_source, config)
            print(json.dumps({"intent_id": args.intent_id, "status": status}))
        elif args.command == "revert":
            status = flow.revert(repo, client, args.intent_id, config.sme_source)
            print(json.dumps({"intent_id": args.intent_id, "status": status}))
        elif args.command == "sync":
            status = mapper.sync_status(repo, client, args.intent_id)
            print(json.dumps({"intent_id": args.intent_id, "status": status}))
        return EXIT_PROPOSED
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
