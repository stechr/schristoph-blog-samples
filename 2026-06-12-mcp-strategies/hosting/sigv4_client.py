"""sigv4_client.py — A minimal MCP client that SigV4-signs its requests.

Because the remote server's Function URL uses AuthType=AWS_IAM, the client must
sign every request with SigV4 (service name "lambda") using credentials from an
IAM principal in the same account. This client:

  1. initialize
  2. tools/list
  3. tools/call demo_account_context   (proves the call stayed in-account)

Run (against the deployed Function URL):
    uv run --with botocore --with boto3 python sigv4_client.py <FUNCTION_URL>

It uses the ambient AWS credentials (AWS_PROFILE / env vars), so set those to a
principal in the deploying account first.
"""
from __future__ import annotations

import json
import sys
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

SERVICE = "lambda"  # Function URLs are signed as the lambda service


def signed_post(url: str, region: str, body: dict) -> dict:
    session = boto3.Session()
    creds = session.get_credentials()
    if creds is None:
        raise SystemExit("No AWS credentials found. Set AWS_PROFILE or env vars.")

    payload = json.dumps(body)
    aws_req = AWSRequest(method="POST", url=url, data=payload,
                         headers={"Content-Type": "application/json"})
    SigV4Auth(creds.get_frozen_credentials(), SERVICE, region).add_auth(aws_req)

    http_req = urllib.request.Request(
        url, data=payload.encode("utf-8"),
        headers=dict(aws_req.headers), method="POST")
    with urllib.request.urlopen(http_req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _region_from_url(url: str) -> str:
    # Function URL host: <id>.lambda-url.<region>.on.aws
    host = url.split("//", 1)[-1].split("/", 1)[0]
    parts = host.split(".")
    return parts[2] if len(parts) > 3 and parts[1] == "lambda-url" else "us-east-1"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: sigv4_client.py <FUNCTION_URL>")
    url = sys.argv[1].rstrip("/") + "/"
    region = _region_from_url(url)
    print(f"Target : {url}")
    print(f"Region : {region}  (SigV4 service '{SERVICE}')\n")

    init = signed_post(url, region, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05",
                   "clientInfo": {"name": "sigv4-demo-client", "version": "1.0"},
                   "capabilities": {}}})
    print("initialize ->", json.dumps(init["result"]["serverInfo"]))

    listed = signed_post(url, region, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in listed["result"]["tools"]]
    print("tools/list ->", names)

    called = signed_post(url, region, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "demo_account_context", "arguments": {}}})
    text = called["result"]["content"][0]["text"]
    print("tools/call demo_account_context ->", text)
    print("\nOK: a SigV4-signed, in-account client reached the remote MCP "
          "server, listed its tools, and invoked one.")


if __name__ == "__main__":
    main()
