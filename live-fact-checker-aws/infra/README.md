# Infrastructure (AWS CDK, Python)

Provisions the PoC backend in **us-east-1**:

- **Amazon Cognito** user pool + app client (inbound JWT auth)
- **API Gateway** (REST) — `POST /v1/extract`, `POST /v1/verify`, `POST /v1/verify/batch`,
  protected by a Cognito authorizer, CORS enabled
- **3 Lambda functions** (extract / verify / batch) — code asset is `../backend/src` (zero
  third-party deps; boto3/botocore are in the runtime)
- **IAM** — `bedrock:InvokeModel` (Converse); the Lambdas are granted `InvokeGateway` on the gateway
- **AgentCore Gateway + its IAM role** — created in-stack via the L2 `aws_bedrockagentcore.Gateway`
  construct (AWS_IAM inbound auth; the gateway role is granted `bedrock-agentcore:InvokeWebSearch`)

Only the managed **web-search connector target** is added out-of-band by `setup_gateway.py`, because
that target type is not yet in CloudFormation/CDK (`CfnGatewayTarget` has no connector target as of
aws-cdk-lib 2.260). Everything else is CDK-native.

## Prerequisites

- An AWS account you control (this PoC targets the **work/dev account** — pin your profile).
- AWS CDK v2 (`npm i -g aws-cdk`), Python 3.12, Node 18+.
- Bedrock model access enabled for the chosen Claude models in us-east-1.

> The Node CDK CLI may not pick up an SSO profile via `AWS_PROFILE`. If `cdk deploy` reports
> "no credentials", export them first:
> `eval "$(aws configure export-credentials --profile <profile> --format env)"`

## Deploy

```bash
cd infra
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 1) Bootstrap (first time per account/region) and deploy — creates Cognito, the API, the
#    Lambdas, AND the AgentCore Gateway + its IAM role:
cdk bootstrap
cdk deploy

# 2) Add the managed web-search connector target to the gateway (one-off; not yet in CFN/CDK):
python setup_gateway.py --region us-east-1
```

Outputs: `ApiUrl`, `UserPoolId`, `UserPoolClientId`, `GatewayId`, `GatewayUrl`. Create a test user
in the pool, get a JWT, and point the frontend (`../frontend`) at `ApiUrl`.

## Confirm model IDs before deploy

`EXTRACT_MODEL_ID` (Haiku) and `VERIFY_MODEL_ID` (Sonnet) in `stacks/factchecker_stack.py` are
defaults to **confirm** for your account/region:

```bash
aws bedrock list-inference-profiles --region us-east-1
```

## Teardown (after the PoC)

```bash
cdk destroy   # removes Cognito, API, Lambdas, AND the AgentCore Gateway + role (all CDK-managed)
# The web-search TARGET is the only non-CDK resource. If destroy complains about the gateway
# having a target, delete the target first:
#   aws bedrock-agentcore-control delete-gateway-target --gateway-identifier <GatewayId> --target-id <tid>
```

> Cost note: AgentCore Web Search is **$7 / 1,000 queries** plus Bedrock token usage. There is no
> persistent compute beyond Lambda; tear everything down when finished.
