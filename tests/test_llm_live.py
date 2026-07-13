import os

import pytest

from conftest import load_invoice

pytestmark = pytest.mark.skipif(
    not os.environ.get("AMANAH_LLAMA_URL"),
    reason="live llama-server check: set AMANAH_LLAMA_URL (human-triggered, not a gate)",
)


def test_live_llama_extracts_clean_invoice():
    from amanah.llm.llama_server import LlamaServerProvider

    provider = LlamaServerProvider(base_url=os.environ["AMANAH_LLAMA_URL"])
    extracted = provider.extract(load_invoice("clean_in_policy.txt"))
    assert extracted.supplier_name == "CV Batik Nusantara"
    assert extracted.amount is not None
