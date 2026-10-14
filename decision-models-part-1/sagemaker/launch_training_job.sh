#!/usr/bin/env bash
# Start the decision-model training run as a SageMaker AI training job.
# Needs: AWS CLI v2, an S3 bucket you own, and a SageMaker execution role that can
# read/write that bucket and write CloudWatch logs. Nothing here is account-specific.
#
#   BUCKET=my-bucket ROLE_ARN=arn:aws:iam::<ACCOUNT_ID>:role/<ROLE> ./launch_training_job.sh
set -euo pipefail
: "${BUCKET:?set BUCKET}" "${ROLE_ARN:?set ROLE_ARN}"
REGION="${AWS_REGION:-eu-central-1}"
INSTANCE="${INSTANCE:-ml.g6.xlarge}"          # one NVIDIA L4, 24 GB, bfloat16
JOB="decision-model-$(date -u +%Y%m%d-%H%M%S)"
PREFIX="decision-models"
# AWS Deep Learning Container, PyTorch 2.8 training, GPU. Registry account per Region:
# https://github.com/aws/deep-learning-containers/blob/master/available_images.md
IMAGE="${IMAGE:?set IMAGE to the pytorch-training:2.8.0-gpu-py312-cu129-ubuntu22.04-sagemaker URI for $REGION}"

HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
cp "$HERE/train_entry.py" "$HERE/../train_unsloth.py" "$TMP/"
tar -czf "$TMP/source.tar.gz" -C "$TMP" train_entry.py train_unsloth.py
aws s3 cp "$TMP/source.tar.gz" "s3://$BUCKET/$PREFIX/code/$JOB/source.tar.gz" --region "$REGION"

aws sagemaker create-training-job --region "$REGION" \
  --training-job-name "$JOB" \
  --role-arn "$ROLE_ARN" \
  --algorithm-specification "TrainingImage=$IMAGE,TrainingInputMode=File" \
  --hyper-parameters "{\"sagemaker_program\":\"\\\"train_entry.py\\\"\",\"sagemaker_submit_directory\":\"\\\"s3://$BUCKET/$PREFIX/code/$JOB/source.tar.gz\\\"\"}" \
  --resource-config "InstanceType=$INSTANCE,InstanceCount=1,VolumeSizeInGB=100" \
  --output-data-config "S3OutputPath=s3://$BUCKET/$PREFIX/jobs/" \
  --stopping-condition "MaxRuntimeInSeconds=7200" \
  --tags ${TAGS:-Key=Project,Value=decision-models}
echo "$JOB"
