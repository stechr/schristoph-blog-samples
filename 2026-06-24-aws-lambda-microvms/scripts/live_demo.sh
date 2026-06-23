#!/usr/bin/env bash
#
# live_demo.sh — AWS Lambda MicroVMs: "An AI sandbox you can watch think"
#
# Three moves, all live:
#   1) SPEED      launch a microVM; the app is already running (snapshot resume)
#   2) STATE      Bedrock writes code -> sandbox runs it -> suspend -> resume,
#                 state survives ("the pause never happened")
#   3) ISOLATION  a second microVM from the same image cannot see the first's state
#
# Prereqs (one-time): a Python venv whose botocore includes the lambda-microvms
# service model, and AWS credentials for an account where the image is provisioned.
#   uv venv .venv && . .venv/bin/activate && uv pip install -U awscli botocore boto3
#   export AWS_PROFILE=<your-profile>
#
# Set ACC to your 12-digit AWS account ID and IMAGE_ARN to your provisioned image.
# The image is pre-baked (slow step done offstage). This script only does the FAST,
# live-on-stage calls.
set -uo pipefail

REG=eu-west-1
ACC=123456789012
IMAGE_ARN="arn:aws:lambda:$REG:$ACC:microvm-image:code-sandbox"
EXEC_ROLE="arn:aws:iam::$ACC:role/<exec-role>"
DEMO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

pause() { echo; read -rp $'\033[2m(press enter)\033[0m' _; echo; }
say()   { echo; echo -e "\033[1;36m# $*\033[0m"; }

token_for() {  # $1 = microvmId
  aws lambda-microvms create-microvm-auth-token --microvm-identifier "$1" \
    --expiration-in-minutes 30 --allowed-ports '[{"port":8080}]' \
    --query 'authToken."X-aws-proxy-auth"' --output text --region $REG
}
wait_ready() {  # $1 = endpoint, $2 = token
  for _ in $(seq 1 15); do
    c=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "https://$1/healthz" \
        -H "X-aws-proxy-auth: $2" -H "X-aws-proxy-port: 8080" || echo 000)
    [ "$c" = "200" ] && return 0; sleep 3
  done; return 1
}

# ---------------------------------------------------------------------------
say "MOVE 1 — SPEED: launch an isolated microVM (one API call)"
RUN=$(aws lambda-microvms run-microvm --image-identifier "$IMAGE_ARN" --image-version 1.0 \
  --execution-role-arn "$EXEC_ROLE" \
  --idle-policy '{"maxIdleDurationSeconds":900,"suspendedDurationSeconds":600,"autoResumeEnabled":true}' \
  --region $REG)
MV1=$(echo "$RUN"  | python -c "import sys,json;print(json.load(sys.stdin)['microvmId'])")
EP1=$(echo "$RUN"  | python -c "import sys,json;print(json.load(sys.stdin)['endpoint'])")
echo "  microvmId: $MV1"; echo "  endpoint:  $EP1"
T1=$(token_for "$MV1")
wait_ready "$EP1" "$T1" && echo "  -> serving on first request: the app was ALREADY running (resumed from snapshot)"
curl -s "https://$EP1/" -H "X-aws-proxy-auth: $T1" -H "X-aws-proxy-port: 8080"; echo
pause

say "MOVE 2 — STATE: Bedrock writes Python, the sandbox runs it"
( cd "$DEMO_DIR" && python demo.py --microvm-id "$MV1" --endpoint "$EP1" \
    --task "Find all prime numbers below 50 and return them as a list." )
pause

say "    ... now build session state (a variable + a file on disk)"
curl -s "https://$EP1/exec" -H "X-aws-proxy-auth: $T1" -H "X-aws-proxy-port: 8080" \
  -H "Content-Type: application/json" \
  -d '{"code":"session_secret = 42\nimport pathlib; pathlib.Path(\"/workspace/notes.txt\").write_text(\"cached model + data\")\nRESULT=\"state set\""}' >/dev/null
echo "  state BEFORE suspend:"
curl -s "https://$EP1/state" -H "X-aws-proxy-auth: $T1" -H "X-aws-proxy-port: 8080" \
  | python -c "import sys,json;d=json.load(sys.stdin);print('   vars=',list(d['session_vars']),'files=',d['workspace_files'])"
pause

say "    suspend the microVM (memory + disk snapshotted, idle cost)"
aws lambda-microvms suspend-microvm --microvm-identifier "$MV1" --region $REG \
  --query 'state' --output text
say "    ... time passes. now send a request — it resumes transparently."
wait_ready "$EP1" "$T1"
echo "  state AFTER resume:"
curl -s "https://$EP1/state" -H "X-aws-proxy-auth: $T1" -H "X-aws-proxy-port: 8080" \
  | python -c "import sys,json;d=json.load(sys.stdin);print('   vars=',list(d['session_vars']),'files=',d['workspace_files'],' -> the pause never happened')"
pause

say "MOVE 3 — ISOLATION: a second microVM from the SAME image"
RUN2=$(aws lambda-microvms run-microvm --image-identifier "$IMAGE_ARN" --image-version 1.0 \
  --execution-role-arn "$EXEC_ROLE" \
  --idle-policy '{"maxIdleDurationSeconds":900,"suspendedDurationSeconds":600,"autoResumeEnabled":true}' \
  --region $REG)
MV2=$(echo "$RUN2" | python -c "import sys,json;print(json.load(sys.stdin)['microvmId'])")
EP2=$(echo "$RUN2" | python -c "import sys,json;print(json.load(sys.stdin)['endpoint'])")
T2=$(token_for "$MV2")
wait_ready "$EP2" "$T2"
echo "  VM2 state (note: empty vars, no notes.txt, DIFFERENT identity):"
curl -s "https://$EP2/state" -H "X-aws-proxy-auth: $T2" -H "X-aws-proxy-port: 8080" \
  | python -c "import sys,json;d=json.load(sys.stdin);print('   vars=',list(d['session_vars']),'files=',d['workspace_files'],'vm=',d['vm_instance_id'][:12])"
echo "  VM1 identity for comparison:"
curl -s "https://$EP1/state" -H "X-aws-proxy-auth: $T1" -H "X-aws-proxy-port: 8080" \
  | python -c "import sys,json;d=json.load(sys.stdin);print('   vm=',d['vm_instance_id'][:12],'  <- different microVM, no shared kernel, no shared state')"
pause

say "CLEANUP — terminate both microVMs (image stays, relaunch in ~1s anytime)"
for m in "$MV1" "$MV2"; do
  aws lambda-microvms terminate-microvm --microvm-identifier "$m" --region $REG --query 'state' --output text
done
echo; echo "Done."
