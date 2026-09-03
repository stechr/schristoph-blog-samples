#!/usr/bin/env python3
"""
Score one or more reference clips from the command line.

The web UI is the comfortable way to record and compare takes, but the whole point of the
scorecard is that it is a plain function: audio in, numbers out. This exposes that directly so
you can grade clips you already have, or wire the check into a pipeline before it spends money
on a GPU.

    python -m voice_studio.score take1.wav take2.wav
    python -m voice_studio.score --json take1.wav
    python -m voice_studio.score --quiet *.wav        # one line per file

Exit code is the worst verdict across all files, so it works as a gate:

    0  keep     — every clip is usable
    1  review   — at least one clip is borderline
    2  reject   — at least one clip fails a hard check
    3  error    — a file could not be read

The hard checks (any one of them rejects, regardless of score) are: signal-to-noise below
20 dB, any meaningful clipping, a duration outside 8-45 s, a sample rate below 24 kHz, and
integrated loudness below -33 LUFS. That last one exists because a clip too quiet to normalize
without lifting its own noise floor is unusable even when it is otherwise clean -- a take at
-38 LUFS once scored "keep, four stars" here on the strength of a 45 dB SNR and then produced
audible crackle in the finished narration.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from .quality import score_file

# worst-verdict tracking: higher wins
_RANK = {"keep": 0, "review": 1, "reject": 2}


def _fmt(v, unit: str = "", nd: int = 1) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}f}{unit}"
    return f"{v}{unit}"


def _report(sc) -> None:
    """Human-readable scorecard, grouped the way the decision actually gets made."""
    d = dataclasses.asdict(sc)
    icon = {"keep": "OK    ", "review": "REVIEW", "reject": "REJECT"}.get(sc.verdict, "?     ")
    print(f"\n{icon}  {sc.path}")
    print(f"  verdict   {sc.verdict}  ({sc.stars} star{'s' if sc.stars != 1 else ''}, "
          f"overall {_fmt(sc.overall_score)}  =  acoustic {_fmt(d.get('objective_score'))} "
          f"+ delivery {_fmt(sc.delivery_score)})")

    print("  signal    "
          f"{_fmt(sc.duration, 's', 2)} · {sc.sample_rate} Hz · {sc.channels}ch"
          + (f" · {sc.bits_per_sample}-bit" if sc.bits_per_sample else ""))
    print("  level     "
          f"{_fmt(sc.integrated_lufs, ' LUFS')} · peak {_fmt(sc.true_peak_dbtp, ' dBTP', 2)} · "
          f"SNR {_fmt(sc.snr_db, ' dB')} · floor {_fmt(sc.noise_floor_dbfs, ' dBFS')}")
    print("  delivery  "
          f"{_fmt(sc.wpm, ' wpm', 0)} · pitch var {_fmt(sc.pitch_std_semitones, ' st', 2)} · "
          f"{sc.pause_count} pauses (mean {_fmt(sc.mean_pause_s, 's', 2)}) · "
          f"silence {_fmt(sc.silence_ratio * 100, '%', 0)}")

    if sc.labels:
        print(f"  labels    {', '.join(sc.labels)}")
    if sc.issues:
        print("  issues")
        for i in sc.issues:
            print(f"    - {i}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m voice_studio.score",
        description="Grade voice reference clips before cloning from them.")
    ap.add_argument("files", nargs="+", help="audio file(s) to score")
    ap.add_argument("--json", action="store_true",
                    help="emit the full scorecard as JSON (one object per file)")
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="one line per file: verdict, stars, duration, loudness")
    ap.add_argument("--no-transcript", action="store_true",
                    help="skip transcription (faster; drops WPM and word error rate)")
    ap.add_argument("--no-mos", action="store_true",
                    help="skip the perceptual quality model (faster)")
    a = ap.parse_args(argv)

    worst = 0
    out = []
    for f in a.files:
        try:
            sc = score_file(f, with_mos=not a.no_mos, with_transcript=not a.no_transcript)
        except Exception as exc:                                    # noqa: BLE001
            print(f"ERROR   {f}: {exc}", file=sys.stderr)
            worst = max(worst, 3)
            continue

        worst = max(worst, _RANK.get(sc.verdict, 0))
        if a.json:
            out.append(dataclasses.asdict(sc))
        elif a.quiet:
            print(f"{sc.verdict:6}  {sc.stars}*  {sc.duration:6.2f}s  "
                  f"{_fmt(sc.integrated_lufs, ' LUFS'):>12}  {sc.path}")
        else:
            _report(sc)

    if a.json:
        print(json.dumps(out, indent=2, default=str))
    elif not a.quiet and len(a.files) > 1:
        print(f"\nworst verdict: {[k for k, v in _RANK.items() if v == worst][0] if worst < 3 else 'error'}")

    return worst


if __name__ == "__main__":
    raise SystemExit(main())
