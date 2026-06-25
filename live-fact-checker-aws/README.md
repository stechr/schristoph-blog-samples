# Live Fact Checker on AWS

A proof-of-concept **claim-verification service** built on AWS. Inspired by browser-based
"fact-check a video" extensions, but re-architected around a clean seam:

> **A backend whose only job is: given a claim as text, return a verdict with evidence.**

Anything that can produce text (a web page, a meeting bot, a CLI, a browser extension) becomes a
client. This PoC ships the backend plus the simplest possible client — a paste-and-check web page.

## Demo

A ~45s narrated screencast of the paste-and-check (Extract) flow: paste a paragraph, claims are
identified and highlighted inline, then verified in parallel — each tile fills in with a verdict,
a confidence score, and cited, dated sources. Click a claim for the full explanation and sources.

The video is embedded in the accompanying blog post:
[**Live Fact Checker on AWS** — schristoph.online](https://schristoph.online/blog/live-fact-checker-aws/).

> The screen recording (`live-fact-checker-aws-demo.mp4`) is intentionally **not committed** —
> it is hosted alongside the blog post. Regenerate it from the running app + the `demo-video`
> workflow if needed.

## How it works

```
client (paste text / claim)
        │  HTTPS + Cognito JWT
        ▼
API Gateway ──► Lambda (extract)  ─► Claude on Amazon Bedrock (Converse)  → claims[]
            └─► Lambda (verify)   ─► AgentCore Web Search (managed grounding, MCP via Gateway)
                                   └► Claude on Amazon Bedrock (Converse)  → verdict + sources
```

1. **Extract** — `POST /v1/extract`: a transcript or document → a list of verifiable claims.
2. **Verify** — `POST /v1/verify`: a single claim → `TRUE | FALSE | UNCERTAIN` with a confidence
   score, an explanation, and cited sources (URLs + publication dates).

Grounding uses **Web Search on Amazon Bedrock AgentCore** — a managed, MCP-compliant tool backed
by an Amazon-operated web index, with results (snippets, URLs, publication dates) returned without
the query leaving AWS. Reasoning uses **Anthropic Claude on Amazon Bedrock** via the Converse API.

The service is **stateless** in this PoC — every request is self-contained (no session store).

## Layout

```
live-fact-checker-aws/
├── backend/          # Python: API contract models, prompts, grounding, Bedrock, Lambda handlers
├── infra/            # AWS CDK (Python): API Gateway + Cognito + Lambdas + IAM + Gateway setup
└── frontend/         # Static paste-and-check web app (vanilla JS)
```

## Run locally (no AWS, mock grounding)

The backend runs against a **mock grounding provider** so you can exercise the contract without
any AWS calls or credentials:

```bash
cd backend
uv sync
GROUNDING_PROVIDER=mock uv run python -m factchecker.demo "Inflation last year was over 200%."
```

Unit tests (mock grounding, no network):

```bash
cd backend && uv run pytest -q
```

## Deploy (PoC)

> Target: **us-east-1** (AgentCore Web Search is us-east-1 only at GA). Deploy into a development
> AWS account you control. Replace every `<ACCOUNT_ID>` / `<…>` placeholder with your own values;
> nothing account-specific is committed.

See [`infra/README.md`](./infra/) for the CDK deploy and the one-time AgentCore Gateway + Web
Search target setup.

## Configuration

All runtime config is via environment variables (see `backend/src/factchecker/config.py`):

| Var | Default | Purpose |
|---|---|---|
| `AWS_REGION` | `us-east-1` | Region for Bedrock + AgentCore |
| `GROUNDING_PROVIDER` | `agentcore` | `agentcore` (Web Search) or `mock` (local) |
| `AGENTCORE_GATEWAY_URL` | — | Gateway MCP endpoint (set after infra deploy) |
| `EXTRACT_MODEL_ID` | Claude Haiku | cheap pre-screen for `/extract` — **confirm the current ID at deploy** |
| `VERIFY_MODEL_ID` | Claude Sonnet | verdict reasoning for `/verify` — **confirm the current ID at deploy** |
| `MAX_WEB_RESULTS` | `10` | web-search results per claim (1–25) |

## Notes

- All sample data in this repository is **fictional** — no real companies, people, or numbers.
- This is a proof of concept, not production code: no persistence, minimal error handling, single
  region.

## License

MIT — see [LICENSE](./LICENSE).
