"""FactChecker PoC stack — Cognito (JWT) + API Gateway (REST) + Lambdas + AgentCore Gateway.

Stateless: no DynamoDB. The verify Lambda grounds via AgentCore Web Search (a managed connector
target on the AgentCore Gateway) and reasons with Claude on Bedrock (Converse).

CDK coverage (aws-cdk-lib 2.260+):
- The **AgentCore Gateway** and its outbound IAM role ARE created here with the L2
  ``aws_bedrockagentcore.Gateway`` construct (AWS_IAM inbound auth).
- The managed **web-search connector target** is NOT yet representable in CloudFormation/CDK
  (``CfnGatewayTarget`` has no connector target type as of 2.260), so that single target is added
  out-of-band by ``setup_gateway.py`` after deploy. Everything else is CDK-native.
"""
import os

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
)
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

# backend/src holds the `factchecker` package; zero third-party deps (stdlib + boto3, both in the
# Lambda runtime), so the asset needs no bundling.
_BACKEND_SRC = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "src")

# Default model IDs — CONFIRM for the target account/region:  aws bedrock list-inference-profiles
EXTRACT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
VERIFY_MODEL_ID = "us.anthropic.claude-sonnet-4-6"

# AWS-owned ARN for the managed Web Search tool (us-east-1 at GA).
WEB_SEARCH_TOOL_ARN = "arn:aws:bedrock-agentcore:us-east-1:aws:tool/web-search.v1"


class FactCheckerStack(Stack):
    def __init__(self, scope: Construct, cid: str, **kwargs):
        super().__init__(scope, cid, **kwargs)

        # --- Cognito (inbound JWT auth) -------------------------------------
        user_pool = cognito.UserPool(
            self,
            "UserPool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            password_policy=cognito.PasswordPolicy(min_length=12),
        )
        user_pool_client = user_pool.add_client(
            "WebClient",
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
            generate_secret=False,
        )

        # --- AgentCore Gateway (L2) + its outbound role ---------------------
        # MCP gateway with IAM inbound auth (our verify Lambda signs requests with SigV4).
        gateway = agentcore.Gateway(
            self,
            "Gateway",
            gateway_name="fact-checker-gateway",
            authorizer_configuration=agentcore.GatewayAuthorizer.using_aws_iam(),
            description="Live Fact Checker — fronts the managed Web Search tool",
        )
        # The Gateway's own (outbound) role must be allowed to invoke the managed Web Search tool.
        gateway.role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeWebSearch"],
                resources=[WEB_SEARCH_TOOL_ARN],
            )
        )

        # --- Shared Lambda execution role -----------------------------------
        fn_role = iam.Role(
            self,
            "FnRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        # Bedrock Converse (Claude). Scoped to bedrock actions; resource "*" for the PoC — tighten
        # to the specific foundation-model / inference-profile ARNs for production.
        fn_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )
        # Inbound: allow the Lambdas to call the AgentCore Gateway (least-privilege via the L2 grant).
        gateway.grant_invoke(fn_role)

        common_env = {
            "GROUNDING_PROVIDER": "agentcore",
            "AGENTCORE_GATEWAY_URL": gateway.gateway_url,   # CDK reference — no manual wiring
            "EXTRACT_MODEL_ID": EXTRACT_MODEL_ID,
            "VERIFY_MODEL_ID": VERIFY_MODEL_ID,
            # NOTE: AWS_REGION is set automatically by the Lambda runtime — do not override it.
        }

        def make_fn(name: str, handler: str, timeout_s: int) -> lambda_.Function:
            return lambda_.Function(
                self,
                name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler=handler,
                code=lambda_.Code.from_asset(_BACKEND_SRC),
                role=fn_role,
                timeout=Duration.seconds(timeout_s),
                memory_size=512,
                environment=common_env,
            )

        extract_fn = make_fn("ExtractFn", "factchecker.handlers.extract_handler", 30)
        verify_fn = make_fn("VerifyFn", "factchecker.handlers.verify_handler", 60)
        batch_fn = make_fn("BatchFn", "factchecker.handlers.batch_handler", 120)

        # --- REST API + Cognito authorizer ----------------------------------
        api = apigw.RestApi(
            self,
            "Api",
            rest_api_name="fact-checker-poc",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=["POST", "OPTIONS"],
                allow_headers=["Content-Type", "Authorization"],
            ),
        )
        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "Authorizer", cognito_user_pools=[user_pool]
        )

        # CORS headers on error responses too — otherwise an authorizer 401 (expired/invalid token)
        # comes back with no CORS header and the browser reports an opaque "NetworkError".
        for rid, rtype in (("Cors4xx", apigw.ResponseType.DEFAULT_4_XX),
                           ("Cors5xx", apigw.ResponseType.DEFAULT_5_XX)):
            api.add_gateway_response(
                rid,
                type=rtype,
                response_headers={
                    "Access-Control-Allow-Origin": "'*'",
                    "Access-Control-Allow-Headers": "'Content-Type,Authorization'",
                },
            )

        v1 = api.root.add_resource("v1")
        extract_res = v1.add_resource("extract")
        extract_res.add_method(
            "POST", apigw.LambdaIntegration(extract_fn),
            authorizer=authorizer, authorization_type=apigw.AuthorizationType.COGNITO,
        )
        verify_res = v1.add_resource("verify")
        verify_res.add_method(
            "POST", apigw.LambdaIntegration(verify_fn),
            authorizer=authorizer, authorization_type=apigw.AuthorizationType.COGNITO,
        )
        batch_res = verify_res.add_resource("batch")
        batch_res.add_method(
            "POST", apigw.LambdaIntegration(batch_fn),
            authorizer=authorizer, authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # --- Outputs --------------------------------------------------------
        CfnOutput(self, "ApiUrl", value=api.url)
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)
        CfnOutput(self, "GatewayId", value=gateway.gateway_id)
        CfnOutput(self, "GatewayUrl", value=gateway.gateway_url)
