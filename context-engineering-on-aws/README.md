# Context Engineering on AWS — companion code

Runnable, minimal AWS samples for the post
**[Context Engineering on AWS: From Prompt → Context → Memory](https://schristoph.online/blog/context-engineering-on-aws/)**.

Each script maps one rung of the context-engineering stack to a managed AWS service.
They are deliberately small — the point is to show the exact API call for each concept,
not a full application.

| Script | Concept | AWS surface |
|--------|---------|-------------|
| [`prompt_caching_converse.py`](prompt_caching_converse.py) | Reuse a stable context cheaply | Bedrock Converse `cachePoint` |
| [`knowledge_bases_retrieve.py`](knowledge_bases_retrieve.py) | Retrieval / semantic memory (RAG) | Bedrock Knowledge Bases `Retrieve` / `RetrieveAndGenerate` |
| [`agentcore_memory.py`](agentcore_memory.py) | Short-term + long-term agent memory | Bedrock AgentCore Memory `CreateEvent` + retrieve |
| [`titan_embeddings.py`](titan_embeddings.py) | Embeddings (the semantic substrate) | Amazon Titan Text Embeddings V2 |

See [`concept-to-service-mapping.md`](concept-to-service-mapping.md) for the full
context-engineering concept → AWS service table.

## Conventions

- Python + `boto3`. No account IDs, ARNs, or resource IDs in code — everything reads
  from environment variables (`AWS_REGION`, `KNOWLEDGE_BASE_ID`, `MEMORY_ID`, `MODEL_ID`, ...).
- Credentials come from your normal AWS credential chain (env vars, profile, SSO).
- All sample data is fictional. No real customers, numbers, or accounts.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export AWS_REGION=us-east-1

# 1) Embeddings — the cheapest to try
python titan_embeddings.py "Context engineering is precision, not volume."

# 2) Prompt caching (needs a caching-supported model id)
MODEL_ID=<supported-model-id> python prompt_caching_converse.py

# 3) Knowledge Bases retrieve (needs a KB you own)
KNOWLEDGE_BASE_ID=KB12345678 python knowledge_bases_retrieve.py "your question"

# 4) AgentCore Memory (needs a memory resource)
MEMORY_ID=MEM1234567890 python agentcore_memory.py
```

## Test status

- `titan_embeddings.py` — smoke-tested live against Titan Text Embeddings V2 (returns a
  1024-dim vector).
- `prompt_caching_converse.py`, `knowledge_bases_retrieve.py`, `agentcore_memory.py` —
  API shapes follow the official docs (linked in the mapping note); they require a
  caching-supported model / a Knowledge Base / a Memory resource you own, so they are
  **not live-tested here**. Verify the AgentCore data-plane shapes against your installed
  botocore, as those APIs evolve.

## References

- Prompt caching — https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html
- Knowledge Bases — https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html
- Titan Text Embeddings — https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html
- AgentCore Memory — https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html
- Guardrails — https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use.html

## License

MIT — see the [repository LICENSE](../LICENSE).
