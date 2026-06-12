"""handler.py — A minimal MCP-compatible JSON-RPC endpoint for AWS Lambda.

MCP is JSON-RPC 2.0 on the wire. For a remote server fronted by a Lambda
Function URL, we implement the three methods a client needs to discover and
invoke tools: `initialize`, `tools/list`, and `tools/call`. This is stdlib-only
(no bundled dependencies), which keeps the deploy small and auditable.

This is deliberately minimal — it is the "remote server" rung of the hosting
ladder, not a full MCP server framework. The point is to show a real,
account-bounded remote endpoint that a SigV4-signing client can reach.

Access control is NOT in this code: it is enforced at the edge by the Lambda
Function URL's AuthType=AWS_IAM (see the CDK stack). Every request must be
SigV4-signed by an IAM principal in THIS account that holds
lambda:InvokeFunctionUrl on this function. Unsigned/foreign callers get 403
before this handler ever runs.
"""
from __future__ import annotations

import json
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "mcp-strategies-demo-remote", "version": "1.0.0"}

# The tool catalog this remote server exposes. Same design rules as the
# tool-design post: domain-noun-verb names, <=8 params, clear descriptions.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "demo_echo",
        "description": "Echo a message back. Confirms the remote server is "
                       "reachable and the SigV4 signature was accepted.",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string",
                                       "description": "text to echo back"}},
            "required": ["message"],
        },
    },
    {
        "name": "demo_account_context",
        "description": "Return the AWS account and region the server runs in. "
                       "Useful to prove the call stayed inside the account "
                       "boundary.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


def _dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    import os
    if name == "demo_echo":
        return {"echo": args.get("message", "")}
    if name == "demo_account_context":
        return {
            "account": os.environ.get("MCP_ACCOUNT_ID", "unknown"),
            "region": os.environ.get("AWS_REGION", "unknown"),
            "function": os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown"),
        }
    raise KeyError(name)


def _handle_rpc(req: dict[str, Any]) -> dict[str, Any] | None:
    rpc_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    def err(code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL_VERSION,
                   "serverInfo": SERVER_INFO,
                   "capabilities": {"tools": {}}})
    if method in ("notifications/initialized", "initialized"):
        return None  # notification: no response
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments") or {}
        try:
            payload = _dispatch_tool(tool_name, args)
        except KeyError:
            return err(-32602, f"Unknown tool: {tool_name}")
        # MCP tool results are returned as content blocks.
        return ok({"content": [{"type": "text",
                                 "text": json.dumps(payload)}],
                   "isError": False})
    return err(-32601, f"Method not found: {method}")


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Lambda Function URL handler. Body is a JSON-RPC request (or batch)."""
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _http(400, {"jsonrpc": "2.0", "id": None,
                           "error": {"code": -32700, "message": "Parse error"}})

    if isinstance(parsed, list):  # JSON-RPC batch
        responses = [r for r in (_handle_rpc(p) for p in parsed) if r is not None]
        return _http(200, responses)

    response = _handle_rpc(parsed)
    if response is None:
        return _http(202, "")
    return _http(200, response)


def _http(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": body if isinstance(body, str) else json.dumps(body),
    }
