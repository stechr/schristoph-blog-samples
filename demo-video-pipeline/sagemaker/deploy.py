#!/usr/bin/env python3
"""
Deploy Qwen3-TTS as a SageMaker ASYNC inference endpoint (scale-to-zero).

Subcommands:
  precheck   Check ml.g5.xlarge endpoint-usage quota across candidate regions; pick one.
  create     Ensure role + bucket, package code/, create Model + async EndpointConfig + Endpoint.
  autoscale  Register application-autoscaling min=0 (run AFTER the endpoint is InService).
  status     Print endpoint status.

State is written to deploy_state.json (gitignored). No account IDs are committed.

Usage:
  python sagemaker/deploy.py precheck
  python sagemaker/deploy.py create
  python sagemaker/deploy.py status
  python sagemaker/deploy.py autoscale
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import boto3

REPO = Path(__file__).resolve().parent.parent
STATE_FILE = REPO / "deploy_state.json"
CODE_DIR = Path(__file__).resolve().parent  # contains inference.py + requirements.txt

CANDIDATE_REGIONS = ["us-east-1", "us-west-2", "eu-central-1"]
QUOTA_CODE = "L-1928E07B"  # ml.g5.xlarge for endpoint usage
INSTANCE_TYPE = os.environ.get("INSTANCE_TYPE", "ml.g5.xlarge")
PROJECT_TAG = os.environ.get("PROJECT_TAG", "qwen3-tts-video")
ENDPOINT_NAME = os.environ.get("ENDPOINT_NAME", "qwen3-tts-async")
ROLE_NAME = "qwen3-tts-sagemaker-exec-role"

# Candidate HF PyTorch inference DLC version tuples (transformers, pytorch, py).
# deploy tries them in order and uses the first whose image URI resolves.
DLC_CANDIDATES = [
    ("4.49.0", "2.6.0", "py312"),
    ("4.48.0", "2.3.0", "py311"),
    ("4.46.1", "2.3.0", "py311"),
    ("4.37.0", "2.1.0", "py310"),
]
TAGS = [{"Key": "project", "Value": PROJECT_TAG}]


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"[state] wrote {STATE_FILE}")


def pick_region():
    """Return first candidate region with sufficient g5.xlarge endpoint quota."""
    for r in CANDIDATE_REGIONS:
        try:
            sq = boto3.client("service-quotas", region_name=r)
            v = sq.get_service_quota(ServiceCode="sagemaker", QuotaCode=QUOTA_CODE)["Quota"]["Value"]
        except Exception as e:  # noqa: BLE001
            print(f"[precheck] {r}: quota lookup failed ({e})")
            continue
        print(f"[precheck] {r}: ml.g5.xlarge endpoint usage = {v}")
        if v >= 1:
            return r, v
    return None, 0


def ensure_role(region):
    iam = boto3.client("iam")
    try:
        return iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        pass
    print(f"[role] creating {ROLE_NAME}")
    trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"Service": "sagemaker.amazonaws.com"},
                       "Action": "sts:AssumeRole"}],
    }
    arn = iam.create_role(RoleName=ROLE_NAME, AssumeRolePolicyDocument=json.dumps(trust),
                          Tags=TAGS, Description="Qwen3-TTS async endpoint execution role")["Role"]["Arn"]
    for pol in ["arn:aws:iam::aws:policy/AmazonSageMakerFullAccess",
                "arn:aws:iam::aws:policy/AmazonS3FullAccess"]:
        iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=pol)
    print("[role] waiting for IAM propagation (15s)")
    time.sleep(15)
    return arn


def ensure_bucket(region, account):
    name = os.environ.get("S3_BUCKET") or f"sagemaker-qwen3-tts-{account}-{region}"
    s3 = boto3.client("s3", region_name=region)
    try:
        s3.head_bucket(Bucket=name)
    except Exception:  # noqa: BLE001
        print(f"[s3] creating bucket {name}")
        if region == "us-east-1":
            s3.create_bucket(Bucket=name)
        else:
            s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": region})
        s3.put_public_access_block(
            Bucket=name,
            PublicAccessBlockConfiguration={"BlockPublicAcls": True, "IgnorePublicAcls": True,
                                            "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
        try:
            s3.put_bucket_tagging(Bucket=name, Tagging={"TagSet": TAGS})
        except Exception as e:  # noqa: BLE001
            print(f"[s3] tagging skipped: {e}")
    return name


def cmd_precheck(_args):
    region, v = pick_region()
    if not region:
        print("QUOTA BLOCKED: request increase for L-1928E07B "
              "'ml.g5.xlarge for endpoint usage' in us-east-1/us-west-2/eu-central-1.")
        sys.exit(2)
    state = load_state()
    state.update({"region": region, "quota_g5xlarge": v})
    save_state(state)
    print(f"[precheck] selected region={region} (quota={v})")


def cmd_create(_args):
    import sagemaker
    from sagemaker.huggingface import HuggingFaceModel
    from sagemaker.async_inference import AsyncInferenceConfig

    state = load_state()
    region = state.get("region")
    if not region:
        region, v = pick_region()
        if not region:
            print("QUOTA BLOCKED — aborting create.")
            sys.exit(2)
        state["region"] = region
    os.environ["AWS_DEFAULT_REGION"] = region

    account = boto3.client("sts").get_caller_identity()["Account"]
    role = os.environ.get("SAGEMAKER_ROLE_ARN") or ensure_role(region)
    bucket = ensure_bucket(region, account)

    boto_sess = boto3.Session(region_name=region)
    sess = sagemaker.Session(boto_session=boto_sess, default_bucket=bucket)

    # Build an explicit model.tar.gz with code/{inference.py,requirements.txt}. Baking the
    # handler under code/ makes the HF/pytorch inference toolkit auto-detect our model_fn /
    # predict_fn (no HF_TASK fallback). This is more reliable than source_dir auto-packaging.
    import tarfile
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    tar_path = tmp / "model.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(CODE_DIR / "inference.py", arcname="code/inference.py")
        tar.add(CODE_DIR / "requirements.txt", arcname="code/requirements.txt")
    model_data = sess.upload_data(str(tar_path), bucket=bucket, key_prefix="model")
    print(f"[create] uploaded model artifact -> {model_data}")

    env = {
        "HF_MODEL_CUSTOM_VOICE": os.environ.get("HF_MODEL_CUSTOM_VOICE",
                                                "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
        "HF_MODEL_BASE": os.environ.get("HF_MODEL_BASE", "Qwen/Qwen3-TTS-12Hz-1.7B-Base"),
        "SAGEMAKER_PROGRAM": "inference.py",
        "SAGEMAKER_MODEL_SERVER_TIMEOUT": "900",
        "TS_DEFAULT_RESPONSE_TIMEOUT": "900",
    }

    last_err = None
    for (tv, pv, pyv) in DLC_CANDIDATES:
        try:
            print(f"[create] trying HF DLC transformers={tv} pytorch={pv} {pyv}")
            model = HuggingFaceModel(
                model_data=model_data, role=role, transformers_version=tv,
                pytorch_version=pv, py_version=pyv, env=env, sagemaker_session=sess,
            )
            async_cfg = AsyncInferenceConfig(
                output_path=f"s3://{bucket}/output/", failure_path=f"s3://{bucket}/error/",
                max_concurrent_invocations_per_instance=2)
            model.deploy(initial_instance_count=1, instance_type=INSTANCE_TYPE,
                         endpoint_name=ENDPOINT_NAME, async_inference_config=async_cfg,
                         tags=TAGS, wait=False)
            print(f"[create] endpoint creation started: {ENDPOINT_NAME} (region {region})")
            state.update({"endpoint_name": ENDPOINT_NAME, "bucket": bucket, "role": role,
                          "account": account, "dlc": f"{tv}/{pv}/{pyv}",
                          "instance_type": INSTANCE_TYPE, "model_data": model_data})
            save_state(state)
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[create] DLC {tv}/{pv}/{pyv} failed: {e}")
    print(f"[create] ALL DLC candidates failed. Last error: {last_err}")
    sys.exit(3)


def cmd_status(_args):
    state = load_state()
    region = state.get("region", "us-east-1")
    sm = boto3.client("sagemaker", region_name=region)
    name = state.get("endpoint_name", ENDPOINT_NAME)
    d = sm.describe_endpoint(EndpointName=name)
    print(f"{name}: {d['EndpointStatus']}  ({region})")
    if d.get("FailureReason"):
        print("FailureReason:", d["FailureReason"])
    print(d["EndpointStatus"])


def cmd_autoscale(_args):
    """Register min=0 / max=1 with a backlog target-tracking policy (scale from zero)."""
    state = load_state()
    region = state.get("region", "us-east-1")
    name = state.get("endpoint_name", ENDPOINT_NAME)
    aas = boto3.client("application-autoscaling", region_name=region)
    rid = f"endpoint/{name}/variant/AllTraffic"
    aas.register_scalable_target(
        ServiceNamespace="sagemaker", ResourceId=rid,
        ScalableDimension="sagemaker:variant:DesiredInstanceCount",
        MinCapacity=0, MaxCapacity=1)
    aas.put_scaling_policy(
        PolicyName="qwen3-tts-backlog-scaling", ServiceNamespace="sagemaker", ResourceId=rid,
        ScalableDimension="sagemaker:variant:DesiredInstanceCount",
        PolicyType="TargetTrackingScaling",
        TargetTrackingScalingPolicyConfiguration={
            "TargetValue": 2.0,
            "CustomizedMetricSpecification": {
                "MetricName": "ApproximateBacklogSizePerInstance", "Namespace": "AWS/SageMaker",
                "Dimensions": [{"Name": "EndpointName", "Value": name}], "Statistic": "Average"},
            "ScaleInCooldown": 300, "ScaleOutCooldown": 60})
    print(f"[autoscale] registered min=0 max=1 backlog target-tracking on {name}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    for c in ("precheck", "create", "status", "autoscale"):
        sub.add_parser(c)
    args = p.parse_args()
    {"precheck": cmd_precheck, "create": cmd_create,
     "status": cmd_status, "autoscale": cmd_autoscale}[args.cmd](args)


if __name__ == "__main__":
    main()
