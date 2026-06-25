#!/usr/bin/env python3
"""CDK app for the Live Fact Checker PoC backend.

Deploy (us-east-1, a dev account you control):

    cd infra
    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    cdk bootstrap
    cdk deploy                       # creates Cognito + API + Lambdas + AgentCore Gateway + role
    python setup_gateway.py          # adds the managed web-search target to the gateway (one-off)
"""
import os

import aws_cdk as cdk

from stacks.factchecker_stack import FactCheckerStack

app = cdk.App()

FactCheckerStack(
    app,
    "FactCheckerPoc",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
)

app.synth()
