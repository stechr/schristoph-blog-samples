#!/usr/bin/env python3
"""
synth_narration.py — synthesize the demo narration in the user's CLONED voice
(Qwen3-TTS voice_clone), loudness-normalize to ~-16 LUFS, and measure durations.

Idempotent: reuses an existing normalized seg wav if present (the endpoint is
scale-to-zero; avoid needless re-spins). Writes:
  <work>/segNN.wav            normalized narration (cloned voice)
  <work>/durations.json       [{seg, scene, file, dur, text}]

Run with AWS creds in env (the synth + S3 wiring uses them):
  eval "$(aws configure export-credentials --profile <aws-profile> --format env)"
  export AWS_REGION=us-east-1
  python demo/synth_narration.py --work /tmp/vss-narr
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

QWEN_DIR = Path.home() / "projects" / "qwen3-tts-video"
# Canonical cloned reference voice — the same export the blog walkthroughs use
# (adopted 2026-06-13). Resolved under the user home so no absolute path is baked in.
REF_EXPORT = Path.home() / ".voice-sample-studio" / "recordings" / "exports" / "76a5bffb1ff4"
REF_WAV = REF_EXPORT / "stefan-eng-1.wav"
REF_TXT = REF_EXPORT / "ref_text.txt"

# 13 narration segments, one per scene (calm, explanatory, plain ASCII).
SEGMENTS = [
    ("01", "01_intro",
     "Welcome to Voice Sample Studio. This is a small web app for recording, scoring, "
     "and managing the short voice samples you use to clone a voice for text to speech. "
     "Let's walk through what it can do."),
    ("02", "02_table",
     "Every take you record shows up here in the takes table. At a glance you can see the "
     "duration, the signal to noise ratio, the speaking pace, the pitch variation, a "
     "perceptual quality score, an overall score, a star rating, and a final verdict: "
     "keep, review, or reject."),
    ("03", "03_select",
     "When you select a row, its full detail view opens right below, on the same page. "
     "No pop ups, no separate screens. Here we picked our clean studio take."),
    ("04", "04_verdict",
     "At the top you get a big, legible verdict card. This one is a clear keep, with a "
     "strong overall score, broken down into acoustic quality, delivery, and a perceptual "
     "mean opinion score."),
    ("05", "05_scorecard",
     "Below that is the full scorecard. The acoustic section covers duration, sample rate, "
     "loudness, true peak and clipping, the noise floor and signal to noise ratio, the "
     "bandwidth, and how much leading and trailing silence to trim."),
    ("06", "06_delivery_replay",
     "The delivery section shows how the clone will actually sound: your speaking rate, "
     "pitch variation, loudness dynamics, and pauses. There is also a transcript with a "
     "word error rate, and an audio player so you can replay the take right here."),
    ("07", "07_rename",
     "Each take has an editable name. Whatever you type here is saved to the index, and it "
     "becomes the file name when you export. Let's rename this one, and you can see it "
     "update instantly in the table."),
    ("08", "08_reject_advice",
     "Now let's pick a different take, one that was recorded too loud and clipped. Notice "
     "the verdict flips to reject. And look at the advice panels. On the left, basic advice "
     "is generated offline with simple rules. On the right, rich advice comes live from a "
     "large language model, with more specific, tailored coaching."),
    ("09", "09_review",
     "This third take has more background noise and a duller, narrower sound. It lands in "
     "the middle, a review. Not bad enough to throw away, but worth re-recording in a "
     "quieter room. The advice points out exactly what to fix."),
    ("10", "10_keep_reject_delete",
     "For every take, you stay in control. You can mark it keep, mark it reject, or delete "
     "it entirely. Your decision is saved straight to the index on disk."),
    ("11", "11_export",
     "When you are happy with a take, export gives you three things: a full quality master, "
     "a clone ready twenty four kilohertz mono version, and a reference transcript file. "
     "Drop those into your cloning pipeline, and you are ready to go."),
    ("12", "12_preview_intro",
     "And here is my favorite part. Voice preview lets you hear a paragraph spoken in this "
     "take's cloned voice, before you commit to it. Pick a preset, or type your own text, "
     "and hit generate."),
    ("13", "13_preview_result",
     "Behind the scenes, it synthesizes the paragraph using the take as the voice reference. "
     "A few moments later, you can play it back and hear the clone, in this voice. "
     "That is Voice Sample Studio."),
]


def ffprobe_dur(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def make_ref_b64(work: Path) -> str:
    ref24 = work / "ref-24k.wav"
    if not ref24.exists():
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", str(REF_WAV),
                        "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(ref24)],
                       capture_output=True, check=True, stdin=subprocess.DEVNULL)
    return base64.b64encode(ref24.read_bytes()).decode("ascii")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/vss-narr")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    if not REF_WAV.exists() or not REF_TXT.exists():
        raise SystemExit(f"Missing ref audio/text under {REF_EXPORT}")
    ref_text = REF_TXT.read_text().strip()

    sys.path.insert(0, str(QWEN_DIR / "sagemaker"))
    import invoke_async  # type: ignore

    ref_b64 = make_ref_b64(work)
    durations = []
    for seg, scene, text in SEGMENTS:
        norm = work / f"seg{seg}.wav"
        if norm.exists() and norm.stat().st_size > 1000:
            dur = ffprobe_dur(norm)
            print(f"[seg{seg}] reuse ({dur:.2f}s)", flush=True)
            durations.append({"seg": seg, "scene": scene, "file": str(norm),
                              "dur": dur, "text": text})
            continue
        raw = work / f"seg{seg}-raw.wav"
        payload = {"mode": "voice_clone", "text": text, "language": "en",
                   "ref_audio": ref_b64, "ref_text": ref_text}
        print(f"[seg{seg}] synth ({len(text)} chars)...", flush=True)
        invoke_async.synth(payload, str(raw), timeout=args.timeout)
        # loudness-normalize to ~-16 LUFS
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", str(raw),
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-ar", "24000", "-ac", "1", str(norm)],
                       capture_output=True, check=True, stdin=subprocess.DEVNULL)
        dur = ffprobe_dur(norm)
        print(f"[seg{seg}] OK -> {norm.name} ({dur:.2f}s)", flush=True)
        durations.append({"seg": seg, "scene": scene, "file": str(norm),
                          "dur": dur, "text": text})

    (work / "durations.json").write_text(json.dumps(durations, indent=2))
    total = sum(d["dur"] for d in durations)
    print(f"\n* {len(durations)} segments, total narration {total:.1f}s", flush=True)
    print(f"* durations -> {work/'durations.json'}", flush=True)


if __name__ == "__main__":
    main()
