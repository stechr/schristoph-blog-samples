"""Amazon Bedrock AgentCore Memory — short-term events + long-term extraction.

AgentCore Memory addresses agent statelessness with two levels:
  - Short-term memory: raw interaction events (user/assistant/tool) stored instantly
    via CreateEvent — immediate session context.
  - Long-term memory: persistent insights (preferences, semantic facts, summaries)
    extracted ASYNCHRONOUSLY across sessions by configured extraction strategies.
    You do NOT write long-term records directly.

Docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html

Note on SDK shape: the data-plane client id and operation shapes evolve. This sample
uses boto3.client("bedrock-agentcore") and defends against SDK/version differences by
catching UnknownServiceError and printing an upgrade hint rather than crashing. Verify
the exact CreateEvent / retrieve shapes against your installed botocore before relying
on them in production.

Config from env — no account IDs / memory ids hardcoded:
    AWS_REGION  (default: us-east-1)
    MEMORY_ID   (required, e.g. MEM1234567890)
    ACTOR_ID    (default: demo-user)
    SESSION_ID  (default: demo-session)
"""
import os
import time

import boto3
from botocore.exceptions import UnknownServiceError


def _client():
    region = os.environ.get("AWS_REGION", "us-east-1")
    try:
        return boto3.client("bedrock-agentcore", region_name=region)
    except UnknownServiceError:
        raise SystemExit(
            "Your botocore has no 'bedrock-agentcore' client — upgrade boto3/botocore "
            "to a version that ships the AgentCore data-plane APIs."
        )


def create_event(user_text: str, assistant_text: str) -> dict:
    """Store a raw interaction as a short-term memory event (immediate)."""
    client = _client()
    memory_id = os.environ["MEMORY_ID"]         # e.g. MEM1234567890 — from env
    actor_id = os.environ.get("ACTOR_ID", "demo-user")
    session_id = os.environ.get("SESSION_ID", "demo-session")

    return client.create_event(
        memoryId=memory_id,
        actorId=actor_id,
        sessionId=session_id,
        payload=[
            {"conversational": {"role": "USER", "content": {"text": user_text}}},
            {"conversational": {"role": "ASSISTANT", "content": {"text": assistant_text}}},
        ],
    )


def retrieve_long_term(query: str, top_k: int = 5) -> dict:
    """Retrieve consolidated long-term memory records (populated asynchronously)."""
    client = _client()
    memory_id = os.environ["MEMORY_ID"]
    return client.retrieve_memory_records(
        memoryId=memory_id,
        searchCriteria={"searchQuery": query, "topK": top_k},
    )


if __name__ == "__main__":
    ev = create_event(
        "Prefer Aurora pgvector so vectors sit beside relational data.",
        "Noted — I'll default to Aurora pgvector for this account.",
    )
    print("stored short-term event:", ev.get("event", {}).get("eventId", "(ok)"))
    time.sleep(1)
    print("long-term extraction runs asynchronously every few turns; "
          "retrieve_memory_records once strategies have processed the session.")
