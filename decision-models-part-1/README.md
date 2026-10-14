# Decision models, part 1: training data, training run, evaluation

Companion code for the blog post *Most Agent Reasoning Is Classification in Disguise*
(part 1 of 2). It turns one agent step into a decision with probabilities over options
you declare, fine-tunes a small model for it with Unsloth, and checks the result with
metrics that look at the probabilities as well as the top answer.

Part 2 serves the trained model with llama.cpp on Amazon SageMaker AI.

## What is in here

| File | Runs on | What it does |
|---|---|---|
| `make_routing_data.py` | CPU | Generates a synthetic "which skill handles this request?" dataset in the typed-decisions format. Template-built, no real requests. |
| `baselines.py` | CPU | Writes `prior` and `uniform` baseline predictions for a split, so you can check the evaluator before trusting it. |
| `evaluate.py` | CPU | Accuracy, Brier, KL from gold, ECE, and an escalation sweep (answer locally above a confidence threshold, escalate the rest). |
| `train_unsloth.py` | NVIDIA GPU | LoRA fine-tune with Unsloth's `FastDecisionModel`, calibration on a held-out split, test evaluation, predictions JSONL, saved adapter and merged model. |

## What has been run

- `make_routing_data.py`, `baselines.py` and `evaluate.py` were run on CPU against the
  public [typed-decisions](https://huggingface.co/datasets/LocalLLaMA/typed-decisions)
  dataset (revision `c806f6c`). On the test split (400 cases, 2,000 decisions) the
  uniform baseline reproduces the dataset card's Brier (0.238) and KL (0.444). The
  prior baseline lands within 0.02 of the card on every column except ECE, whose
  definition differs between reports.
- `train_unsloth.py` was run end to end on one NVIDIA A10G (EC2 `g5.xlarge`, bfloat16)
  with Unsloth 2026.10.4, PyTorch 2.8.0, transformers 5.2.0 and trl 0.22.2, using
  `ec2/user-data.sh` as the bootstrap. 60 steps took 17.6 minutes. Held-out accuracy went
  from 0.305 to 0.800, calibration error from 0.182 to 0.032 after `calibrate`; on the test
  split `evaluate.py` reported accuracy 0.787, Brier 0.125, KL from gold 0.497, ECE 0.030.
  The GGUF export step was skipped by the script: it needs llama.cpp build b11443 or newer.
- Setup notes from that run: use a clean virtual environment; skip `unsloth install-kernels`;
  pin `torchao==0.13.0` with PyTorch 2.8 (an unpinned `torchao>=0.16.0` resolves to a release
  that needs a newer PyTorch and breaks the transformers import).

| File | Runs on | What it does |
|---|---|---|
| `ec2/user-data.sh` | EC2 GPU instance | One-shot bootstrap: clean venv, pinned packages, import check, training, upload to S3, self-terminate (hard stop after 150 min). Set the bucket name first. |
| `sagemaker/` | SageMaker AI training job | Alternative entry point and launch script for a training job; not used for the published numbers. |

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 1. Get the public benchmark (or use your own data in the same format)
REV=c806f6c69d734f29436f25536138547031a673d6
for s in train test; do
  curl -sL -o td_$s.parquet \
    "https://huggingface.co/datasets/LocalLLaMA/typed-decisions/resolve/$REV/all/$s-00000-of-00001.parquet"
done

# 2. Check the evaluator against the card's reference rows
python baselines.py --train td_train.parquet --test td_test.parquet --kind uniform --out uniform.jsonl
python evaluate.py --cases td_test.parquet --predictions uniform.jsonl

# 3. Optional: synthetic routing data for your own agent step
python make_routing_data.py --train 400 --test 100 --out-prefix routing

# 4. On a GPU machine: train, calibrate, predict
python train_unsloth.py --dataset typed-decisions --out-dir run-td
python evaluate.py --cases td_test.parquet --predictions run-td/predictions.jsonl
```

## Metric definitions

Every (case, question) pair is one decision. For each decision with options `o`,
predicted probabilities `p` and gold distribution `g`:

- **accuracy**: the top predicted option equals the gold label. Ties share the credit
  (a uniform guess over `k` options scores `1/k`).
- **Brier**: `sum_o (p_o - g_o)^2`, against the soft gold distribution.
- **KL from gold**: `sum_o g_o * log(g_o / p_o)`.
- **ECE**: 10 equal-width bins over the top-label probability, weighted gap between
  mean confidence and accuracy per bin. Other reports compute ECE differently; compare
  Brier and KL across reports, not ECE.
- **escalation sweep**: for each threshold `t`, the share of decisions whose top
  probability is at least `t` (answered locally), their accuracy, and the share
  escalated.

A uniform guess gets ECE 0.000 under this definition. Its confidence always equals its
expected accuracy, which makes it calibrated and useless. Read ECE next to Brier or KL.

## Data format

One JSON object per line (or the dataset's parquet columns):

```json
{"id": "routing-test-0000",
 "state": "{\"request\": \"Move my Monday sync to Friday.\"}",
 "questions": "{\"skill\": {\"type\": \"choice\", \"instructions\": \"...\", \"criteria\": {\"calendar\": \"...\"}}}",
 "gold": "{\"skill\": {\"type\": \"choice\", \"label\": \"calendar\", \"probabilities\": {\"calendar\": 0.9}}}"}
```

Question types are `choice` (one of N options), `noul` (yes/no, options `false`/`true`)
and `score` (ordered levels `0..k-1`).

## Licenses

- This folder: MIT-0.
- typed-decisions dataset: Apache-2.0 (per its dataset card).
- Unsloth notebooks: LGPL-3.0; the Unsloth decision-model source files carry their own
  license headers. Check both before you ship anything built on them.
