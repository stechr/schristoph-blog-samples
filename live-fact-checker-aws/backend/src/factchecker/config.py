"""Runtime configuration, all environment-driven.

Nothing account-specific is hardcoded. Model IDs default to the Claude Haiku/Sonnet split
(cheap extract, stronger verdict) but MUST be confirmed against the target account/region at
deploy time — model and inference-profile IDs change over time. Verify with:

    aws bedrock list-inference-profiles --region us-east-1
"""
from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# --- Region -----------------------------------------------------------------
AWS_REGION: str = _env("AWS_REGION", "us-east-1")

# --- Grounding --------------------------------------------------------------
# "agentcore" = Web Search on Amazon Bedrock AgentCore (via Gateway MCP).
# "mock"      = canned results, for local dev / unit tests (no AWS, no network).
GROUNDING_PROVIDER: str = _env("GROUNDING_PROVIDER", "agentcore")

# AgentCore Gateway MCP endpoint, e.g.
# https://gateway-<id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp
AGENTCORE_GATEWAY_URL: str = _env("AGENTCORE_GATEWAY_URL", "")

MAX_WEB_RESULTS: int = int(_env("MAX_WEB_RESULTS", "5"))  # 1..25 (fewer = faster + cheaper)
WEB_SEARCH_TIMEOUT_S: float = float(_env("WEB_SEARCH_TIMEOUT_S", "20"))

# The AgentCore Gateway namespaces a target's tools as "{targetName}___{toolName}".
# setup_gateway.py names the target "web-search-tool", so the tool is "web-search-tool___WebSearch".
WEB_SEARCH_TOOL_NAME: str = _env("WEB_SEARCH_TOOL_NAME", "web-search-tool___WebSearch")

# --- Models (Haiku/Sonnet split) --------------------------------------------
# Defaults are placeholders to CONFIRM at deploy; override via env.
EXTRACT_MODEL_ID: str = _env(
    "EXTRACT_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)
VERIFY_MODEL_ID: str = _env(
    "VERIFY_MODEL_ID", "us.anthropic.claude-sonnet-4-6"
)

# --- Limits -----------------------------------------------------------------
MAX_CLAIM_CHARS: int = int(_env("MAX_CLAIM_CHARS", "2000"))
MAX_TEXT_CHARS: int = int(_env("MAX_TEXT_CHARS", "20000"))
MAX_CLAIMS_PER_EXTRACT: int = int(_env("MAX_CLAIMS_PER_EXTRACT", "5"))
WEB_QUERY_MAX_CHARS: int = 200  # AgentCore Web Search hard limit on query length

# Optional Bedrock Guardrail (set both to enable).
GUARDRAIL_ID: str = _env("GUARDRAIL_ID", "")
GUARDRAIL_VERSION: str = _env("GUARDRAIL_VERSION", "")
