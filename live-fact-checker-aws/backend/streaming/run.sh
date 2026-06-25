#!/usr/bin/env bash
# Launch the live streaming fact-check server with grounding configured.
#
#   AGENTCORE_GATEWAY_URL='https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp' \
#     ./streaming/run.sh
#
# (or export GROUNDING_PROVIDER=mock to run without AgentCore Web Search)
set -euo pipefail

if [[ "${GROUNDING_PROVIDER:-agentcore}" == "agentcore" ]]; then
  : "${AGENTCORE_GATEWAY_URL:?Set AGENTCORE_GATEWAY_URL to your AgentCore Gateway MCP endpoint (or export GROUNDING_PROVIDER=mock)}"
fi

cd "$(dirname "$0")/.."   # -> backend/
exec uv run --with amazon-transcribe --with websockets python streaming/server.py
