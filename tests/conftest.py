from pathlib import Path

import pytest

from lumo.config import Config
from lumo.db import migrate, seed
from lumo.db.connection import connect
from lumo.db.repo import Repo

FIXTURES = Path(__file__).parent / "fixtures" / "invoices"

ATTACKER_ADDRESS = "GATTACK6XK5DCWZWSBTGCRGG2V75DPWNP6BTO34OB7O5BU43XL6SAMX7"


def load_invoice(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "lumo.db"


@pytest.fixture
def conn(db_path):
    c = connect(db_path)
    migrate.up(c)
    seed.seed(c)
    yield c
    c.close()


@pytest.fixture
def repo(conn):
    return Repo(conn)


@pytest.fixture
def config(db_path):
    return Config(db_path=str(db_path))
