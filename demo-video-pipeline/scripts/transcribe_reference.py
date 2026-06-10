#!/usr/bin/env python3
"""transcribe_reference.py — transcribe a voice reference clip to its EXACT words.

The Qwen3-TTS voice_clone backend needs the literal transcript of the reference clip
(``ref_audio.wav``) as ``REF_TEXT``. A wrong/placeholder transcript makes generation run
long and the async call time out. This script runs the clip through Amazon Transcribe and
writes the plain transcript to ``ref_text.txt``.

Flow: upload the clip to an Amazon S3 bucket → start a Transcribe job → poll until done →
download the result JSON → write the plain transcript text.

Usage:
    .venv/bin/python scripts/transcribe_reference.py --audio ref_audio.wav --out ref_text.txt

Region comes from --region, then AWS_REGION / AWS_DEFAULT_REGION, else us-east-1.
Bucket comes from --bucket, then the S3_BUCKET env var, then deploy_state.json (if a Qwen
endpoint was deployed), else a per-account default ``transcribe-ref-{account}-{region}``
created on demand (private). Only standard AWS creds on the default chain are required.
"""
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_region(cli_region):
    return (cli_region or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1")


def resolve_bucket(cli_bucket, region, account):
    if cli_bucket:
        return cli_bucket
    if os.environ.get("S3_BUCKET"):
        return os.environ["S3_BUCKET"]
    state = REPO_ROOT / "deploy_state.json"
    if state.exists():
        try:
            b = json.loads(state.read_text()).get("bucket")
            if b:
                return b
        except Exception:  # noqa: BLE001
            pass
    return f"transcribe-ref-{account}-{region}"


def ensure_bucket(s3, bucket, region):
    try:
        s3.head_bucket(Bucket=bucket)
        return
    except ClientError:
        print(f"[s3] creating bucket {bucket}")
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(Bucket=bucket,
                             CreateBucketConfiguration={"LocationConstraint": region})
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            },
        )


def main():
    ap = argparse.ArgumentParser(description="Transcribe a voice reference clip via Amazon Transcribe.")
    ap.add_argument("--audio", default="ref_audio.wav", help="reference clip (wav/mp3/m4a/flac)")
    ap.add_argument("--out", default="ref_text.txt", help="output transcript file")
    ap.add_argument("--region", help="AWS region (default: env or us-east-1)")
    ap.add_argument("--bucket", help="S3 bucket for the Transcribe input/output")
    ap.add_argument("--language", default="en-US", help="language code (default en-US)")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        sys.exit(f"ERROR: audio file not found: {audio}")

    region = resolve_region(args.region)
    account = boto3.client("sts").get_caller_identity()["Account"]
    bucket = resolve_bucket(args.bucket, region, account)

    s3 = boto3.client("s3", region_name=region)
    transcribe = boto3.client("transcribe", region_name=region)

    ensure_bucket(s3, bucket, region)

    ext = audio.suffix.lstrip(".").lower() or "wav"
    fmt = {"wav": "wav", "mp3": "mp3", "m4a": "mp4", "mp4": "mp4", "flac": "flac",
           "ogg": "ogg", "amr": "amr", "webm": "webm"}.get(ext, "wav")
    key = f"transcribe-ref/{uuid.uuid4().hex}.{ext}"
    print(f"[s3] uploading {audio} → s3://{bucket}/{key}")
    s3.upload_file(str(audio), bucket, key)

    job = f"ref-transcribe-{uuid.uuid4().hex[:12]}"
    print(f"[transcribe] starting job {job} ({region}, {args.language})")
    transcribe.start_transcription_job(
        TranscriptionJobName=job,
        LanguageCode=args.language,
        MediaFormat=fmt,
        Media={"MediaFileUri": f"s3://{bucket}/{key}"},
    )

    # Poll
    while True:
        d = transcribe.get_transcription_job(TranscriptionJobName=job)["TranscriptionJob"]
        status = d["TranscriptionJobStatus"]
        if status in ("COMPLETED", "FAILED"):
            break
        print(f"[transcribe] {status} …")
        time.sleep(5)

    if status == "FAILED":
        sys.exit(f"ERROR: transcription failed: {d.get('FailureReason')}")

    uri = d["Transcript"]["TranscriptFileUri"]
    # Result is a presigned/public-readable S3 URL; fetch with urllib (no extra deps).
    import urllib.request
    with urllib.request.urlopen(uri) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    text = result["results"]["transcripts"][0]["transcript"].strip()

    Path(args.out).write_text(text + "\n")
    print(f"\n[done] transcript → {args.out}\n")
    print("--- transcript ---")
    print(text)
    print("------------------")
    print("\nConfirm the words above are exactly what you said, then render:")
    print(f'  make demo-clone REF_AUDIO={args.audio} REF_TEXT="$(cat {args.out})"')

    # Best-effort cleanup of the uploaded input + finished job.
    try:
        s3.delete_object(Bucket=bucket, Key=key)
        transcribe.delete_transcription_job(TranscriptionJobName=job)
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
