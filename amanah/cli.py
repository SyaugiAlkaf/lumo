import argparse
import json
import sys
from pathlib import Path

from amanah import pipeline
from amanah.config import Config
from amanah.db import migrate, seed
from amanah.db.connection import connect
from amanah.db.repo import Repo
from amanah.llm.llama_server import LlamaServerProvider
from amanah.llm.mock import MockProvider

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
        invoice_text = args.invoice.read_text()
        result = pipeline.run(invoice_text, Repo(conn), build_provider(config), config)
        print(json.dumps(result.model_dump(), indent=2))
        return EXIT_PROPOSED if result.decision == "proposed" else EXIT_REFUSED
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
