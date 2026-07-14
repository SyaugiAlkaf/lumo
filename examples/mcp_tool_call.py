import json
import subprocess
import sys

INVOICE = (
    "INVOICE INV-2026-0099\n"
    "From: CV Batik Nusantara\n"
    "Payment address: GBATIKYLX7IEOR2YJMNTPMKZCIWXT2PAX635P7ZDGB3DTLQLS263VNS3\n"
    "Amount due: 500.00 USDC\n"
)

server = subprocess.Popen(
    [sys.executable, "-m", "lumo.mcp"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
)


def rpc(request_id, method, params=None):
    request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    server.stdin.write(json.dumps(request) + "\n")
    server.stdin.flush()
    return json.loads(server.stdout.readline())


print(rpc(1, "initialize")["result"]["serverInfo"])
print([tool["name"] for tool in rpc(2, "tools/list")["result"]["tools"]])

call = rpc(
    3,
    "tools/call",
    {"name": "lumo.propose_payment", "arguments": {"invoice_text": INVOICE}},
)
print(call["result"]["content"][0]["text"])

server.stdin.close()
sys.exit(server.wait())
