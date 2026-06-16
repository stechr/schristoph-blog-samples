# Demo screencast — Voice Sample Studio v3

A narrated walkthrough video of the v3 master-detail app, produced **audio-first**
(measure-both-then-reconcile) with the narration in a cloned voice (Qwen3-TTS
`voice_clone`). The video binaries are gitignored; only the scripts live here.

## Pipeline

1. **Synthesize a clean studio read** (the KEEP take's source) in the cloned voice,
   so the demo store can be seeded with no microphone.
2. **`synth_narration.py`** — synthesizes the 13 narration segments in the cloned
   voice, loudness-normalizes to ~-16 LUFS, and measures each duration.
3. **`record_demo.py`** — seeds an **isolated** store (`/tmp/vss-demo-store`) with
   3 derived takes (clean → KEEP, +20 dB → REJECT, noise+band-limit → REVIEW),
   launches the app in-process, and drives a calm full feature tour with Playwright
   `recordVideo`. Each scene records **start/end marks**; heavy "dead" time (the
   live LLM advice render after each select, and the ~60 s live preview synth) sits
   in the dropped inter-scene gaps. A single **real** voice-preview synth runs on
   camera (the feature being demoed).
4. **`stitch_demo.py`** — reconciles each scene to its narration
   (`scene_len = max(content, audio) + gap`; trim trailing holds, freeze-pad when
   the narration is longer), concatenates, lays the narration back-to-back, and
   muxes h264 + aac. Prints a per-scene reconcile table and a poster frame.

## Run

```bash
# AWS creds for the cloned-voice synth + live LLM advice must be in the env.
eval "$(aws configure export-credentials --profile <aws-profile> --format env)"
export AWS_REGION=us-east-1

python demo/synth_narration.py --work /tmp/vss-narr
python demo/record_demo.py     --out  /tmp/vss-demo-pass1 --store /tmp/vss-demo-store
python demo/stitch_demo.py     --pass1 /tmp/vss-demo-pass1 --narr /tmp/vss-narr \
                               --out  demo/voice-sample-studio-v3-demo.mp4
```

The app, the demo store, and all outputs are isolated from any real recordings.
