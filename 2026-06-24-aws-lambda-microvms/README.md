# An AI sandbox you can watch think — AWS Lambda MicroVMs demo

A minimal demo of **AWS Lambda MicroVMs**: an AI-generated-code sandbox where **Amazon Bedrock
writes Python and a per-session Firecracker microVM runs it**, in isolation, with state that
survives suspend/resume.

It shows three things together in one compute primitive:

| Move | Shows | How |
|------|-------|-----|
| **1. Speed** | near-instant launch | `RunMicrovm` returns an endpoint; the app is *already running* (resumed from a snapshot), so it serves on the first request |
| **2. State** | stateful suspend/resume | Bedrock-generated code runs, sets a variable + writes a file, the VM is **suspended**, then **resumes** with everything intact |
| **3. Isolation** | VM-level isolation | a second microVM from the same image cannot see the first's variables or files, and has a different identity |

> **All sample data in this folder is synthetic** — placeholder account IDs, bucket names, roles,
> and identities. Replace the placeholders with your own resources before running.

## What it demonstrates

```
  you / a talk          Amazon Bedrock                 AWS Lambda MicroVM (Firecracker)
  ───────────           ──────────────                 ───────────────────────────────
  demo.py  ──"write code for X"──▶ Claude (eu.* profile)
       │  ◀──────── Python ────────┘
       │
       └── POST /exec (X-aws-proxy-auth) ─────────────▶ Flask app on :8080
                                                         exec() in a persistent namespace
                                                         /workspace on disk
                                                         lifecycle hooks on :9000
```

- **Image (pre-baked):** `Dockerfile` + `app.py` zipped to S3 → `CreateMicrovmImage` runs the
  Dockerfile, boots the app, calls `/ready`, snapshots memory + disk, calls `/validate`.
- **Per session:** `RunMicrovm` launches from the snapshot (app already running) → dedicated
  HTTPS endpoint → mint a short-lived auth token → send traffic with `X-aws-proxy-auth`.
- **Lifecycle:** `SuspendMicrovm` / `ResumeMicrovm` / `TerminateMicrovm`, or the `idlePolicy`.

## Files

- `app/app.py` — the sandbox: `/exec` (run code in a persistent namespace), `/state`, and the
  lifecycle hooks `/ready` `/validate` `/run` `/resume` `/suspend` `/terminate` on port 9000.
- `app/Dockerfile` — `FROM public.ecr.aws/lambda/microvms:al2023-minimal`, single-process dual server.
- `app/requirements.txt` — Flask.
- `demo.py` — Bedrock → code → `/exec` driver.
- `scripts/live_demo.sh` — narrated, projector-friendly runbook for a live walkthrough.

## Prerequisites

- An AWS account with access to AWS Lambda MicroVMs and Amazon Bedrock (this demo uses the
  `eu-west-1` region and an EU Claude inference profile).
- A pre-baked microVM image built from `app/` (see "What it demonstrates" above), plus a build
  role and an execution role.
- **A Python venv whose botocore includes the lambda-microvms service model** (the CLI/SDK
  surface is newer than older system installs):

  ```bash
  uv venv .venv && . .venv/bin/activate
  uv pip install -U awscli botocore boto3
  export AWS_PROFILE=<your-profile>
  ```

Set these placeholders to your own values before running:

| Placeholder | Where | Example real value (yours) |
|---|---|---|
| `123456789012` | `scripts/live_demo.sh` (`ACC`), ARNs | your 12-digit account ID |
| `arn:aws:iam::123456789012:role/<exec-role>` | exec role ARN | your microVM execution role |
| `<your-bucket>` | image-build source bucket | your S3 bucket |
| `<your-profile>` | `AWS_PROFILE` | your named AWS profile |
| `microvm-image:code-sandbox` | image ARN | your provisioned image identifier |

## Run the walkthrough

```bash
. .venv/bin/activate && export AWS_PROFILE=<your-profile>
bash scripts/live_demo.sh        # pauses between moves; terminates both VMs at the end
```

You can also drive a single execution directly:

```bash
python demo.py --microvm-id <microvm-id> --endpoint <endpoint> \
  --task "Find all prime numbers below 50 and return them as a list."
```

## Expected output (representative)

```
MOVE 1 — SPEED
  GET / -> {"message":"Isolated Firecracker sandbox, ready for code.",
            "vm_instance_id":"<hex>","uptime_seconds":99.2}   # served first try

MOVE 2 — STATE (Bedrock writes the code)
  task: "Find all prime numbers below 50 and return them as a list."
  generated: def is_prime(n): ... ; RESULT = [n for n in range(2,50) if is_prime(n)]
  RESULT: [2,3,5,7,11,13,17,19,23,29,31,37,41,43,47]   (0.2 ms)
  state BEFORE suspend: vars=[RESULT, is_prime, session_secret]  files=[notes.txt]
  suspend -> SUSPENDED
  state AFTER  resume: vars=[RESULT, is_prime, session_secret]  files=[notes.txt]  # intact

MOVE 3 — ISOLATION
  VM2 state: vars=[]  files=[]  vm=<hex-b>   # empty, different identity
  VM1 state: vm=<hex-a>                      # different microVM, no shared kernel/state
```

## Two gotchas worth knowing (both real, both fixed in this code)

1. **Trust-policy ARN format.** The IAM reference shows `aws:SourceArn` as
   `…:microvm-image/*` (slash), but the real image ARN is `…:microvm-image:code-sandbox`
   (colon). The slash pattern never matches → `unable to assume the role`. Use
   `…:microvm-image*`.
2. **Snapshot Python is 3.9.** `dnf install python3` on the AL2023 base gives Python 3.9, so
   `str | None` annotations crash the app at import → the `/ready` hook times out → build fails.
   Fix: `from __future__ import annotations` (already in `app.py`), or pin Python 3.11+.

Plus the **snapshot-uniqueness** point: an identity generated at import time is *shared* by every
microVM cloned from the snapshot. `app.py` reseeds it in the `/run` runtime hook so each microVM
is distinct — that's why VM1 and VM2 report different `vm_instance_id`s.

## Cost / teardown

- The **image version** incurs storage cost while it exists; **running microVMs** bill baseline
  compute (idle = suspended = low). The walkthrough script terminates both VMs at the end.
- To fully tear down afterwards:

  ```bash
  aws lambda-microvms list-microvms --region eu-west-1   # terminate any stragglers
  aws lambda-microvms delete-microvm-image --image-identifier \
    arn:aws:lambda:eu-west-1:123456789012:microvm-image:code-sandbox --region eu-west-1
  # then delete the IAM roles + S3 bucket if you are done for good
  ```

## License

MIT — see the repository [LICENSE](../LICENSE).
