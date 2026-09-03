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

The generator extracts the app's (or a product spec's) facts and emits a ready-to-paste
prompt. **You then write the polished `narration.json` with your own model** — this is how
the bundled `sample-content/narration.json` was authored, and it produces far better prose
than the stdlib heuristic skeleton.

```bash
# Extract facts + emit the prompt (no network, no AWS):
make script-from-app                 # → /tmp/draft.json (heuristic skeleton) + /tmp/prompt.txt
# From a product spec markdown file instead:
make script-from-spec SPEC=my-product.md
```

Workflow (agent-authored — the primary path):
1. Run `make script-from-app` (or `--spec`) to get `/tmp/prompt.txt` + the heuristic
   `/tmp/draft.json`. This step is a no-AWS smoke — safe to run anytime.
2. **Read `/tmp/prompt.txt` and write the narration yourself** (your own model), matching the
   schema in `sample-content/narration.json`. Keep segments short; one idea per segment. Use
   the heuristic draft only as a structural hint, not as the final wording.
3. Confirm the wording with the user, save to e.g. `/tmp/script.json`, then render:
   ```bash
   python pipeline/render.py --backend polly --script /tmp/script.json --out media/mine.mp4
   ```

> [!note] Non-agent fallback
> Outside an agent (CI/automation), `generate_script.py --bedrock --model <current-id>` can
> call an LLM directly. There is **no default model id** (ids change / reach end-of-life), so
> a current one must be passed explicitly; without it the generator falls back to the
> heuristic skeleton.

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

> [!important] Reference clip spec — 10–20s, peaking −6 to −12 dBFS
> Cloning is in-context learning over a 12.5 Hz audio codec, so a 10–20s clip becomes roughly
> a few hundred audio tokens of conditioning context. **This band is provisional and
> pipeline-specific, not vendor guidance** — the Qwen3-TTS model card advertises cloning from as
> little as 3 seconds and states no upper bound. In my own measurements on one speaker a 27s
> reference produced a faster, less faithful clone than a 12.6s one, though duration was not
> isolated as the cause.
>
> **Level matters as much as length, and too-quiet is the dangerous direction** because it passes
> every clipping check. A reference peaking near −19 dBFS needs ~18 dB of normalization, which
> lifts the quantization floor into audible range — the clone then reproduces *and clips* it,
> producing audible crackle throughout the render. Validate both bounds while the speaker is still
> at the microphone.

### Pacing a cloned narration

`voice_clone` exposes no speed or `instruct` knob. (`instruct` belongs to the CustomVoice model,
which cannot clone — cloning runs on Base, so a handler that accepts `instruct` here silently drops
it.) More importantly, **the reference is not a duration knob**: it influences rate only weakly.
Fitted across five references in one setup (n = 5 — indicative, not a model-wide law):

```
output_wpm ≈ 0.58 × reference_wpm + 110      (r = 0.84, attractor ≈ 260 wpm)
```

So a deliberately slow 78 wpm read still rendered at 151 wpm. **Re-recording a slower reference is
not an effective fix** — don't send the speaker back to the microphone expecting one.

**Start with arithmetic.** `words ÷ target_minutes` is the pace the script requires. If that already
exceeds the pace you want, no synthesis setting and no post-processing can rescue it — cut the
script.

Then, in order:

1. **Add commas to the synthesis text.** Commas are the only punctuation the model turns into real
   silence. Measured on identical words and reference:

   | text variant | length | pause time | gross rate |
   |---|---|---|---|
   | plain | 3.84s | 0.16s | 219 wpm |
   | **extra commas** | **4.80s (+25%)** | **0.82s** | **175 wpm** |
   | ellipses `...` | 3.44s | **0.00s** | 244 wpm |
   | split into short sentences | 3.68s | **0.00s** | 228 wpm |

   Ellipses and extra full stops are ignored entirely. Keep two copies of the narration: a clean one
   for human review, and a comma-enriched one for synthesis.
2. **Shorten the script.** Nothing in the audio pipeline competes with saying less.
3. **ffmpeg `atempo` time-stretch, last resort, capped near 10%.** Pitch-preserved but audible —
   `atempo=0.75` reads as an unnaturally sedated speaker.

> [!warning] Never inject inter-sentence silence
> Splitting on `silencedetect` and concatenating with an added `anullsrc` gap is an anti-pattern: it
> produces FEWER, LONGER, DEADER pauses than the model's own prosody, and reviewers hear it as
> "audible breaks" or "badly stitched segments". Measured on one identical 56-word passage:
>
> | | internal pauses | mean pause |
> |---|---|---|
> | 5 per-sentence calls + 0.85s injected gap | 6 | **0.73s** — dead air |
> | **1 whole-segment call** | 11 | **0.35s** — natural breathing |
>
> For the same reason, **synthesize one call per scene, never per sentence.** Per-sentence calls also
> rush short lines (past 300 wpm) and truncate endings. If a segment risks running long, split it at
> a pause the model already produces and cross-fade, or shorten the text.
>
> Also note ffmpeg's `silenceremove` defaults to `stop_periods=-1`, which squashes *every* internal
> silence — including the model's own prosody. Preserve internal pauses explicitly.

After any pacing change, re-measure each segment and let the pipeline re-fit each scene.

### Pronunciation: verify every respelling by transcribing it back

Text-to-speech applies English orthographic rules you did not intend, so a respelling that looks
obviously right is often wrong. For the acronym "WAF":

| spelled | heard back |
|---|---|
| **whaff** | **"WAF"** — correct |
| `waff` | "Woff" — after /w/, "a" is pulled toward /ɒ/ (want, wash, watch) |
| `WAF` unmodified | "Web" — the model expands the bare acronym |
| `whaf` / `w-aff` | "WEF" / "WF" |

Leaving an acronym untouched is not safe either. Synthesize each new term in a natural sentence, run
ASR on the output, and only add the lexicon row once the readback is correct.

### Audio QA before anyone reviews the cut

- **A trailing non-lexical artifact is invisible to transcription** — one scored a *perfect* 1.00
  text-similarity, because a sound with no words cannot be detected by comparing words. Add an
  energy-envelope check: mean |amplitude| over each segment's final ~250ms, flagged when a sentence
  should have decayed but hasn't.
- **Guard any automated trim with a re-transcription** and revert when similarity drops — a blind
  trimmer removes real words (in one run it would have damaged half the segments it touched).
- **Flag rate outliers** above ~1.35× the median wpm; that is where swallowed words cluster.
- **Census silences >0.5s** in the final mix — only intentional bookends should be long.
- **Don't use sample-level discontinuity as a stitch metric.** Calibrate first: an accepted cut and a
  rejected cut measured 503 and 502 jumps respectively, so it separates nothing.
- **`difflib.SequenceMatcher` is unreliable above 200 characters** — its autojunk heuristic garbaged
  a correct segment's score to 0.19 purely because it was the longest input. Compare word lists with
  `autojunk=False`.

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
