# MCP Strategies on AWS — companion code

Runnable companion code for the four-part blog series **MCP Strategies on AWS**,
which turns the AWS Prescriptive Guidance paper
[*Model Context Protocol strategies on AWS*](https://docs.aws.amazon.com/prescriptive-guidance/latest/mcp-strategies/mcp-strategies.pdf)
into code you can run.

| Folder | Post | What it demonstrates |
|--------|------|----------------------|
| [`tool-design/`](tool-design/) | Tool Design, in Code | Token-tax counter (reproduces the 250-500 tok/tool claim), granular-vs-coarse tools, and a linter for the `<=8` params / `domain-noun-verb` / `<=50` tools rules. |
| [`hosting/`](hosting/) | Hosting, Local to AWS | A local stdio MCP server, and AWS CDK for a remote server bounded to one account (Lambda Function URL + `AWS_IAM`), with a SigV4 client and a trap-protected teardown. |
| [`governance/`](governance/) | Governance, in Code | Token-isolation demo (a hallucinated delete fails safely under a scoped token) and per-tool rate limiting with the standard `X-RateLimit-*` headers. |

## Conventions

- Python, the official `mcp` SDK, and the Strands Agents SDK.
- Demos run with [`uv`](https://docs.astral.sh/uv/) (`uv run --with ...`) or plain `pip`.
- No real AWS account IDs in the code — the hosting deploy reads account/region
  from environment variables, and tears everything down after the demo.
- Sample data uses fictional names (`octo/demo`, a mock DB service).

Each folder has its own README with a quickstart and the expected output.
