import httpx

from lumo.llm.llama_server import LlamaServerProvider
from lumo.models import ExtractedInvoice

EMPTY = ExtractedInvoice()


def _provider(handler) -> LlamaServerProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    return LlamaServerProvider(client=client)


def _returning(content: str) -> LlamaServerProvider:
    return _provider(
        lambda req: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    )


def test_fails_closed_on_truncated_json():
    # A small on-device model can emit truncated JSON when it runs out of tokens;
    # that must yield an empty extraction (-> policy refuses), never a crash.
    assert _returning('{"supplier_name": "CV Batik", "amount": "1,2').extract("x") == EMPTY


def test_fails_closed_on_prose_not_json():
    assert _returning("Sure — the supplier is CV Batik Nusantara.").extract("x") == EMPTY


def test_fails_closed_on_http_500():
    assert _provider(lambda req: httpx.Response(500)).extract("x") == EMPTY


def test_fails_closed_on_transport_error():
    def boom(req):
        raise httpx.ConnectError("connection refused")

    assert _provider(boom).extract("x") == EMPTY


def test_fails_closed_on_missing_choices():
    assert _provider(lambda req: httpx.Response(200, json={"error": "no model"})).extract("x") == EMPTY


def test_parses_valid_currency_formatted_extraction():
    content = (
        '{"invoice_ref":"INV-1","supplier_name":"CV Batik Nusantara",'
        '"payment_address":"GBATIKYLX7IEOR2YJMNTPMKZCIWXT2PAX635P7ZDGB3DTLQLS263VNS3",'
        '"amount":"1,250.00 USDC","currency":"USDC"}'
    )
    result = _returning(content).extract("x")
    assert result.supplier_name == "CV Batik Nusantara"
    assert result.amount == "1,250.00 USDC"
