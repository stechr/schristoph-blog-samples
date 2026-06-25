#!/usr/bin/env python3
"""Add the managed Web Search connector target to the CDK-created AgentCore Gateway.

The Gateway + its IAM role are created by the CDK stack (L2 ``aws_bedrockagentcore.Gateway``).
Only the managed **web-search connector target** is added here, because that target type is not
yet representable in CloudFormation/CDK (``CfnGatewayTarget`` has no connector target as of
aws-cdk-lib 2.260). Run this ONCE, AFTER ``cdk deploy``.

  python setup_gateway.py                 # reads GatewayId from the deployed stack output
  python setup_gateway.py --gateway-id <id>

Requires boto3 >= 1.43.36 (the ``targetConfiguration.mcp.connector`` shape landed in 1.43.36).
Web Search is us-east-1 only at GA.
"""
from __future__ import annotations

import argparse
import sys

import boto3

STACK_NAME = "FactCheckerPoc"


def resolve_gateway_id(region: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    cfn = boto3.client("cloudformation", region_name=region)
    outs = cfn.describe_stacks(StackName=STACK_NAME)["Stacks"][0].get("Outputs", [])
    for o in outs:
        if o["OutputKey"] == "GatewayId":
            return o["OutputValue"]
    raise SystemExit(f"GatewayId output not found on stack {STACK_NAME}; pass --gateway-id.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--gateway-id", default=None, help="defaults to the FactCheckerPoc stack output")
    args = ap.parse_args()

    gateway_id = resolve_gateway_id(args.region, args.gateway_id)
    print(f"[..] adding web-search target to gateway {gateway_id}")

    gw = boto3.client("bedrock-agentcore-control", region_name=args.region)
    try:
        gw.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name="web-search-tool",
            targetConfiguration={
                "mcp": {
                    "connector": {
                        "source": {"connectorId": "web-search"},
                        "configurations": [{"name": "WebSearch", "parameterValues": {}}],
                    }
                }
            },
            credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        )
        print("[ok] web-search target added (tool name: web-search-tool___WebSearch)")
    except gw.exceptions.ConflictException:
        print("[ok] web-search target already exists — nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(main())
