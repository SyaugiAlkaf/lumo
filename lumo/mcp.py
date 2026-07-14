import json
import sys

from lumo.config import Config
from lumo.sdk import ATTEST_KINDS, LumoClient

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "lumo.propose_payment",
        "description": (
            "Run an invoice through Lumo's guard chain (injection scan, policy "
            "engine, caps). Returns a decision: proposed, held, or refused, with "
            "reason codes. Money can only move to registered suppliers within caps."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "invoice_text": {
                    "type": "string",
                    "description": "Raw invoice text to evaluate",
                }
            },
            "required": ["invoice_text"],
        },
    },
    {
        "name": "lumo.get_status",
        "description": "Fetch the current status of a payment intent by id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "intent_id": {
                    "type": "string",
                    "description": "Intent id returned by lumo.propose_payment",
                }
            },
            "required": ["intent_id"],
        },
    },
    {
        "name": "lumo.attest",
        "description": (
            "Record an oracle attestation (Shipped or Failed) for a payment intent. "
            "Shipped gates release to the supplier; Failed gates refund to the SME."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "intent_id": {"type": "string", "description": "Intent id to attest"},
                "kind": {
                    "type": "string",
                    "enum": list(ATTEST_KINDS),
                    "description": "Attestation kind",
                },
            },
            "required": ["intent_id", "kind"],
        },
    },
]


def _call_tool(name: str, arguments: dict, client: LumoClient) -> dict | None:
    if name == "lumo.propose_payment":
        return client.propose(arguments["invoice_text"]).model_dump()
    if name == "lumo.get_status":
        return client.status(arguments["intent_id"])
    if name == "lumo.attest":
        client.attest(arguments["intent_id"], arguments["kind"])
        return {"intent_id": arguments["intent_id"], "attested": arguments["kind"]}
    return None


def handle(request: dict, client: LumoClient) -> dict | None:
    method = request.get("method", "")
    request_id = request.get("id")
    if request_id is None:
        return None

    def reply(result):
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def error(code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        return reply(
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lumo", "version": "0.1.0"},
            }
        )
    if method == "tools/list":
        return reply({"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        if name not in {tool["name"] for tool in TOOLS}:
            return error(-32602, f"unknown tool {name!r}")
        try:
            result = _call_tool(name, params.get("arguments", {}), client)
        except (KeyError, ValueError) as exc:
            return reply(
                {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            )
        if result is None:
            return reply(
                {"content": [{"type": "text", "text": "unknown intent"}], "isError": True}
            )
        return reply(
            {
                "content": [{"type": "text", "text": json.dumps(result)}],
                "isError": False,
            }
        )
    return error(-32601, f"method {method!r} not found")


def main() -> int:
    client = LumoClient(Config.from_env())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        response = handle(json.loads(line), client)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
