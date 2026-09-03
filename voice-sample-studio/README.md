# 🎙️ Voice Sample Studio

A small **local** web app to record, score, and manage high-quality voice
reference clips for the **Qwen3-TTS `voice_clone`** path (the cloned narrator used
by the `blog-screencast-video` / `demo-video` pipelines).

It records multiple takes, plays them back, scores each take's **acoustic quality**
*and* its **delivery / prosody** (speaking rate, intonation, dynamics, phrasing),
shows a prominent **keep / review / reject** verdict with a 1–5 star rating, auto
transcribes the text, and exports kept takes both as a full-quality master **and**
as a Qwen-ready **24 kHz mono** clip paired with its `ref_text.txt`. Select any take
to open a **detail view** with its full scorecard, audio replay, an editable name,
**actionable advice for your next recording** (offline rule-based *and* an optional
LLM-generated variant, side-by-side), and a **voice preview** that synthesizes sample
text in that take's cloned voice so you can hear how the clone will sound.

> The clone **inherits the cadence, pace, pitch and timbre of the reference clip**,
> so a good reference is calm, clear, clean (low noise / no clipping), full
> bandwidth, well-paced, expressive (not monotone), and long enough to capture your
> range. This tool tells good takes from bad — **reference-clip quality is the #1
> lever for a good clone.**

## Demo

[![Voice Sample Studio walkthrough](https://schristoph.online/media/voice-sample-studio-demo-poster.png)](https://schristoph.online/media/voice-sample-studio-demo.mp4)

A walkthrough of the master-detail app — record, score, the keep/review/reject verdict,
side-by-side advice, and a live voice preview. **▶ [Watch the demo](https://schristoph.online/media/voice-sample-studio-demo.mp4)**
(narration is a cloned voice; synthesis is non-deterministic, so output varies).

The **core** (record / score / manage / export) runs **locally on CPU — no cloud
calls**. Two **optional** features use the cloud and **gracefully degrade** if it is
unavailable: *rich advice* (Amazon Bedrock Claude) and *voice preview* (the Qwen3-TTS
endpoint). The app never crashes when they are absent.

---

## Quick start

```bash
cd ~/projects/voice-sample-studio

# Launch the single-page Gradio app (opens in your browser).
# This command enables ALL metrics (pitch, WPM/transcript, perceptual MOS) plus
# the optional cloud features (boto3: rich advice + voice preview):
uv run --with gradio --with soundfile --with numpy --with pyloudnorm \
    --with librosa --with faster-whisper --with torch --with torchaudio \
    --with boto3 \
    python -m voice_studio.app
```

Everything except `gradio/soundfile/numpy/pyloudnorm/librosa` degrades gracefully:

- drop `--with faster-whisper` → no transcript / WER / WPM (pace falls back to a
  silence-based pause estimate),
- drop `--with torch --with torchaudio` → no perceptual MOS,
- `librosa` powers the pitch-variation metric (drop it and pitch is reported `n/a`),
- drop `--with boto3` → no *rich advice* and no *voice preview* (the app shows
  basic advice only and disables the preview button with a clear message).

The two cloud features also need credentials in the environment: **rich advice** uses
Amazon Bedrock (`bedrock-runtime` Converse, region `us-east-1` by default) and **voice
preview** invokes the Qwen3-TTS async endpoint. Without working creds/endpoint they
degrade — they never crash the app.

Or, with the project installed (`uv pip install -e ".[transcribe,mos]"`): `voice-studio`.

### Score a clip from the command line

The web UI is the comfortable way to record and compare takes, but the scorecard is just a
function: audio in, numbers out. Grade clips you already have, or gate a pipeline before it
spends anything on a GPU:

```bash
uv run --no-project --with numpy --with soundfile --with pyloudnorm \
    --with librosa --with faster-whisper python -m voice_studio.score take1.wav take2.wav

# one line per file, no transcription (fast)
... python -m voice_studio.score --quiet --no-transcript *.wav

# full scorecard as JSON
... python -m voice_studio.score --json take1.wav
```

Exit code is the worst verdict across all files, so it works as a gate: `0` keep, `1` review,
`2` reject, `3` error.

### Headless self-test (no mic needed)

```bash
uv run --no-project --with numpy --with soundfile --with pyloudnorm \
    --with librosa --with faster-whisper python selftest.py
# add  --with torch --with torchaudio  to also exercise the MOS assertion
# optionally pass a clean reference wav:  python selftest.py /path/to/clean.wav
```

The self-test generates noisy / clipped / band-limited / speed-perturbed / monotone
variants of a clean reference with ffmpeg and asserts the scorer ranks the clean clip
highest, detects each acoustic defect, orders WPM by speed, and flags the monotone
clip's low pitch variation. See **Self-test results** below.

### End-to-end UI test / demo driver (`ui_demo.py`)

`selftest.py` covers the quality engine; `ui_demo.py` covers the **browser UI** —
it builds the app in-process on an isolated, seeded store (your real recordings
are never touched), drives a real Chromium with Playwright, and asserts the full
master-detail flow: load → select a row → detail view (scorecard, replay, advice,
preview) → rename (persisted) → keep → export.

```bash
# assertion mode (headless, deterministic; rich-advice + preview show their
# graceful-degrade notes when boto3/creds are absent):
uv run --with gradio --with soundfile --with numpy --with pyloudnorm \
    --with librosa --with faster-whisper --with torch --with torchaudio \
    --with playwright python ui_demo.py --test

# visible, slowed-down walkthrough for screen-recording a demo:
uv run ... --with playwright python ui_demo.py --demo --slow-mo 700
```

It never triggers a real (GPU) voice-preview synth unless you pass `--synth`.
Screenshots of each step are written to `/tmp/vss-uitest`.

---

## What it does (single page)

| Feature | Notes |
|---|---|
| **Record** | Gradio mic component (or upload a wav). Captured at the device's full quality. |
| **Verdict card** | Big, legible `keep`/`review`/`reject` + overall score + ★ rating + labels. |
| **Takes table** | Auto-populates as you record (no manual refresh). Clean, non-cramped headers. **Select a row** to open its detail view. |
| **Master-detail** | Selecting a take renders a detail panel on the same page: full scorecard, **audio replay**, an **editable name** (persists to `index.json` + used as the export slug), and keep / reject / delete / export actions. |
| **Actionable advice** | Side-by-side: **Basic** (offline, deterministic, rule-based from the scorecard) and **Rich** (Bedrock Claude; graceful-degrades to a note if unavailable). Both phrased as *“to improve your next recording.”* |
| **Voice preview** | Synthesize a preset paragraph (technical / narrative / conversational) **or your own text** in *that take's cloned voice* (Qwen `voice_clone`, using the take's own WAV + transcript) and play it back. Graceful-degrades if the endpoint is unavailable. |
| **Dual export** | Per take: full-quality **master WAV** + **24 kHz mono** Qwen clip + `ref_text.txt` (named after the take). |
| **Transcription** | Local Whisper auto-fills `ref_text` + WER vs the target script (`<name>` token ignored). |

Take metadata (incl. editable name + created timestamp) persists in a small JSON
index (`index.json`) under the recordings directory
(`~/.voice-sample-studio/recordings` by default, override with
`VOICE_STUDIO_RECORDINGS`). Identical re-inserts of the same recording are
de-duplicated by content hash, so one recording is always one row.

---

## Architecture

The scoring logic is **deliberately separate from the Gradio UI** so it can be
unit-tested without a microphone:

```
voice_studio/
├── audio_io.py     # decode any wav -> mono float32 (soundfile, ffmpeg fallback)
├── quality.py      # acoustic + delivery metrics + scorecard + verdict  (UI-independent)
├── mos.py          # perceptual MOS (TorchAudio-SQUIM default; NISQA/DNSMOS hooks)
├── transcribe.py   # local Whisper: text + word timestamps + WER  (graceful degrade)
├── advice.py       # next-recording advice: BASIC (offline, rule-based) + RICH (Bedrock)
├── preview.py      # voice preview: synth sample text in the take's cloned voice (Qwen)
├── export.py       # dual export: master + 24 kHz mono + ref_text.txt
├── store.py        # JSON-backed take index (name, timestamp, dedupe, row-select map)
└── app.py          # thin single-page master-detail Gradio UI (delegates to the above)
selftest.py         # headless verification of the quality engine + advice + preview wiring
```

---

## Quality metrics & thresholds

All metrics are computed locally. Two families:

### Acoustic (signal quality) → **objective score (0–100)**

| Metric | What / how | Pass guidance | Weight |
|---|---|---|---|
| **SNR** | 90th-pct vs 10th-pct frame energy | ≥ 35 dB great, < 20 dB **reject** | 0.24 |
| **Noise floor** | 10th-pct frame level (dBFS) | < −50 dBFS | 0.14 |
| **Clipping** | fraction of near-full-scale samples | > 0.05% → **reject** | 0.13 |
| **True peak** | 4× oversampled peak (dBTP) | ≤ −1.0 dBTP | 0.07 |
| **Loudness** | integrated LUFS (pyloudnorm / ffmpeg `loudnorm`) | −30…−12 LUFS (norm target −16); below −33 → **reject** | 0.11 |
| **Duration** | seconds | 10–20 s ideal; <8 or >45 → **reject** | 0.09 |
| **Sample rate** | input SR | ≥ 24 kHz (Qwen reference rate) | 0.06 |
| **Silence ratio** | voiced-frame fraction + lead/tail trim hints | < 45% silence | 0.06 |
| **Bandwidth** | occupied BW at −40 dB of avg voiced spectrum | ≥ 9 kHz great, < 5 kHz muffled | 0.10 |

### Delivery / prosody (how the clone will *sound*) → **delivery score (0–100)**

The clone inherits the reference's cadence, so these matter as much as cleanliness.
Each sub-metric maps to a 0–1 score; the delivery score is the mean of the
**available** sub-metrics (missing ones are excluded).

| Metric | What / how | Bands |
|---|---|---|
| **Speaking rate (WPM)** | words / spoken-span (Whisper word timestamps); articulation rate excludes pauses | <105 **too slow/draggy** · 105–120 *a touch slow* · 120–165 **good pace** · 165–175 ok · >175 **too fast** |
| **Pitch variation** | F0 std in **semitones** over voiced frames (librosa `pyin`); + mean F0 & range | <1.5 st **monotone/flat/boring** · 2–6 st **expressive/lively** · >9 st *very sing-songy* |
| **Loudness dynamics** | p95 − p10 of voiced frame RMS (dB) | <6 dB **flat delivery** · 8–22 dB **good dynamics** |
| **Pause profile** | count + mean length of inter-word gaps ≥ 0.30 s (or silence gaps) | >18 pauses/min **choppy/hesitant** · else **smooth** |

### Overall score, stars & verdict

- **overall** = `0.75 × objective + 0.25 × delivery`; if a perceptual MOS is
  available it is folded in: `0.6 × (that blend) + 0.4 × (MOS→0–100)`.
- **★ rating** from the overall score: 1 (<40) · 2 (40–55) · 3 (55–70) · 4 (70–85) · 5 (≥85).
- **Hard rejects** (independent of score, **acoustic only** — delivery never hard-rejects):
  SNR < 20 dB, clipping detected, duration out of [8, 45] s, or SR < 24 kHz. Otherwise
  the verdict is `keep` (≥ 75), `review` (≥ 55), or `reject`.

### Labels

Each take gets human-readable chips derived from the measures, shown alongside the
raw numbers: `clear, muffled, noisy, clipped/distorted, too quiet, too loud, too fast,
good pace, too slow/draggy, monotone/flat/boring, expressive/lively, choppy/hesitant,
smooth, too short, too long, natural, synthetic-sounding`.

All thresholds are the constants at the top of `voice_studio/quality.py` — tune freely.

### Perceptual MOS (enabled by default in v2)

`mos.py` predicts a 1–5 perceptual quality score. The **default backend is
TorchAudio-SQUIM (objective)** — a reference-free, non-intrusive model that estimates
wideband **PESQ** (a 1.0–4.5 MOS-LQO scale), surfaced directly as a MOS-style number.

Licenses (all permissive): **torch** BSD-3-Clause · **torchaudio** BSD-2-Clause ·
**SQUIM_OBJECTIVE weights** Creative Commons Attribution 4.0 (**CC-BY-4.0**).

> ⚠️ We deliberately do **not** use `SQUIM_SUBJECTIVE` — its weights are CC-BY-**NC**-4.0
> (non-commercial), which fails the permissive-license policy.

If torch/torchaudio aren't installed the MOS is reported `unavailable` and the take is
scored on objective + delivery metrics only — a large/flaky model download never blocks
the app. Legacy NISQA / DNSMOS hooks remain (set `VOICE_STUDIO_NISQA_WEIGHTS` /
`VOICE_STUDIO_DNSMOS_DIR`). Disable MOS entirely with `VOICE_STUDIO_DISABLE_MOS=1`.

> _Attribution (CC-BY-4.0): TorchAudio-SQUIM — Kumar et al., "TorchAudio-Squim:
> Reference-less Speech Quality and Intelligibility measures in TorchAudio", ICASSP 2023._

### Transcription (optional)

`transcribe.py` prefers **faster-whisper** (CPU-friendly, MIT), falls back to
**openai-whisper**, else `unavailable`. It now also returns **word timestamps**, which
power the WPM and pause-profile metrics. Set model size with
`VOICE_STUDIO_WHISPER_MODEL` (default `base`). The transcript auto-fills `ref_text.txt`
on export — **review it**, since the `voice_clone` ICL path needs the *exact* transcript
(a wrong `ref_text` causes over-long generation / timeout). WER ignores the literal
`<name>` token from the default script so an un-filled placeholder never inflates it.

---

## Actionable advice (next recording)

When you select a take, the detail view shows two advice panels **side-by-side** so
you can compare them. Both are phrased as forward-looking tips for your *next*
recording (not just a diagnosis of this one):

- **Basic** — a deterministic, **offline**, rule-based function of the scorecard
  (`advice.basic_advice`). It maps the existing metrics/issues to concrete tips,
  e.g. *“You clipped (X% near full-scale) — lower input gain or move ~10 cm back,”*
  *“A touch fast at NNN WPM — aim 120–165,”* *“Background noise is high (SNR XX dB) —
  record in a quieter room,”* *“Fairly monotone (pitch std X st) — add vocal
  variation.”* It is a pure function (same scorecard → same advice) and is
  unit-tested in `selftest.py`.
- **Rich** — an LLM-generated variant via **Amazon Bedrock Claude** (`bedrock-runtime`
  Converse, `us-east-1` by default; override with `VOICE_STUDIO_BEDROCK_MODEL` /
  `VOICE_STUDIO_BEDROCK_REGION`). It is fed the same scorecard numbers + labels and
  returns concise, friendly, actionable advice. If boto3 / creds / the model are
  unavailable it **degrades** to a small *“rich advice unavailable”* note and the
  basic panel still shows — it never crashes the app.

## Voice preview

The detail view can synthesize sample text **in the selected take's cloned voice** so
you can hear how the clone will sound *before* committing the take. It uses the
Qwen3-TTS `voice_clone` path with the take's **own WAV** as the reference (downsampled
to 24 kHz mono, sent inline) and its **transcript** as `ref_text`. Choose one of three
preset paragraphs (technical / narrative / conversational) or type your own, then
**Generate preview**. Previews are saved under
`~/.voice-sample-studio/recordings/exports/<take-id>/previews/<slug>.wav` (gitignored).

If the Qwen endpoint or boto3/creds are unavailable the button is disabled with a
clear message; the rest of the app works offline. The endpoint is scale-to-zero, so
the first preview after an idle period cold-starts (~5–10 min) while it warms up.



| Package | License | Role |
|---|---|---|
| numpy | BSD-3 | arrays / DSP |
| soundfile | BSD-3 | wav decode |
| pyloudnorm | MIT | LUFS |
| gradio | Apache-2.0 | UI |
| librosa | ISC | pitch (`pyin`) intonation metric |
| faster-whisper | MIT | transcript + word timestamps (WPM / pauses / WER) |
| torch | BSD-3 | MOS backend runtime |
| torchaudio | BSD-2 | TorchAudio-SQUIM objective MOS |
| SQUIM_OBJECTIVE weights | CC-BY-4.0 | the MOS model itself |
| boto3 | Apache-2.0 | optional: rich advice (Bedrock) + voice preview (Qwen endpoint) |

All permissive (no GPL/AGPL/copyleft, no non-commercial weights).

---

## Qwen alignment

Matches `~/projects/qwen3-tts-video/recording/`:

- Export produces a **24 kHz mono PCM** WAV (named after the take) + `ref_text.txt`.
- Drop both into `qwen3-tts-video/recording/` and run the clone path.

---

## Self-test results

Run on the real `qwen3-tts-video/recording/user_sample.wav` (24 kHz mono, ~27 s) plus
ffmpeg-synthesized variants (white-noise, +40 dB clip, telephone-band low-pass,
`atempo=1.4`/`0.7` speed, and a 150 Hz monotone tone):

<!-- SELFTEST_RESULTS -->
```
=== SCORECARDS (acoustic) ===
CLEAN        score=  76.1  verdict=keep    snr=  41.8dB  nf=  -69.5dBFS  clip= 0.000%  bw=  11227Hz  dyn=28.3dB
noisy        score=  63.2  verdict=reject  snr=  11.3dB  nf=  -38.6dBFS  clip= 0.000%  bw=  12000Hz  dyn=13.4dB
clipped      score=  55.0  verdict=reject  snr=  29.0dB  nf=  -29.5dBFS  clip=34.880%  bw=  11648Hz  dyn=29.2dB
bandlimited  score=  64.5  verdict=review  snr=  45.1dB  nf=  -76.5dBFS  clip= 0.000%  bw=   3926Hz  dyn=26.9dB

=== PITCH VARIATION (F0 std, semitones) ===
CLEAN   std=3.41 st   ·  monotone std=0.0 st   (backend librosa-pyin)

=== SPEAKING RATE (WPM) ===
orig=136.0  ·  faster x1.4 = 190.8  ·  slower x0.7 = 95.6   (backend word-timestamps)

=== PERCEPTUAL MOS ===   (with --with torch --with torchaudio)
CLEAN mos=1.77  ·  noisy mos=1.15   ->  clean >= noisy ✓

=== BASIC ADVICE (rule-based, offline) ===
clipped -> ['clipping', 'noise', 'too_loud']     noisy -> ['noise', 'too_quiet']
band    -> ['choppy','lead_silence','muffled','too_much_silence','too_quiet']
fast(200wpm) -> ['fast','too_short']   monotone(0.5) -> ['monotone','too_short']   perfect -> ['all_good']

=== PREVIEW SYNTH WIRING ===
build_clone_payload: mode=voice_clone  ref_audio b64 ok  text ok   -> OK
real synth (VOICE_STUDIO_PREVIEW_SMOKE=1) -> ok, 24 kHz wav produced ✓

=== ASSERTIONS ===
  ✓ CLEAN ranks above noisy, clipped, and band-limited clips
  ✓ clipping detected on clipped clip
  ✓ noise / low SNR detected on noisy clip
  ✓ band-limiting detected on telephone-band clip
  ✓ monotone has lower pitch-variation than natural speech
  ✓ faster clip > original > slower clip on WPM
  ✓ CLEAN MOS >= degraded MOS
  ✓ basic advice: clipping/noise/muffled/fast/monotone tips + clean=all_good + deterministic
  ✓ preview wiring: voice_clone payload builds (ffmpeg+base64+ref_text)
SELF-TEST PASSED.
```
<!-- /SELFTEST_RESULTS -->

The self-test always runs the acoustic + pitch + **basic-advice** + **preview-wiring**
(offline payload) checks; WPM and MOS run if `faster-whisper` / `torch` are present
(else they skip gracefully). Set `VOICE_STUDIO_PREVIEW_SMOKE=1` (with boto3 + creds +
a warm endpoint) to also do **one real preview synth** end-to-end.

(The clean clip is quiet at ~−32 LUFS — just above the −33 reject line, so it still scores; PESQ-based
MOS is conservative on quiet input, but the *ordering* clean ≥ degraded holds. It still
verdicts `keep` and shows healthy delivery: 136 WPM "good pace", 3.41 st "expressive".)
_See the initiative note for the full options report and the v2 design._

---

## Live mic test (deferred to a foreground session)

The recording UI needs a microphone and a browser, so a person must run it:

```bash
uv run --with gradio --with soundfile --with numpy --with pyloudnorm \
    --with librosa --with faster-whisper --with torch --with torchaudio \
    --with boto3 \
    python -m voice_studio.app
```

Then: replace `<name>` in the pre-filled script with your name, read it aloud, click
record, check the verdict card + scorecard, watch the take appear in the table, then
**select the row** to open its detail view — replay the audio, read both advice panels
(basic + rich), generate a voice preview and listen, rename, keep the best take, and
export. macOS will prompt for microphone permission the first time.

---

## Privacy

Recordings are **your own voice** and are **gitignored** (`recordings/`, `exports/`,
`previews/`, `*.wav`). The core (scoring, MOS, pitch, Whisper) runs **locally on CPU**
and uploads nothing.

The two **optional** cloud features do send data when you use them: **rich advice**
sends the take's *numeric scorecard + labels* (no audio) to Amazon Bedrock, and
**voice preview** uploads the reference clip (the take's WAV) to your own SageMaker
S3 bucket for the Qwen `voice_clone` synth. Both are opt-in (you trigger them) and the
app works fully without them.
