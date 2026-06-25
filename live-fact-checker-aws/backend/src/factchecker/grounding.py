"""Grounding — retrieve web evidence for a claim.

Two providers, selected by ``config.GROUNDING_PROVIDER``:

* ``mock``      — deterministic canned results; no AWS, no network. For local dev + tests.
* ``agentcore`` — Web Search on Amazon Bedrock AgentCore, invoked as an MCP ``tools/call``
                  against the AgentCore Gateway endpoint, signed with SigV4.

The AgentCore response (per the MCP envelope) is a single ``content`` text block holding a
serialized JSON document: ``{"id": ..., "results": [{"text","url","title","publishedDate"}]}``.
"""
from __future__ import annotations

import json
import uuid

from . import config
from .models import Source


def web_search(query: str, max_results: int | None = None) -> list[Source]:
    """Return evidence Sources for a search query. Query is truncated to the 200-char limit."""
    query = (query or "").strip()[: config.WEB_QUERY_MAX_CHARS]
    n = max_results or config.MAX_WEB_RESULTS
    if not query:
        return []
    if config.GROUNDING_PROVIDER == "mock":
        return _mock_search(query, n)
    return _agentcore_search(query, n)


# --------------------------------------------------------------------------- #
# Mock provider                                                               #
# --------------------------------------------------------------------------- #
def _mock_search(query: str, n: int) -> list[Source]:
    """Deterministic synthetic evidence. All data is fictional."""
    base = [
        Source(
            url="https://example.org/stats/inflation-2025",
            title="Annual price index report 2025 (fictional statistics office)",
            published_date="2026-01-15",
            snippet="Official annual inflation for 2025 was recorded at 211%, down from the prior year.",
        ),
        Source(
            url="https://example.org/factcheck/economy",
            title="Fact-check: economic figures in the 2026 budget speech (fictional)",
            published_date="2026-02-02",
            snippet="The frequently cited '200%+' figure aligns with the official 211% reading.",
        ),
    ]
    return base[: max(1, min(n, len(base)))]


# --------------------------------------------------------------------------- #
# AgentCore Web Search provider (MCP via Gateway, SigV4-signed)               #
# --------------------------------------------------------------------------- #
def _agentcore_search(query: str, n: int) -> list[Source]:
    if not config.AGENTCORE_GATEWAY_URL:
        raise RuntimeError(
            "AGENTCORE_GATEWAY_URL is not set. Deploy the AgentCore Gateway + web-search target "
            "and set AGENTCORE_GATEWAY_URL, or use GROUNDING_PROVIDER=mock for local dev."
        )
    # Lazy imports so the mock path needs no AWS deps. boto3/botocore ship in the Lambda runtime;
    # urllib is stdlib — no third-party dependency required in the deployment package.
    import urllib.request

    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": config.WEB_SEARCH_TOOL_NAME, "arguments": {"query": query, "maxResults": n}},
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    creds = boto3.Session().get_credentials()
    aws_req = AWSRequest(method="POST", url=config.AGENTCORE_GATEWAY_URL, data=body, headers=headers)
    SigV4Auth(creds, "bedrock-agentcore", config.AWS_REGION).add_auth(aws_req)

    req = urllib.request.Request(  # noqa: S310 — fixed https Gateway endpoint, SigV4-signed
        config.AGENTCORE_GATEWAY_URL, data=body, headers=dict(aws_req.headers), method="POST"
    )
    with urllib.request.urlopen(req, timeout=config.WEB_SEARCH_TIMEOUT_S) as resp:
        return _parse_mcp_results(json.loads(resp.read().decode("utf-8")))


def _parse_mcp_results(envelope: dict) -> list[Source]:
    """Parse the MCP tools/call envelope into Sources.

    Envelope: {"result": {"content": [{"type":"text","text": "<json string>"}]}}
    Inner JSON: {"id": ..., "results": [{"text","url","title","publishedDate"}]}
    Knowledge-graph observations may have null url/title.
    """
    result = envelope.get("result", envelope)
    content = result.get("content", [])
    if not content:
        return []
    text = content[0].get("text", "")
    try:
        inner = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[Source] = []
    for r in inner.get("results", []):
        out.append(
            Source(
                url=r.get("url") or "",
                title=r.get("title") or "",
                published_date=r.get("publishedDate") or "",
                snippet=r.get("text") or "",
            )
        )
    return out


def evidence_block(sources: list[Source]) -> str:
    """Render sources into a compact, numbered evidence block for the verdict prompt."""
    if not sources:
        return "(no search results found)"
    lines = []
    for i, s in enumerate(sources, 1):
        date = f" ({s.published_date})" if s.published_date else ""
        lines.append(f"[{i}] {s.title}{date}\n    {s.snippet}\n    URL: {s.url}")
    return "\n".join(lines)
