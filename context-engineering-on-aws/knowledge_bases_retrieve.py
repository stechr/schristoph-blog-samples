"""Amazon Bedrock Knowledge Bases — managed RAG retrieval.

Two read APIs:
  - Retrieve:            embed the query, return matching chunks + scores. YOU decide
                         what enters the context window (the precision lever).
  - RetrieveAndGenerate: retrieval + generation in one call, with traceable sources.

For context-engineering CONTROL you usually want Retrieve, so you own what goes
into the window and how much (numberOfResults = the recall-vs-noise knob).

Docs: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html
      (Retrieve / RetrieveAndGenerate under the bedrock-agent-runtime client)

Config from env — no account IDs / KB ids hardcoded:
    AWS_REGION        (default: us-east-1)
    KNOWLEDGE_BASE_ID (required, e.g. KB12345678)
    KB_MODEL_ARN      (required only for retrieve_and_generate)

Run:
    KNOWLEDGE_BASE_ID=KB12345678 python knowledge_bases_retrieve.py "your question"
"""
import os
import sys

import boto3


def retrieve(query: str, num_results: int = 8) -> list[dict]:
    region = os.environ.get("AWS_REGION", "us-east-1")
    kb_id = os.environ["KNOWLEDGE_BASE_ID"]  # e.g. KB12345678 — from env, never hardcode
    client = boto3.client("bedrock-agent-runtime", region_name=region)

    resp = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": num_results}  # fewer = less noise
        },
    )
    return resp["retrievalResults"]


def retrieve_and_generate(query: str) -> dict:
    region = os.environ.get("AWS_REGION", "us-east-1")
    kb_id = os.environ["KNOWLEDGE_BASE_ID"]
    model_arn = os.environ["KB_MODEL_ARN"]  # e.g. arn:aws:bedrock:<region>::foundation-model/<id>
    client = boto3.client("bedrock-agent-runtime", region_name=region)

    return client.retrieve_and_generate(
        input={"text": query},
        retrieveAndGenerateConfiguration={
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {"knowledgeBaseId": kb_id, "modelArn": model_arn},
        },
    )


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Why did the migration stall last quarter?"
    for r in retrieve(q):
        print(round(r.get("score", 0.0), 4), r["content"]["text"][:120])
