# Hosting — companion code

Runnable companion code for the blog post **"MCP Hosting: From a Local Server to
an Account-Bounded One on AWS"**, part 3 of the *MCP Strategies on AWS* series.
It walks the hosting ladder from the AWS Prescriptive Guidance paper
[*Model Context Protocol strategies on AWS*](https://docs.aws.amazon.com/prescriptive-guidance/latest/mcp-strategies/mcp-strategies.pdf):
**local → remote → gateway.**

## What's here

| Path | Rung | Demonstrates |
|------|------|--------------|
| `local_server.py` | Local (stdio) | The "start here" MCP server. No client-to-server auth; runs as a subprocess. Official `mcp` SDK (FastMCP). |
| `cdk/` | Remote | AWS CDK (Python) for a Lambda Function URL with `AuthType=AWS_IAM` — a remote server **bounded to one AWS account**, not internet-facing. |
| `cdk/lambda/handler.py` | Remote | A minimal, stdlib-only MCP-over-JSON-RPC handler (`initialize`, `tools/list`, `tools/call`). |
| `sigv4_client.py` | Remote | An MCP client that SigV4-signs every request (service `lambda`) so the IAM-authed Function URL accepts it. |
| `deploy.sh` / `teardown.sh` | Remote | Deploy, demo in-account, and a trap-protected teardown that verifies the resources are gone. |

The **gateway** rung (Amazon Bedrock AgentCore Gateway) is discussed in the post
as the managed option; it is not deployed here.

## The local server

```bash
uv run --with mcp python local_server.py        # stdio MCP server
```

Point any MCP client at it. No network, no auth — the local starting point.

## The remote (account-bounded) server

The Function URL uses `AuthType=AWS_IAM`. That is the access boundary: every
request must be SigV4-signed by an IAM principal **in the deploying account**
that holds `lambda:InvokeFunctionUrl`. Unsigned or out-of-account callers get
`403` before the handler runs. There is no wildcard resource permission.

### Deploy, demo, and tear down

```bash
export MCP_ACCOUNT_ID=<your-account-id>
export MCP_REGION=eu-central-1
export MCP_PROFILE=<your-aws-profile>
# if your local cdk CLI lags the lib schema:
export CDK_CLI="npx --yes aws-cdk@latest"

bash deploy.sh
```

`deploy.sh` bootstraps (idempotent), deploys, runs the SigV4 client against the
live endpoint, fires an unsigned request as a negative control (expects `403`),
then **tears the stack down and verifies** it is gone. A `trap` on
`EXIT/SIGTERM/SIGINT` runs the teardown even if the script is killed mid-run.

### Extending to internet-facing (described, NOT deployed)

The account-bounded deploy here is the safe default. To expose it to the
internet you would, per the paper's governance pillar:

1. Swap the authorizer — replace `AuthType=AWS_IAM` with a JWT/OIDC authorizer
   (Amazon Cognito, or Amazon Bedrock AgentCore Identity issuing scoped tokens),
   or front the Lambda with an API Gateway HTTP API.
2. Validate the MCP `aud` (audience) claim so tokens minted for other servers
   are rejected (MCP spec requirement).
3. Add AWS WAF (rate-based + IP/geo rules) at the public edge.

These are deliberately left undeployed — see the CDK stack comments.

## Safety / cost notes

- No real account IDs in this code; everything comes from environment variables.
- The demo resources are Lambda + a Function URL: zero idle cost, and the deploy
  driver tears them down within about a minute.
- The handler makes no outbound calls and stores nothing.
