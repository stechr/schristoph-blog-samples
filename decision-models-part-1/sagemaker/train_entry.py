"""SageMaker AI training-job entry point for train_unsloth.py.

SageMaker starts this from /opt/ml/code on a PyTorch 2.8 GPU Deep Learning
Container. It installs Unsloth on top of the container's PyTorch, then runs the
training script. The model goes to /opt/ml/model (SageMaker uploads it to S3 as
model.tar.gz); metrics and predictions go to /opt/ml/output/data
(output.tar.gz).
"""
import subprocess
import sys
import time

PACKAGES = [
    "unsloth==2026.10.4",
    "unsloth_zoo==2026.10.4",
    "transformers==5.2.0",
    "trl==0.22.2",
    "tokenizers>=0.22.0,<=0.23.0",
    "bitsandbytes",
    "datasets",
]


def run(cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


t0 = time.time()
run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv"])
run([sys.executable, "-m", "pip", "install", "--quiet", *PACKAGES])
run([sys.executable, "-c", "import torch, unsloth, transformers; "
     "print('torch', torch.__version__, 'bf16', torch.cuda.is_bf16_supported()); "
     "print('unsloth', unsloth.__version__, 'transformers', transformers.__version__)"])
print(f"setup took {time.time() - t0:.0f}s", flush=True)

t1 = time.time()
run([sys.executable, "/opt/ml/code/train_unsloth.py", "--dataset", "typed-decisions",
     "--max-steps", "60", "--out-dir", "/opt/ml/output/data", "--model-dir", "/opt/ml/model", "--gguf"])
print(f"training script took {time.time() - t1:.0f}s", flush=True)
