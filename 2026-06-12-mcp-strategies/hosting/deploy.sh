#!/usr/bin/env bash
# deploy.sh — deploy the account-bounded MCP server, demo it in-account, tear it down.
#
# write-safety: a teardown trap is registered on EXIT/SIGTERM/SIGINT BEFORE the
# deploy, so the stack is destroyed even if this script (or a child) is killed.
#
# Required env (no secrets are hardcoded):
#   MCP_ACCOUNT_ID  - 12-digit deploying account id
#   MCP_REGION      - e.g. eu-central-1
#   MCP_PROFILE     - AWS CLI profile with creds for that account
set -uo pipefail

REGION="${MCP_REGION:?set MCP_REGION}"
PROFILE="${MCP_PROFILE:?set MCP_PROFILE}"
ACCOUNT="${MCP_ACCOUNT_ID:?set MCP_ACCOUNT_ID}"
STACK="McpStrategiesRemoteStack"
HERE="$(cd "$(dirname "$0")" && pwd)"
export AWS_PROFILE="$PROFILE"
export PATH="/usr/local/bin:$PATH"

# --- MANDATORY teardown trap (survives a killed child) ----------------------
cleanup() { echo; echo ">>> TRAP: running teardown"; bash "$HERE/teardown.sh"; }
trap cleanup EXIT SIGTERM SIGINT

echo ">>> bootstrap (idempotent)"
( cd "$HERE/cdk" && ${CDK_CLI:-cdk} bootstrap "aws://$ACCOUNT/$REGION" \
    --context account="$ACCOUNT" --context region="$REGION" 2>&1 | tail -3 )

echo ">>> deploy"
( cd "$HERE/cdk" && ${CDK_CLI:-cdk} deploy "$STACK" --require-approval never \
    --context account="$ACCOUNT" --context region="$REGION" \
    --outputs-file /tmp/mcp-outputs.json 2>&1 | tail -15 )

URL=$(python3 -c "import json;print(json.load(open('/tmp/mcp-outputs.json'))['$STACK']['FunctionUrl'])")
echo ">>> deployed Function URL: $URL"

echo ">>> DEMO: SigV4-signed in-account client"
uv run --with boto3 --with botocore python "$HERE/sigv4_client.py" "$URL" 2>&1

echo ">>> DEMO: negative control — unsigned curl should be 403"
curl -s -o /dev/null -w "unsigned GET status: %{http_code}\n" "$URL"

echo ">>> explicit teardown (trap will also run as backstop)"
bash "$HERE/teardown.sh"
trap - EXIT  # teardown already ran cleanly; don't double-run
echo ">>> done"
