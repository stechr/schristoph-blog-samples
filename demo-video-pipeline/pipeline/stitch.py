"""Stitch narration audio onto a fixed-pause recording.

Because the recorder (record.py) holds each segment for EXACTLY its audio duration,
the narration can be laid back-to-back with a single lead-in offset and it will line up
with the visuals — no per-segment adelay arithmetic, no drift.

  stitch(video, wavs, lead_in, out)  ->  out.mp4

Layout assumed on `video`:  [lead_in] [seg1=d1] [seg2=d2] ... [tail]
Audio is placed starting at `lead_in`, each wav immediately after the previous.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def _run(cmd):
    subprocess.run(cmd, check=True)


def stitch(video: str | Path, wavs: list[str | Path], lead_in: float,
           out: str | Path) -> str:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="stitch_"))

    # 1) concat all narration wavs back-to-back -> a single track (48k stereo)
    inputs, filters, labels = [], [], []
    for i, w in enumerate(wavs):
        inputs += ["-i", str(w)]
        filters.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
        labels.append(f"[a{i}]")
    graph = ";".join(filters) + ";" + "".join(labels) + \
        f"concat=n={len(labels)}:v=0:a=1[cat]"
    narration = tmp / "narration.m4a"
    _run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
          "-filter_complex", graph, "-map", "[cat]", "-c:a", "aac", "-b:a", "160k",
          str(narration)])

    # 2) delay the narration by the lead-in, overlay on the video's (silent) track
    lead_ms = int(round(lead_in * 1000))
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(narration),
          "-filter_complex", f"[1:a]adelay={lead_ms}|{lead_ms}[a]",
          "-map", "0:v", "-map", "[a]",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
          "-movflags", "+faststart", str(out)])
    print(f"[stitch] wrote {out}")
    return str(out)
