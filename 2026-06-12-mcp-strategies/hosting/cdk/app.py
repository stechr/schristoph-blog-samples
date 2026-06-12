#!/usr/bin/env python3
"""CDK app: a REMOTE MCP server that is bounded to a single AWS account.

It deploys one Lambda function fronted by a Lambda Function URL with
`AuthType = AWS_IAM`. That is the access-limiting mechanism:

  - The Function URL lives on a public hostname, but EVERY request must be
    SigV4-signed by an IAM principal that holds `lambda:InvokeFunctionUrl` on
    THIS function. Unsigned or out-of-account callers are rejected with 403
    before the handler runs.
  - We do NOT add a wildcard resource-based permission. Only principals in the
    deploying account (granted via IAM) can invoke it. That is the account
    boundary.

How to EXTEND this to internet-facing (described, NOT deployed here):
  - Switch the Function URL to `AuthType = NONE` (or front it with API Gateway
    HTTP API) and put a JWT/OIDC authorizer in front — e.g. Amazon Cognito or
    Amazon Bedrock AgentCore Identity issuing scoped tokens.
  - Add AWS WAF (rate-based + IP/geo rules) on the public edge.
  - Require the MCP `aud` (audience) claim to match this server, per the MCP
    spec, so tokens minted for other servers are rejected.
  None of those are enabled here on purpose: this deploy stays account-bounded.
"""
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_lambda as _lambda,
)
from constructs import Construct


class McpRemoteStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        fn = _lambda.Function(
            self,
            "McpServer",
            function_name="mcp-strategies-demo-remote",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambda"),
            timeout=Duration.seconds(15),
            memory_size=256,
            environment={"MCP_ACCOUNT_ID": self.account},
            description="Account-bounded MCP server (Function URL, AWS_IAM auth) "
                        "for the MCP-strategies blog series. Not internet-facing.",
        )

        # AWS_IAM auth = account boundary. No CORS (not browser-facing).
        fn_url = fn.add_function_url(
            auth_type=_lambda.FunctionUrlAuthType.AWS_IAM,
        )

        CfnOutput(self, "FunctionUrl", value=fn_url.url,
                  description="SigV4-signed (service 'lambda') endpoint")
        CfnOutput(self, "FunctionName", value=fn.function_name)
        CfnOutput(self, "AccountId", value=self.account)
        CfnOutput(self, "Region", value=self.region)


app = cdk.App()
McpRemoteStack(
    app,
    "McpStrategiesRemoteStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region"),
    ),
)
app.synth()
