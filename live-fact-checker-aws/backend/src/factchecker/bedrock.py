"""Amazon Bedrock (Claude) via the Converse API, using forced tool-use for structured output.

``extract_claims`` uses the cheap model (Haiku); ``reason_verdict`` uses the stronger model
(Sonnet). Both constrain the model to a tool schema so the result is always valid structured
JSON — no prose-parsing fallbacks.
"""
from __future__ import annotations

from . import config, prompts
from .models import Claim, Context


def _client():
    import boto3
    return boto3.client("bedrock-runtime", region_name=config.AWS_REGION)


def _converse_tool_call(model_id: str, prompt: str, tool: dict) -> dict:
    """Run a single Converse turn that forces the given tool, return the tool input dict."""
    kwargs = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "toolConfig": {
            "tools": [tool],
            "toolChoice": {"tool": {"name": tool["toolSpec"]["name"]}},
        },
        "inferenceConfig": {"temperature": 0.1, "maxTokens": 1024},
    }
    if config.GUARDRAIL_ID and config.GUARDRAIL_VERSION:
        kwargs["guardrailConfig"] = {
            "guardrailIdentifier": config.GUARDRAIL_ID,
            "guardrailVersion": config.GUARDRAIL_VERSION,
        }
    resp = _client().converse(**kwargs)
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise RuntimeError("Model did not return a tool use block")


def extract_claims(text: str, ctx: Context, max_claims: int) -> list[Claim]:
    prompt = prompts.extract_prompt(text, ctx, max_claims)
    data = _converse_tool_call(config.EXTRACT_MODEL_ID, prompt, prompts.EXTRACT_TOOL)
    claims = []
    for c in data.get("claims", [])[:max_claims]:
        claims.append(
            Claim(
                claim=c.get("claim", ""),
                summary=c.get("summary", ""),
                search_query=c.get("searchQuery", ""),
            )
        )
    return claims


def reason_verdict(claim: str, summary: str, ctx: Context, evidence_block: str) -> dict:
    """Return {'verdict','confidence','explanation','claimNormalized'?} from the verdict model."""
    prompt = prompts.verdict_prompt(claim, summary, ctx, evidence_block)
    return _converse_tool_call(config.VERIFY_MODEL_ID, prompt, prompts.VERDICT_TOOL)
