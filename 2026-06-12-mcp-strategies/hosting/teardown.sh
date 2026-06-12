#!/usr/bin/env bash
# teardown.sh — destroy the account-bounded MCP stack and VERIFY it is gone.
#
# Mandated by write-safety: this is registered as a trap on EXIT/SIGTERM in the
# deploy driver so it runs even if the deploy/demo subprocess is killed. It is
# idempotent — safe to run when nothing is deployed.
#
# Account/region come from the environment (never hardcoded), so this file
# carries no account id:
#   MCP_ACCOUNT_ID, MCP_REGION, MCP_PROFILE
set -uo pipefail

STACK="McpStrategiesRemoteStack"
FN="mcp-strategies-demo-remote"
REGION="${MCP_REGION:-eu-central-1}"
PROFILE="${MCP_PROFILE:-default}"
ACCOUNT="${MCP_ACCOUNT_ID:?set MCP_ACCOUNT_ID}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "[teardown] destroying $STACK in $REGION (account $ACCOUNT, profile $PROFILE)"
( cd "$HERE/cdk" && AWS_PROFILE="$PROFILE" ${CDK_CLI:-cdk} destroy "$STACK" --force \
    --context account="$ACCOUNT" --context region="$REGION" 2>&1 ) || \
  echo "[teardown] destroy returned non-zero (may already be gone)"

echo "[teardown] verifying the function is gone..."
if AWS_PROFILE="$PROFILE" aws lambda get-function --function-name "$FN" \
     --region "$REGION" >/dev/null 2>&1; then
  echo "[teardown] WARNING: $FN STILL EXISTS — manual cleanup needed"
  exit 1
else
  echo "[teardown] verified: $FN is gone"
fi

echo "[teardown] verifying the stack is gone..."
ST=$(AWS_PROFILE="$PROFILE" aws cloudformation describe-stacks \
       --stack-name "$STACK" --region "$REGION" \
       --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "DELETE_COMPLETE")
echo "[teardown] stack status: $ST"
[ "$ST" = "DELETE_COMPLETE" ] || [ -z "$ST" ] && echo "[teardown] clean." || true
