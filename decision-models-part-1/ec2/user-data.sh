#!/bin/bash
# EC2 user data: train the decision model once on a GPU instance, upload results to S3, terminate.
# Launch with --instance-initiated-shutdown-behavior terminate and an instance profile that can
# read/write the bucket. Set BUCKET and PREFIX before use.
BUCKET="__BUCKET__"
PREFIX="decision-models/ec2-run"
BUCKET_REGION="eu-central-1"
LOG=/var/log/decision-train.log
exec > >(tee -a "$LOG") 2>&1
shutdown -h +150                       # hard stop, whatever happens below
sync_log() { aws s3 cp --region "$BUCKET_REGION" "$LOG" "s3://$BUCKET/$PREFIX/train.log" --only-show-errors || true; }
( while true; do sleep 120; sync_log; done ) &
set -x
cd /opt && mkdir -p dm && cd dm
aws s3 cp --region "$BUCKET_REGION" "s3://$BUCKET/$PREFIX/code/source.tar.gz" . && tar -xzf source.tar.gz
# A clean virtual environment with the package set from Unsloth's decision notebook.
# (The AMI's own PyTorch environment carries extra packages that break the import.)
export HOME=/root
fail() { echo "SETUP_FAILED: $1"; sync_log; shutdown -h now; exit 1; }
/opt/pytorch/bin/pip install --quiet uv || fail "uv"
export PATH="/opt/pytorch/bin:$PATH"
uv venv /opt/dm/venv --python 3.12 || fail "venv"
source /opt/dm/venv/bin/activate
nvidia-smi --query-gpu=name,memory.total --format=csv
INSTALL_START=$(date +%s)
uv pip install "torch==2.8.0" "triton>=3.3.0" torchvision "torchaudio==2.8.0" bitsandbytes \
  "xformers==0.0.32.post2" "unsloth_zoo[base]==2026.10.4" "unsloth[base]==2026.10.4" datasets \
  "transformers==5.2.0" "trl==0.22.2" "tokenizers>=0.22.0,<=0.23.0" einops || fail "packages"
# Note: `unsloth install-kernels` is skipped on purpose; the optional kernels it adds
# (mamba_ssm) need einops and broke the import in an earlier run.
# Unsloth's notebook upgrades torchao here ("torchao>=0.16.0"). Today that resolves to a torchao
# built for a newer PyTorch than 2.8, and transformers then fails to import. Pin the torchao line
# made for PyTorch 2.8, and if the training imports still fail, run without torchao.
uv pip install --no-deps "torchao==0.13.0"
check() { python -c "from transformers import TrainingArguments; from unsloth import FastDecisionModel, DecisionTrainer; print('training imports OK')"; }
check || { uv pip uninstall torchao; check; } || fail "training imports"
echo "INSTALL_SECONDS=$(( $(date +%s) - INSTALL_START ))"
python -c "import torch, unsloth, transformers; print('torch', torch.__version__, 'bf16', torch.cuda.is_bf16_supported(), 'unsloth', unsloth.__version__, 'transformers', transformers.__version__)" || fail "import"
START=$(date +%s)
python train_unsloth.py --dataset typed-decisions --max-steps 60 --out-dir out --model-dir model --gguf
RC=$?
echo "TRAIN_RC=$RC SECONDS=$(( $(date +%s) - START ))"
aws s3 cp --region "$BUCKET_REGION" out "s3://$BUCKET/$PREFIX/output/" --recursive --only-show-errors
aws s3 cp --region "$BUCKET_REGION" model "s3://$BUCKET/$PREFIX/model/" --recursive --only-show-errors
echo "=== DONE"
sync_log
shutdown -h now
