# demo-video-pipeline — common entrypoints.
# `make demo` is the zero-AWS-deploy path (Amazon Polly). The qwen-* targets need a
# deployed Amazon SageMaker endpoint (see `make deploy`).
#
# Run `make setup` FIRST — it creates ./.venv and installs the deps + Chromium.
# Every target except `setup` runs through ./.venv/bin/python automatically, so you do
# NOT need to activate the venv. Manage your own environment instead? Override on the
# command line, e.g. `make demo PY=python3` (deps must already be importable).

# Bootstrap interpreter used ONLY to build the venv in `make setup`.
BOOTSTRAP_PY ?= python3
# Interpreter used by every other target — the venv created by `make setup`.
PY ?= .venv/bin/python
SCRIPT ?= sample-content/narration.json

# Load .env (if present) and export it to recipe commands, so POLLY_VOICE, AWS_REGION,
# TTS_BACKEND, etc. take effect. .env is gitignored — copy it from .env.example.
ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: help setup demo demo-qwen demo-clone script-from-app script-from-spec \
        record-ref transcribe-ref deploy status autoscale validate teardown

help:
	@grep -E '^[a-zA-Z_-]+:.*?#' $(MAKEFILE_LIST) | sed 's/:.*#/\t/' | sort

setup:           # create venv + install client deps + chromium (run this FIRST)
	$(BOOTSTRAP_PY) -m venv .venv && . .venv/bin/activate && \
	  pip install -U -r requirements.txt && python -m playwright install chromium

demo:            # DEFAULT: render the sample demo with Amazon Polly (no AWS deployment)
	$(PY) pipeline/render.py --backend polly --script $(SCRIPT) --out media/demo.mp4

demo-qwen:       # render with a Qwen3-TTS named speaker (needs the SageMaker endpoint)
	$(PY) pipeline/render.py --backend qwen-speaker --script $(SCRIPT) --out media/demo-qwen.mp4

demo-clone:      # render with a Qwen3-TTS voice clone (provide your OWN ref clip + transcript)
	@test -n "$(REF_AUDIO)" || (echo "Set REF_AUDIO=path/to/ref.wav REF_TEXT='exact transcript'"; exit 1)
	$(PY) pipeline/render.py --backend qwen-clone --script $(SCRIPT) \
	  --ref-audio "$(REF_AUDIO)" --ref-text "$(REF_TEXT)" --out media/demo-clone.mp4

record-ref:      # record a ~10-30s mic reference clip for voice cloning (→ ref_audio.wav)
	bash scripts/record_reference.sh $(SECONDS) $(REF_AUDIO)

transcribe-ref:  # transcribe ref_audio.wav to its exact words via Amazon Transcribe (→ ref_text.txt)
	$(PY) scripts/transcribe_reference.py --audio $(or $(REF_AUDIO),ref_audio.wav) --out $(or $(REF_TEXT_OUT),ref_text.txt)

script-from-app: # propose a narration script from the sample app's source
	$(PY) scripts/generate_script.py --app sample-app --out /tmp/draft.json --prompt-out /tmp/prompt.txt

script-from-spec:# propose a narration script from a product spec (SPEC=path.md)
	$(PY) scripts/generate_script.py --spec $(SPEC) --out /tmp/draft.json

deploy:          # create the Qwen3-TTS SageMaker async endpoint (non-blocking; poll `make status`)
	$(PY) sagemaker/deploy.py precheck && $(PY) sagemaker/deploy.py create

status:          # endpoint status
	$(PY) sagemaker/deploy.py status

autoscale:       # register min=0 scale-to-zero (run AFTER InService)
	$(PY) sagemaker/deploy.py autoscale

validate:        # smoke-test the standard Qwen speaker against the endpoint
	$(PY) sagemaker/invoke_async.py --mode custom_voice \
	  --text "Hello from the demo video pipeline." --speaker Aiden --out /tmp/validate.wav

teardown:        # USER-INITIATED: delete endpoint/config/model when COMPLETELY done (keeps S3 + role). Not automatic — the scale-to-zero endpoint is ~$0 idle, so reuse it between renders.
	bash sagemaker/teardown.sh
