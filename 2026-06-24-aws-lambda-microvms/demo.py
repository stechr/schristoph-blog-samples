#!/usr/bin/env python3
"""
Demo driver: Bedrock generates Python -> runs it in a per-session Lambda MicroVM.

Usage:
  python demo.py --microvm-id microvm-xxxx --endpoint <endpoint> \
      --task "compute the 20th Fibonacci number" \
      [--model eu.anthropic.claude-sonnet-4-5-20250929-v1:0] [--region eu-west-1]

If --token is omitted, the driver mints a short-lived auth token for port 8080.
"""
import argparse
import json
import re
import sys
import urllib.request

import boto3

CODEGEN_SYSTEM = (
    "You write small, self-contained Python 3 snippets that run in a sandbox. "
    "Rules: assign the final answer to a variable named RESULT. "
    "Use only the Python standard library unless told otherwise. "
    "Output ONLY the code, no prose, no markdown fences."
)


def generate_code(bedrock, model: str, task: str) -> str:
    resp = bedrock.converse(
        modelId=model,
        system=[{"text": CODEGEN_SYSTEM}],
        messages=[{"role": "user", "content": [{"text": f"Task: {task}"}]}],
        inferenceConfig={"maxTokens": 800, "temperature": 0},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    # Strip accidental code fences.
    text = re.sub(r"^```(?:python)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    return text.strip()


def mint_token(region: str, microvm_id: str) -> str:
    mv = boto3.client("lambda-microvms", region_name=region)
    tok = mv.create_microvm_auth_token(
        microvmIdentifier=microvm_id,
        expirationInMinutes=30,
        allowedPorts=[{"port": 8080}],
    )
    return tok["authToken"]["X-aws-proxy-auth"]


def call_microvm(endpoint: str, token: str, path: str, body: dict | None = None):
    url = f"https://{endpoint}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET")
    req.add_header("X-aws-proxy-auth", token)
    req.add_header("X-aws-proxy-port", "8080")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--microvm-id", required=True)
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--model", default="eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
    ap.add_argument("--region", default="eu-west-1")
    ap.add_argument("--token", default=None)
    args = ap.parse_args()

    bedrock = boto3.client("bedrock-runtime", region_name=args.region)

    print(f"\n[1] Asking Bedrock ({args.model}) to write code for:\n    \"{args.task}\"")
    code = generate_code(bedrock, args.model, args.task)
    print("\n--- generated code ---")
    print(code)
    print("----------------------")

    token = args.token or mint_token(args.region, args.microvm_id)
    print(f"\n[2] Executing in microVM {args.microvm_id} ...")
    out = call_microvm(args.endpoint, token, "/exec", {"code": code})

    print("\n--- sandbox result ---")
    if out.get("stdout"):
        print("stdout:", out["stdout"].rstrip())
    print("RESULT:", out.get("result"))
    if out.get("error"):
        print("ERROR:\n", out["error"])
    print(f"(exec #{out.get('exec_count')}, {out.get('duration_ms')} ms, "
          f"vm {out.get('vm_instance_id')})")


if __name__ == "__main__":
    sys.exit(main())
