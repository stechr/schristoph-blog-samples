#!/usr/bin/env bash
# Tear down the Qwen3-TTS async endpoint (endpoint + config + model).
# Does NOT delete the S3 bucket or IAM role by default (uncomment to remove).
# Reads region + names from deploy_state.json (gitignored).
set -euo pipefail
export PATH="/usr/local/bin:$PATH"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$DIR/deploy_state.json"

REGION="$(python3 -c "import json;print(json.load(open('$STATE')).get('region','us-east-1'))" 2>/dev/null || echo us-east-1)"
EP="$(python3 -c "import json;print(json.load(open('$STATE')).get('endpoint_name','qwen3-tts-async'))" 2>/dev/null || echo qwen3-tts-async)"

echo "Tearing down endpoint '$EP' in $REGION ..."

# Deregister autoscaling (ignore errors)
aws application-autoscaling deregister-scalable-target \
  --service-namespace sagemaker \
  --resource-id "endpoint/$EP/variant/AllTraffic" \
  --scalable-dimension sagemaker:variant:DesiredInstanceCount \
  --region "$REGION" 2>/dev/null || true

# SCOPED model deletion: capture the model(s) THIS endpoint's config references BEFORE
# deleting the config, then delete only those. NEVER glob by DLC framework name
# (contains(ModelName,'huggingface-pytorch')) — that matches EVERY HF DLC model across
# ALL projects in the account and irreversibly deletes unrelated ones.
MODELS="$(aws sagemaker describe-endpoint-config --endpoint-config-name "$EP" --region "$REGION" \
            --query 'ProductionVariants[].ModelName' --output text 2>/dev/null || true)"
[ -z "$MODELS" ] && MODELS="$(python3 -c "import json;print(json.load(open('$STATE')).get('model_name',''))" 2>/dev/null || true)"

aws sagemaker delete-endpoint --endpoint-name "$EP" --region "$REGION" 2>/dev/null || true
aws sagemaker delete-endpoint-config --endpoint-config-name "$EP" --region "$REGION" 2>/dev/null || true
for M in $MODELS; do
  [ -n "$M" ] || continue
  echo "  deleting model $M (scoped to this endpoint's config)"
  aws sagemaker delete-model --model-name "$M" --region "$REGION" 2>/dev/null || true
done

echo "Done. (S3 bucket + IAM role left intact — delete manually if desired.)"
# To also remove the bucket:  aws s3 rb s3://<bucket> --force --region "$REGION"
# To remove the role: detach policies then  aws iam delete-role --role-name qwen3-tts-sagemaker-exec-role
