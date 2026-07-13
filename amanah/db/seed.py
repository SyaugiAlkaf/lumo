"""Demo persona: Bu Sari, owner of Sari Craft Export (batik exporter, Yogyakarta).

Addresses are fixtures for the local demo network, not real accounts.
"""

import sqlite3

from amanah.db import ulid

SME_ADDRESS = "GBUSARIYWABHQJ7BYCIY6F6Y4ZFWOASDFGFOHBGWCT2DTKBAFFN2DWLR"
TOKEN_ADDRESS = "CUSDCR3LOBHARLAPU3ASFXKBMSZPJKLZVXW3AOO24DRILTVEHSWW3G3T"

SUPPLIERS = [
    ("CV Batik Nusantara", "GBATIKYLX7IEOR2YJMNTPMKZCIWXT2PAX635P7ZDGB3DTLQLS263VNS3"),
    ("PT Kain Jaya Textiles", "GKAING2HW25HBZSUAASSYDDENT4D5WTH3OCLLBMZM6DP2VJBW63ESO63"),
]

STROOP = 10_000_000
CAP_PER_TX = 2_000 * STROOP
CAP_DAILY = 5_000 * STROOP

RULES = {
    "sme_address": SME_ADDRESS,
    "token_address": TOKEN_ADDRESS,
    "cap_per_tx": str(CAP_PER_TX),
    "cap_daily": str(CAP_DAILY),
}


def seed(conn: sqlite3.Connection) -> None:
    with conn:
        for name, address in SUPPLIERS:
            conn.execute(
                "INSERT OR IGNORE INTO suppliers (id, name, address) VALUES (?, ?, ?)",
                (ulid.new(), name, address),
            )
        for key, value in RULES.items():
            conn.execute(
                "INSERT INTO policy_rules (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
