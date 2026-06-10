#!/usr/bin/env python3
r"""End-to-end demo-video renderer.

Pipeline:  narration script -> TTS (3 backends) -> record OR re-time -> stitch -> mp4

  python pipeline/render.py --backend polly                       # default, no AWS deploy
  python pipeline/render.py --backend qwen-speaker --speaker Aiden # SageMaker endpoint
  python pipeline/render.py --backend qwen-clone \                 # SageMaker endpoint
      --ref-audio path/to/ref.wav --ref-text "$(cat ref_text.txt)"

Methods
  fixed   (default) record the sample app, holding each segment for its audio length,
          then lay audio back-to-back. Best for self-recorded, predictable apps.
  retime  re-time an EXISTING capture (--video) per scene to the new audio lengths,
          using --marks (boundary timestamps). Best for re-voicing / variable latency.

Synthesis is idempotent: a valid existing wav in --audio-dir is reused (so re-runs and
the scale-to-zero SageMaker endpoint are not needlessly re-invoked).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
sys.path.insert(0, str(REPO / "sagemaker"))

import retime as retime_mod  # noqa: E402
from script_model import load_script  # noqa: E402
from stitch import stitch  # noqa: E402
from tts import duration, synth_segment  # noqa: E402


def _synth_one(text, out_wav, backend, opts):
    """Synthesize one segment, reusing a valid existing wav (idempotent + cost-aware)."""
    out_wav = Path(out_wav)
    if out_wav.exists() and out_wav.stat().st_size > 1024:
        try:
            if duration(out_wav) > 0.3:
                print(f"[render] reuse {out_wav.name} ({duration(out_wav):.2f}s)")
                return out_wav
        except Exception:  # noqa: BLE001
            pass
    synth_segment(text, str(out_wav), backend=backend, **opts)
    return out_wav


def synth_all(script, backend, audio_dir, opts):
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    wavs, durs = [], []
    for seg in script.segments:
        out_wav = audio_dir / f"{seg.id}.wav"
        print(f"[render] segment {seg.id} via {backend}")
        w = _synth_one(seg.text, out_wav, backend, opts)
        d = duration(w)
        wavs.append(w)
        durs.append(d)
        print(f"[render] {seg.id}: {d:.2f}s")
    return wavs, durs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--script", default="sample-content/narration.json")
    ap.add_argument("--backend", choices=["polly", "qwen-speaker", "qwen-clone"],
                    default="polly")
    ap.add_argument("--method", choices=["fixed", "retime"], default="fixed")
    ap.add_argument("--out", default="media/demo.mp4")
    ap.add_argument("--audio-dir", default=None, help="default: media/audio-<backend>")
    ap.add_argument("--screen", default="media/screen.mp4",
                    help="recorded screen capture path (written in fixed, read in retime)")
    # qwen-speaker / qwen-clone options
    ap.add_argument("--speaker", default=None)
    ap.add_argument("--instruct", default=None)
    ap.add_argument("--ref-audio", default=None)
    ap.add_argument("--ref-text", default="")
    # retime options
    ap.add_argument("--video", default=None, help="existing capture to re-time (retime)")
    ap.add_argument("--marks", default=None, help="boundary-timestamps JSON (retime)")
    ap.add_argument("--gap", type=float, default=0.0)
    a = ap.parse_args()

    script = load_script(REPO / a.script)
    audio_dir = a.audio_dir or f"media/audio-{a.backend}"
    opts = {}
    for k in ("speaker", "instruct", "ref_audio", "ref_text"):
        v = getattr(a, k.replace("-", "_"))
        if v:
            opts[k] = v

    print(f"[render] backend={a.backend} method={a.method} out={a.out}")
    wavs, durs = synth_all(script, a.backend, REPO / audio_dir, opts)

    out = REPO / a.out
    if a.method == "retime":
        video = Path(a.video or (REPO / a.screen))
        if not video.exists():
            sys.exit(f"[render] retime needs an existing --video (got {video})")
        if a.marks:
            bounds = retime_mod.bounds_from_marks(REPO / a.marks)
        else:
            sys.exit("[render] retime needs --marks (boundary timestamps JSON)")
        enc = {"w": script.width, "h": script.height, "fps": script.fps}
        summary = retime_mod.retime_stitch(video, wavs, durs, out, bounds, gap=a.gap, enc=enc)
        retime_mod.print_table(summary)
        ok, problems = retime_mod.verify_sync(summary)
        print("[render] SYNC VERIFIED ✓" if ok else "[render] SYNC WARNINGS:")
        for p in problems:
            print(f"  - {p}")
        return

    # fixed (default): record the app, then lay audio back-to-back
    from record import record
    screen = record(script, durs, REPO / a.screen)
    stitch(screen, wavs, script.lead_in_seconds, out)
    total = script.lead_in_seconds + sum(durs) + script.tail_seconds
    print(f"[render] DONE -> {out}  (~{total:.1f}s: "
          f"lead {script.lead_in_seconds}s + narration {sum(durs):.1f}s + "
          f"tail {script.tail_seconds}s)")


if __name__ == "__main__":
    main()
