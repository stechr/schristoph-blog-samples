---
name: demo-video
description: Generate a narrated demo video of a web app — write/confirm a narration script, synthesize a voiceover (Amazon Polly or Qwen3-TTS on Amazon SageMaker), record the UI, and stitch them into a synced MP4. Use when the user says "generate a demo video", "record a demo", "narrated walkthrough", "demo of the sample app", or "make a demo video of my app".
---

# Demo Video Skill

Generate a narrated demo video by orchestrating this repo's deterministic Python +
Makefile pipeline: synthesize audio, record the app, and stitch everything into a synced
MP4. You (the agent) drive the workflow conversationally and shell out to the repo's own
scripts — you do **not** reimplement the pipeline.

## When to Use

- "Generate a narrated demo video of the sample app"
- "Record a demo / walkthrough video with voiceover"
- "Make a demo video of my own app"
- "Re-voice this existing screen capture"
- "Narrate the demo in my own voice" (voice-clone backend)

## Prerequisites

- Run from the repo root. The pipeline lives in `pipeline/`, `scripts/`, and `sagemaker/`,
  driven by the `Makefile`.
- `ffmpeg` (with `ffprobe`) on PATH.
- AWS credentials on the standard chain. Amazon Polly needs `polly:SynthesizeSpeech`; the
  Amazon SageMaker backends need SageMaker + Amazon S3 permissions.
- The first run builds an isolated `./.venv` via `make setup` (installs deps + the Chromium
  recorder). Every other `make` target runs through `./.venv/bin/python` automatically.

## Defaults (pick these unless the user says otherwise)

- Backend: **Amazon Polly** (no deployment, lowest barrier).
- Voice: **Matthew**, neural engine.
- Script: the shipped sample at `sample-content/narration.json`.
- Output: `media/demo.mp4`.

## Core Workflow — generate the sample demo (Amazon Polly)

This is the happy path: an end-to-end result with no user input.

1. **Set up the environment (once).** If `./.venv` does not exist, run:
   ```bash
   make setup
   ```
   This creates `./.venv`, installs `requirements.txt`, and runs
   `playwright install chromium`.

2. **Render.** Run the default target:
   ```bash
   make demo
   # = .venv/bin/python pipeline/render.py --backend polly \
   #       --script sample-content/narration.json --out media/demo.mp4
   ```
   The renderer synthesizes each narration segment with Amazon Polly, records the sample
   app holding each scene for exactly its measured audio length, and lays the audio
   back-to-back. Synthesis is idempotent — a valid existing `.wav` in the audio dir is
   reused, so re-runs don't re-synthesize.

3. **Report.** The output is `media/demo.mp4`. Tell the user the path and the total
   duration printed by the renderer (`lead-in + narration + tail`).

To change the voice, set `POLLY_VOICE` in `.env` (`Joanna`, `Stephen`, `Ruth`, …) or pass
it through the environment, then re-run `make demo`.

> [!important] Audio-length drives the timing
> The pipeline measures each segment's real audio length with `ffprobe` and holds the
> matching on-screen scene for exactly that long, so video and audio stay aligned without
> hand-tuned pauses. Do not hardcode pause durations.

## Script a demo of the user's OWN app or product

The generator proposes a narration script from a web app's source **or** a product spec,
plus a ready-to-paste LLM prompt.

```bash
# From an app dir whose index.html uses data-testid hooks (the sample app qualifies):
make script-from-app                 # → /tmp/draft.json + /tmp/prompt.txt
# From a product spec markdown file:
make script-from-spec SPEC=my-product.md
# Optionally let Amazon Bedrock write the polished script from the generated prompt:
python scripts/generate_script.py --app sample-app --bedrock --out /tmp/script.json
```

Workflow:
1. Run the appropriate generator above (`make script-from-app` is a no-AWS smoke that just
   inspects source — safe to run anytime).
2. Review and tighten the wording with the user. Keep segments short; one idea per segment.
3. Render the reviewed script:
   ```bash
   python pipeline/render.py --backend polly --script /tmp/script.json --out media/mine.mp4
   ```

For the recorder to drive a custom app, its interactive elements need `data-testid`
attributes; the script's `steps` reference them (`type`, `click`, `eval`, `wait`/`pause`).
See `docs/speaker-notes.md` and `sample-app/index.html` for the convention.

## Backend 2 — Qwen3-TTS named speaker (Amazon SageMaker)

An open-weights voice you control, served from an asynchronous, scale-to-zero Amazon
SageMaker endpoint. Only use this if the user explicitly wants a non-Polly voice and is
willing to deploy an endpoint.

> [!warning] Deploy-time cost + wait — warn the user BEFORE deploying
> The **first** endpoint build takes **~15–25 min** (cold start; both 1.7B models load) and
> runs on a GPU instance (`ml.g5.xlarge` ≈ **$1.41/hr** while processing, billed per-second).
> Tell the user this before running `make deploy`. After it is `InService`, the endpoint is
> **scale-to-zero**, so it costs **≈ $0 while idle** and you reuse it for every later render.

```bash
make deploy       # FIRST TIME ONLY: quota precheck → role/bucket → Model + async EndpointConfig + Endpoint (~15–25 min, GPU)
make status       # poll until InService
make autoscale    # register min=0 (scale to zero → $0 compute when idle)
make validate     # smoke-test the speaker
make demo-qwen    # render with the named speaker (default "Aiden")
```

> [!important] Deploy ONCE, then REUSE — do NOT tear down between renders
> The endpoint is **scale-to-zero (~$0 while idle)**. Deploy it **once** and **reuse it
> across every render**. For a second/third render (or a later session), check `make status`:
> if the endpoint already exists, **reuse it** — and if it idled to zero instances, just
> **wake it (0→1)** (see the scale-from-zero gotcha below) rather than redeploying. The agent
> MUST NOT run `make teardown` automatically. Tearing the endpoint down is a **user-initiated**
> action, done only when the user is completely finished with voice work (see "Tearing down
> the endpoint" below).

> [!important] Scale-from-zero gotcha
> `make autoscale` registers a target-tracking policy that scales 1→N but **not 0→1**.
> After the endpoint idles at zero instances, the first async invoke can sit in the backlog
> without waking an instance. Wake it deterministically by setting the desired count to 1
> once (`aws sagemaker update-endpoint-weights-and-capacities …
> DesiredInstanceCount=1`), or add a step-scaling policy on `HasBacklogWithoutCapacity`.

> [!important] Only wake the endpoint when synthesis must actually run
> Synthesis is idempotent. If all narration segments already exist as valid `.wav` files,
> reuse them — do not wake the endpoint just to reproduce identical audio. (This is about
> avoiding a needless 0→1 wake, NOT about deleting the endpoint — reusing wavs ≠ tearing
> down. The endpoint stays deployed and idle at $0 between renders.)

## Tearing down the endpoint (user-initiated only)

When the user says they are **completely finished** with voice work and want to stop any
SageMaker billing, delete the endpoint:

```bash
make teardown     # = bash sagemaker/teardown.sh — deletes endpoint + config + model
```

This deletes the endpoint, endpoint config, and model; it **leaves the Amazon S3 bucket and
IAM role intact**. Only do this on explicit user request — never automatically after a
render (the scale-to-zero endpoint is ~$0 idle and should be reused).

## Backend 3 — Qwen3-TTS voice clone (Amazon SageMaker)

Same endpoint, `voice_clone` mode: clone a voice from a short reference clip the user
supplies. **This repo ships no cloned audio** — the user provides their own clip. This
backend **reuses the already-deployed Backend-2 endpoint** — do NOT redeploy or tear down
around the clone. If no endpoint exists yet, deploy once (per Backend 2, warn about the
~15–25 min / GPU cost first); otherwise reuse / wake the existing one.

When the user says *"clone my voice and re-record the video in my voice"*, walk this flow:

1. **Record a reference clip.** Offer to capture ~10–30s of clear speech:
   ```bash
   bash scripts/record_reference.sh           # → ref_audio.wav (ffmpeg/avfoundation, or sox)
   ```
   Or accept a clip the user made in **QuickTime Player** (record audio → export to `.wav`)
   and point the next step at that file. The script prints both paths/instructions.
2. **Transcribe it to the EXACT words** with Amazon Transcribe (this is the transcript
   `voice_clone` needs — a wrong one makes generation run long and time out):
   ```bash
   .venv/bin/python scripts/transcribe_reference.py --audio ref_audio.wav --out ref_text.txt
   ```
3. **Confirm the transcript with the user** (read back `ref_text.txt`; fix any mis-hearing).
4. **Render**, reusing the deployed endpoint:
   ```bash
   make demo-clone REF_AUDIO=ref_audio.wav REF_TEXT="$(cat ref_text.txt)"
   ```

> [!important] In-context cloning needs the true transcript
> Pass the reference clip's *actual* words as `REF_TEXT`. A wrong or placeholder transcript
> makes generation run long and the async call time out. `scripts/transcribe_reference.py`
> produces the exact transcript for you.

The `voice_clone` path exposes no speed/instruct knob — the clone inherits the reference
clip's cadence. To pace a cloned narration, apply post-synthesis ffmpeg `atempo`
time-stretch (pitch-preserved) or inject inter-sentence pauses, then re-measure and let the
pipeline re-fit each scene.

## Re-voice an existing capture (variable-latency apps)

When you can't cheaply re-record (a deployed backend, a one-shot capture) or the app has
variable latency (live backends, network), keep the existing screen recording and re-time
each scene to its narration segment instead of recording fresh:

```bash
python pipeline/render.py --method retime --video media/capture.mp4 --marks marks.json \
    --backend polly --out media/revoiced.mp4
```

`marks.json` is a list of scene-boundary timestamps (one more than the number of
segments). Derive them from ffmpeg scene detection, on-screen timestamps, and frame
inspection. The re-time method freeze-pads a scene when its narration is longer than the
captured action, and trims the trailing hold when shorter — it never cuts mid-action. The
renderer prints a per-scene table and a sync check at the end; surface any sync warnings.

## Pipeline reference (what you shell out to)

| File | Role |
|------|------|
| `pipeline/render.py` | Orchestrator: synth → record\|retime → stitch. The main entrypoint. |
| `pipeline/script_model.py` | Loads/validates a narration script (`narration.json`). |
| `pipeline/tts.py` | TTS abstraction: `polly` \| `qwen-speaker` \| `qwen-clone`. |
| `pipeline/record.py` | Playwright recorder (fixed-pause: each scene = its audio length). |
| `pipeline/stitch.py` | Lays narration back-to-back over the recording. |
| `pipeline/retime.py` | Per-scene A/V re-time for re-voicing / variable-latency captures. |
| `scripts/generate_script.py` | Proposes a narration script from app source or a product spec. |
| `scripts/record_reference.sh` | Records a ~10–30s mic reference clip (`ref_audio.wav`) for voice cloning. |
| `scripts/transcribe_reference.py` | Transcribes the reference clip to its exact text (`ref_text.txt`) via Amazon Transcribe. |
| `sagemaker/deploy.py` | Deploys the Qwen3-TTS async Amazon SageMaker endpoint. |
| `sagemaker/invoke_async.py` | Invokes the endpoint and polls the Amazon S3 output. |
| `Makefile` | Common entrypoints — the engine this skill drives. |

## Troubleshooting

- **WebM doesn't mux into MP4 directly.** The pipeline re-encodes to h264 + aac; if you
  hand-stitch, use `-c:v libx264 -preset fast -crf 23`.
- **Audio too quiet after mixing.** Apply `loudnorm=I=-16:TP=-1.5:LRA=11`.
- **`make setup` interpreter.** `make setup` bootstraps the venv with `BOOTSTRAP_PY`
  (defaults to `python3`); every other target uses `./.venv/bin/python`. To use your own
  environment, override `PY=python3` (deps must already be importable).
- **`.env` not taking effect.** The Makefile `include`s and `export`s `.env`; copy it from
  `.env.example`. It is gitignored — never commit real values.
