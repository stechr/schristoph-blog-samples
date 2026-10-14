#!/usr/bin/env bash
# Run the golden set against real releases on Amazon Bedrock (eu-central-1).
# Needs boto3 and AWS credentials with bedrock:InvokeModel. Starts from an empty history.
#   1. Nova Lite with the c1 tool contract (the first run in the blog post)
#   2. Nova Lite with the c2 contract, accepted as the baseline if it passes
#   3. candidate: Nova 2 Lite (model upgrade)
#   4. candidate: Nova Micro (cheaper model)
set -u
cd "$(dirname "$0")"
H=runs/bedrock-history.jsonl
rm -f "$H"
for args in "bedrock-nova-lite-c1" "bedrock-nova-lite --accept" "bedrock-nova-2-lite" "bedrock-nova-micro"; do
  # shellcheck disable=SC2086
  python3 -W ignore gate.py --history "$H" --agent $args; echo "exit=$?"; echo
done
