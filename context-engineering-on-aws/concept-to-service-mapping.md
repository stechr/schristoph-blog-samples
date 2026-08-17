# Concept → AWS service mapping

How each context-engineering concept maps to a managed AWS capability. Every claim
here traces to an official AWS doc; none of these ships "on" by default — each is a
service you configure and integrate.

| Context-engineering concept | AWS service / feature | Notes |
|---|---|---|
| Working memory (context window) | Bedrock model context window | Exact window is per-model — read the model card |
| Reuse a stable context cheaply | **Bedrock prompt caching** | Per-model minimum tokens per checkpoint; ≤4 checkpoints (Claude); on-demand only; static-first ordering |
| Retrieval / semantic memory (RAG) | **Bedrock Knowledge Bases** | Managed ingest → chunk → embed → store; `Retrieve` / `RetrieveAndGenerate` |
| Chunking | Knowledge Bases chunking config | default (~300 tok) / fixed / semantic / hierarchical |
| Embeddings | **Titan Text Embeddings V2** / Cohere Embed v3 | Titan v2: 1024/512/256 dims, up to 8,192 input tokens |
| Vector store | **OpenSearch Serverless**, **Aurora pgvector**, Pinecone, Redis, S3 Vectors, Neptune Analytics | Separate resource, own scaling/billing |
| Managed permission-aware search | **Amazon Kendra** | Automatic permission mapping + connectors |
| Short-term + long-term agent memory | **Bedrock AgentCore Memory** | `CreateEvent` (STM) + async extraction strategies (LTM) |
| Graph-shaped knowledge (GraphRAG) | Amazon Neptune / Neptune Analytics | Relationship-heavy retrieval |
| Orchestration (assemble context per turn) | **Bedrock Agents** | Retrieve + Memory + tools |
| Runtime governance | **Bedrock Guardrails** | jailbreak / prompt injection / prompt leakage + contextual grounding |
| Observe context drift | CloudWatch + CloudTrail | Coverage = the instrumentation you enable |

## Sources

- Prompt caching — https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html
- Knowledge Bases — https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html
- Titan Text Embeddings — https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html
- AgentCore Memory — https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html
- Guardrails — https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use.html

_All sample data in this folder is fictional. No real accounts, ARNs, or customer data._
