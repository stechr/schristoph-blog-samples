#!/usr/bin/env python3
"""Per-scene A/V re-time — the robust path for re-voicing or variable-latency captures.

WHEN YOU NEED THIS
------------------
The fixed-pause path (record.py + stitch.py) is ideal when you record the app yourself
and can hold each segment for its narration length. Use *this* module instead when:
  * you already have a screen capture and want to re-voice it (new TTS, new timing), or
  * the on-screen actions have VARIABLE latency (live backends, network) so you can't
    pre-set the recording pauses to the audio lengths.

THE METHOD
----------
Cut the capture into one scene per narration segment at known boundaries, then set each
scene's length to its segment's MEASURED audio duration:
  * narration LONGER than the scene  -> freeze-pad the last frame (ffmpeg tpad)
  * narration SHORTER than the scene -> trim the trailing hold (never cut mid-action)
Concat the re-timed scenes, lay the audio BACK-TO-BACK. Every segment's audio start then
equals its scene boundary, so narration can never drift.

SCENE BOUNDARIES
----------------
Pass `bounds` as a list of (start, end) seconds (one per segment), or load them from a
marks JSON (a list of boundary timestamps captured during recording). Derive them from
ffmpeg scene detection, on-screen timestamps, and frame inspection — see the README.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

DEFAULT_ENCODE = {"w": 1280, "h": 720, "fps": 25}


def _run(cmd):
    subprocess.run(cmd, check=True)


def ffprobe_duration(path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def bounds_from_marks(marks_path) -> list[tuple[float, float]]:
    """marks.json may be a list of N+1 boundary timestamps, or {"marks": [...]}."""
    data = json.loads(Path(marks_path).read_text())
    marks = data["marks"] if isinstance(data, dict) else data
    return [(marks[i], marks[i + 1]) for i in range(len(marks) - 1)]


def _build_scene_clip(video, start, natural, audio_len, out_clip, enc):
    base_vf = f"fps={enc['fps']},scale={enc['w']}:{enc['h']},setsar=1,format=yuv420p"
    venc = ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-an"]
    delta = audio_len - natural
    if delta > 0.02:      # PAD — narration longer than the scene
        vf = f"{base_vf},tpad=stop_mode=clone:stop_duration={delta:.3f}"
        _run(["ffmpeg", "-y", "-loglevel", "error",
              "-ss", f"{start:.3f}", "-t", f"{natural:.3f}", "-i", str(video),
              "-vf", vf, *venc, str(out_clip)])
        return f"pad {delta:.2f}s"
    elif delta < -0.02:   # TRIM — keep first audio_len of the scene
        _run(["ffmpeg", "-y", "-loglevel", "error",
              "-ss", f"{start:.3f}", "-t", f"{audio_len:.3f}", "-i", str(video),
              "-vf", base_vf, *venc, str(out_clip)])
        return f"trim {-delta:.2f}s"
    else:                 # EXACT
        _run(["ffmpeg", "-y", "-loglevel", "error",
              "-ss", f"{start:.3f}", "-t", f"{natural:.3f}", "-i", str(video),
              "-vf", base_vf, *venc, str(out_clip)])
        return "exact"


def retime_stitch(video, wavs, durs, out, bounds, gap=0.0, enc=None, verbose=True):
    """Cut `video` into scenes (per `bounds`), re-time each to its segment audio length,
    lay audio back-to-back, encode h264+aac to `out`. Returns a sync-table summary dict."""
    enc = enc or DEFAULT_ENCODE
    assert len(bounds) == len(wavs) == len(durs), "bounds/wavs/durs length mismatch"
    tmp = Path(tempfile.mkdtemp(prefix="retime_"))
    rows, scene_clips, cum_start = [], [], 0.0

    for i, ((s, e), wav, d) in enumerate(zip(bounds, wavs, durs), start=1):
        natural = e - s
        scene_len = d + gap
        clip = tmp / f"scene{i}.mp4"
        action = _build_scene_clip(video, s, natural, scene_len, clip, enc)
        actual = ffprobe_duration(clip)
        rows.append({"scene": i, "src_start": round(s, 2), "src_end": round(e, 2),
                     "natural_len": round(natural, 2), "audio_len": round(d, 2),
                     "scene_len": round(scene_len, 2), "action": action,
                     "start_offset": round(cum_start, 2), "clip_actual": round(actual, 3)})
        scene_clips.append(clip)
        cum_start += scene_len
        if verbose:
            print(f"[retime] scene{i} {s:>6.2f}->{e:<6.2f} nat={natural:5.2f}s "
                  f"aud={d:5.2f}s {action:<9} @offset={rows[-1]['start_offset']:.2f}s")

    total_video = cum_start
    total_audio = sum(durs) + gap * len(durs)

    concat_list = tmp / "scenes.txt"
    concat_list.write_text("".join(f"file '{c}'\n" for c in scene_clips))
    video_track = tmp / "video_track.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
          "-i", str(concat_list), "-c", "copy", str(video_track)])

    a_inputs, a_filters, a_labels, idx = [], [], [], 0
    for j, wav in enumerate(wavs):
        a_inputs += ["-i", str(wav)]
        a_filters.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo[a{j}]")
        a_labels.append(f"[a{j}]")
        idx += 1
        if gap > 0 and j < len(wavs) - 1:
            a_inputs += ["-f", "lavfi", "-t", f"{gap:.3f}", "-i",
                         "anullsrc=channel_layout=stereo:sample_rate=48000"]
            a_filters.append(f"[{idx}:a]anull[g{j}]")
            a_labels.append(f"[g{j}]")
            idx += 1
    a_graph = ";".join(a_filters) + ";" + "".join(a_labels) + \
        f"concat=n={len(a_labels)}:v=0:a=1[aout]"
    audio_track = tmp / "audio_track.m4a"
    _run(["ffmpeg", "-y", "-loglevel", "error", *a_inputs, "-filter_complex", a_graph,
          "-map", "[aout]", "-c:a", "aac", "-b:a", "160k", str(audio_track)])

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_track),
          "-i", str(audio_track), "-c:v", "copy", "-c:a", "copy", "-shortest", str(out)])

    summary = {"out": str(out), "rows": rows,
               "total_video": round(total_video, 2), "total_audio": round(total_audio, 2),
               "final_duration": round(ffprobe_duration(out), 2)}
    if verbose:
        print(f"[retime] DONE -> {out}  video={summary['total_video']}s "
              f"audio={summary['total_audio']}s final={summary['final_duration']}s")
    return summary


def verify_sync(summary, tol=0.05):
    problems, cum = [], 0.0
    for r in summary["rows"]:
        if abs(r["start_offset"] - cum) > tol:
            problems.append(f"scene{r['scene']}: start_offset {r['start_offset']} != {cum:.2f}")
        if abs(r["clip_actual"] - r["scene_len"]) > max(tol, 0.06):
            problems.append(f"scene{r['scene']}: clip {r['clip_actual']} != len {r['scene_len']}")
        cum += r["scene_len"]
    if abs(summary["total_audio"] - summary["total_video"]) > tol:
        problems.append(f"total_audio {summary['total_audio']} != video {summary['total_video']}")
    return (len(problems) == 0, problems)


def print_table(summary):
    print("\n  scene | src_start->end   | natural | audio  | action   | offset")
    print("  ------+------------------+---------+--------+----------+--------")
    for r in summary["rows"]:
        print(f"  {r['scene']:>5} | {r['src_start']:>6.2f}->{r['src_end']:<7.2f} | "
              f"{r['natural_len']:>6.2f}s | {r['audio_len']:>5.2f}s | {r['action']:<8} | "
              f"{r['start_offset']:>6.2f}s")
    print(f"  totals: video={summary['total_video']}s audio={summary['total_audio']}s "
          f"final={summary['final_duration']}s")
