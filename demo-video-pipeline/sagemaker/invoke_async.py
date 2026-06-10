#!/usr/bin/env python3
"""
Invoke the Qwen3-TTS async endpoint: upload input JSON to S3, call
invoke_endpoint_async, poll the S3 output location, decode the wav.

Usage:
  python sagemaker/invoke_async.py --mode custom_voice --text "Hello." --speaker Aiden \
      --instruct "calm, professional" --out /tmp/out.wav
  python sagemaker/invoke_async.py --mode voice_clone --text "Cloned line." \
      --ref-audio https://.../clone.wav --ref-text "..." --out /tmp/clone.wav
"""
import argparse
import base64
import json
import os
import time
import uuid
from pathlib import Path

import boto3

STATE_FILE = Path(__file__).resolve().parent.parent / "deploy_state.json"


def _state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def synth(payload, out_path, timeout=1200, poll=10):
    st = _state()
    region = st.get("region", os.environ.get("AWS_REGION", "us-east-1"))
    endpoint = st.get("endpoint_name", os.environ.get("ENDPOINT_NAME", "qwen3-tts-async"))
    bucket = st.get("bucket") or os.environ["S3_BUCKET"]

    s3 = boto3.client("s3", region_name=region)
    smr = boto3.client("sagemaker-runtime", region_name=region)

    key = f"input/{uuid.uuid4()}.json"
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(payload).encode("utf-8"),
                  ContentType="application/json")
    input_s3 = f"s3://{bucket}/{key}"
    print(f"[invoke] uploaded {input_s3}")

    resp = smr.invoke_endpoint_async(EndpointName=endpoint, InputLocation=input_s3,
                                     ContentType="application/json")
    out_loc = resp["OutputLocation"]
    fail_loc = resp.get("FailureLocation")
    print(f"[invoke] output -> {out_loc}")

    def parse(loc):
        b = loc[5:]
        return b.split("/", 1)

    ob, ok = parse(out_loc)
    # Derive the failure location if the API didn't return one:
    # output/<id>.out  ->  error/<id>-error.out
    if not fail_loc:
        oid = ok.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        fail_loc = f"s3://{ob}/error/{oid}-error.out"
    fb, fk = parse(fail_loc)
    print(f"[invoke] failure -> s3://{fb}/{fk}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            obj = s3.get_object(Bucket=ob, Key=ok)
            raw = json.loads(obj["Body"].read())
            # The deployed endpoint may wrap the body as [body_json_str, content_type]
            # (a quirk of an output_fn that returned a tuple). Unwrap to a dict.
            if isinstance(raw, list) and raw:
                raw = raw[0]
            if isinstance(raw, str):
                raw = json.loads(raw)
            result = raw
            wav = base64.b64decode(result["audio_base64"])
            Path(out_path).write_bytes(wav)
            print(f"[invoke] OK sr={result.get('sample_rate')} -> {out_path}")
            return result
        except s3.exceptions.NoSuchKey:
            pass
        except Exception as e:  # noqa: BLE001
            if "NoSuchKey" not in str(e) and "Not Found" not in str(e):
                print(f"[invoke] poll output err: {e}")
        # Check failure location (also matches error/ prefix by inference id)
        try:
            err = s3.get_object(Bucket=fb, Key=fk)["Body"].read().decode("utf-8", "replace")
            raise RuntimeError(f"Inference FAILED: {err[:2000]}")
        except s3.exceptions.NoSuchKey:
            pass
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            if "NoSuchKey" not in str(e) and "Not Found" not in str(e):
                pass
        print(f"[invoke] waiting... ({int(deadline - time.time())}s left)")
        time.sleep(poll)
    raise TimeoutError(f"No output after {timeout}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["custom_voice", "voice_clone"], default="custom_voice")
    ap.add_argument("--text", required=True)
    ap.add_argument("--language", default="en")
    ap.add_argument("--speaker", default="Aiden")
    ap.add_argument("--instruct", default=None)
    ap.add_argument("--ref-audio", default=None)
    ap.add_argument("--ref-text", default="")
    ap.add_argument("--out", default="/tmp/qwen_tts_out.wav")
    a = ap.parse_args()

    if a.mode == "custom_voice":
        payload = {"mode": "custom_voice", "text": a.text, "language": a.language,
                   "speaker": a.speaker}
        if a.instruct:
            payload["instruct"] = a.instruct
    else:
        if not a.ref_audio:
            ap.error("--ref-audio required for voice_clone")
        payload = {"mode": "voice_clone", "text": a.text, "language": a.language,
                   "ref_audio": a.ref_audio, "ref_text": a.ref_text}
    synth(payload, a.out)


if __name__ == "__main__":
    main()
