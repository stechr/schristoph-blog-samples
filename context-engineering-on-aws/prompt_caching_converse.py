"""Amazon Bedrock prompt caching via the Converse API (cachePoint).

Mark a stable, static prefix of the context as a cache checkpoint. On supported
models, repeated calls reuse the cached prefix at a reduced read rate instead of
reprocessing it — the direct implementation of "curate context once, feed it
cheaply every turn."

Key facts (verify current state on the doc — these evolve):
  - Optional feature on SUPPORTED models; you mark cache checkpoints on a
    contiguous, STATIC prompt prefix. Editing the prefix causes a cache miss.
  - Per-model token minimums per checkpoint (e.g. some Claude models 1,024,
    others 4,096). Max 4 checkpoints per request (Claude); fields that accept
    checkpoints: system, messages, tools.
  - On-demand only (not batch). Order static content first, variable/user last.
Docs: https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html

Config from env:
    AWS_REGION   (default: us-east-1)
    MODEL_ID     (a prompt-caching-supported model id)

Run:
    MODEL_ID=<supported-model-id> python prompt_caching_converse.py
"""
import os

import boto3


def build_static_prefix() -> str:
    # A large, STABLE prefix (system prompt + reference docs) is the thing worth
    # caching. It must exceed the model's per-checkpoint minimum to be cached.
    # Kept short here for readability; in practice this is your full instruction
    # block + tool definitions + reference material.
    return (
        "You are a precise assistant. Answer only from the provided reference "
        "material. If the answer is not present, say so.\n\n"
        "<reference>\n"
        "... (a large, stable block of reference documentation goes here) ...\n"
        "</reference>"
    )


def converse_with_cache(question: str) -> dict:
    region = os.environ.get("AWS_REGION", "us-east-1")
    model_id = os.environ.get("MODEL_ID", "")  # supply a prompt-caching-supported model id
    if not model_id:
        raise SystemExit("Set MODEL_ID to a prompt-caching-supported model id.")
    client = boto3.client("bedrock-runtime", region_name=region)

    # Static content first, marked with a cachePoint. Variable user input last.
    system = [
        {"text": build_static_prefix()},
        {"cachePoint": {"type": "default"}},  # cache the prefix above
    ]
    messages = [
        {"role": "user", "content": [{"text": question}]},
    ]

    resp = client.converse(modelId=model_id, system=system, messages=messages)
    usage = resp.get("usage", {})
    # cacheReadInputTokens / cacheWriteInputTokens appear once caching is active.
    print("usage:", usage)
    return resp


if __name__ == "__main__":
    r = converse_with_cache("Summarize the reference in one sentence.")
    text = r["output"]["message"]["content"][0]["text"]
    print("answer:", text)
