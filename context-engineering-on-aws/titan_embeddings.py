"""Amazon Titan Text Embeddings V2 — the semantic-memory substrate.

Embeds text into a vector you can store in a vector index (OpenSearch Serverless,
Aurora pgvector, ...). Titan Text Embeddings V2 supports output dimensions of
1024 (default), 512, or 256, and up to 8,192 input tokens.

Docs: https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html

Config is read from the environment — no account IDs or ARNs in code:
    AWS_REGION           (default: us-east-1)
    TITAN_EMBED_MODEL_ID (default: amazon.titan-embed-text-v2:0)

Run:
    python titan_embeddings.py "Why did the Acme migration stall last quarter?"
"""
import json
import os
import sys

import boto3


def embed(text: str, dimensions: int = 1024, normalize: bool = True) -> list[float]:
    region = os.environ.get("AWS_REGION", "us-east-1")
    model_id = os.environ.get("TITAN_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
    client = boto3.client("bedrock-runtime", region_name=region)

    body = {
        "inputText": text,
        "dimensions": dimensions,   # 1024 | 512 | 256
        "normalize": normalize,
    }
    resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
    payload = json.loads(resp["body"].read())
    return payload["embedding"]


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "Context engineering is precision, not volume."
    vec = embed(text)
    print(f"input: {text!r}")
    print(f"dimensions: {len(vec)}")
    print(f"first 8 values: {[round(v, 4) for v in vec[:8]]}")
