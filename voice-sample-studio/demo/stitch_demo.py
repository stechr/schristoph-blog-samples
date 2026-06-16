#!/usr/bin/env python3
"""
stitch_demo.py — reconcile PASS-1 capture against the cloned-voice narration and
produce the final synced MP4 (audio-first, measure-both-then-reconcile).

Per scene: scene_len = audio_len + GAP. We TRIM the trailing hold when the
captured scene is longer than the narration, or FREEZE-PAD the last frame when the
narration is longer. Narration is laid back-to-back at the cumulative scene
offsets, so audio start == scene start by construction. Encodes h264 + aac and
prints a per-scene reconcile table + spot-checked frame offsets.

  python demo/stitch_demo.py --pass1 /tmp/vss-demo-pass1 --narr /tmp/vss-narr \
      --out demo/voice-sample-studio-v3-demo.mp4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

GAP = 0.4          # calm pause held between scenes (s)
FPS = 30
W, H = 1280, 720
SCENE_LABELS = [   # narration seg -> scene mark label
    "01_intro", "02_table", "03_select", "04_verdict", "05_scorecard",
    "06_delivery_replay", "07_rename", "08_reject_advice", "09_review",
    "10_keep_reject_delete", "11_export", "12_preview_intro", "13_preview_result",
]


def run(cmd, **kw):
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, **kw)


def ffprobe_dur(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)]).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass1", default="/tmp/vss-demo-pass1")
    ap.add_argument("--narr", default="/tmp/vss-narr")
    ap.add_argument("--out", default="demo/voice-sample-studio-v3-demo.mp4")
    ap.add_argument("--work", default="/tmp/vss-stitch")
    args = ap.parse_args()

    p1 = Path(args.pass1)
    narr = Path(args.narr)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    video = p1 / "video.webm"
    marks = json.loads((p1 / "marks.json").read_text())["marks"]
    durs = {d["scene"]: d for d in json.loads((narr / "durations.json").read_text())}
    vid_total = ffprobe_dur(video)

    # Each scene window is [<label>, <label>__end]; inter-scene gaps (live-Bedrock
    # detail renders, the ~60s preview synth wait) are NOT referenced -> dropped.
    tm = {m["label"]: m["t"] for m in marks}

    scenes = []
    for i, label in enumerate(SCENE_LABELS):
        start = tm[label]
        endk = label + "__end"
        content_end = tm.get(endk, tm.get(SCENE_LABELS[i + 1], vid_total) if i + 1 < len(SCENE_LABELS) else vid_total)
        content = max(0.3, content_end - start)
        audio = durs[label]["dur"]
        scene_len = round(max(content, audio) + GAP, 3)
        pad = round(scene_len - content, 3)   # freeze-pad last captured (settled) frame
        decision = "freeze-pad" if audio > content else ("trim-hold" if content - audio > 0.05 else "match")
        scenes.append(dict(i=i, label=label, start=round(start, 3),
                           natural=round(content, 2), content=round(content, 3),
                           audio=round(audio, 2), pad=pad, scene_len=scene_len,
                           decision=decision))

    # ---- extract + retime each scene (two-pass so freeze-pad isn't truncated) ----
    # Pass 1: cut the scene to exactly `content` (clip ENDS there).
    # Pass 2: tpad clones that last frame out to `scene_len` (freeze-pad). Doing it
    # in one pass with `-t` truncates the tpad-added frames, so we split it.
    scene_files = []
    for s in scenes:
        raw = work / f"raw{s['i']:02d}.mp4"
        vf = (f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,"
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1")
        r = run(["ffmpeg", "-nostdin", "-y", "-i", str(video),
                 "-ss", f"{s['start']:.3f}", "-t", f"{s['content']:.3f}",
                 "-vf", vf, "-an", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS), str(raw)])
        if r.returncode != 0:
            print(f"FFMPEG raw{s['i']} failed:\n{r.stderr[-1500:]}", file=sys.stderr); sys.exit(2)
        outp = work / f"scene{s['i']:02d}.mp4"
        if s["pad"] > 0.02:
            r = run(["ffmpeg", "-nostdin", "-y", "-i", str(raw),
                     "-vf", f"tpad=stop_mode=clone:stop_duration={s['pad']:.3f}",
                     "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                     "-pix_fmt", "yuv420p", "-r", str(FPS), str(outp)])
            if r.returncode != 0:
                print(f"FFMPEG pad{s['i']} failed:\n{r.stderr[-1500:]}", file=sys.stderr); sys.exit(2)
        else:
            outp = raw
        s["file_dur"] = round(ffprobe_dur(outp), 2)
        scene_files.append(outp)

    # ---- concat video scenes ----
    concat_list = work / "scenes.txt"
    concat_list.write_text("".join(f"file '{f}'\n" for f in scene_files))
    video_concat = work / "video_concat.mp4"
    r = run(["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(video_concat)])
    if r.returncode != 0:
        print(f"concat failed:\n{r.stderr[-1500:]}", file=sys.stderr); sys.exit(2)

    # ---- narration: pad each seg with silence to its full scene_len, concat ----
    apad_files = []
    for s in scenes:
        seg_wav = Path(durs[s["label"]]["file"])
        padded = work / f"narr{s['i']:02d}.wav"
        r = run(["ffmpeg", "-nostdin", "-y", "-i", str(seg_wav),
                 "-af", f"apad=whole_dur={s['scene_len']}", "-ar", "48000", "-ac", "2",
                 str(padded)])
        if r.returncode != 0:
            print(f"apad scene{s['i']} failed:\n{r.stderr[-1200:]}", file=sys.stderr); sys.exit(2)
        apad_files.append(padded)
    narr_list = work / "narr.txt"
    narr_list.write_text("".join(f"file '{f}'\n" for f in apad_files))
    narr_full = work / "narration_full.wav"
    r = run(["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0",
             "-i", str(narr_list), "-c", "copy", str(narr_full)])
    if r.returncode != 0:
        print(f"narr concat failed:\n{r.stderr[-1200:]}", file=sys.stderr); sys.exit(2)

    # ---- mux ----
    out = Path(args.out)
    if not out.is_absolute():
        out = Path(__file__).resolve().parent.parent / out
    out.parent.mkdir(parents=True, exist_ok=True)
    r = run(["ffmpeg", "-nostdin", "-y", "-i", str(video_concat), "-i", str(narr_full),
             "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)])
    if r.returncode != 0:
        print(f"mux failed:\n{r.stderr[-1500:]}", file=sys.stderr); sys.exit(2)

    final_dur = ffprobe_dur(out)
    vc_dur = ffprobe_dur(video_concat)
    na_dur = ffprobe_dur(narr_full)

    # ---- poster frame from the verdict scene (~2s into scene 04) ----
    poster = out.with_name(out.stem + "-poster.png")
    off = sum(s["scene_len"] for s in scenes[:3]) + 2.0
    run(["ffmpeg", "-nostdin", "-y", "-ss", f"{off:.2f}", "-i", str(out),
         "-frames:v", "1", str(poster)])

    # ---- report ----
    print("\n=== PER-SCENE RECONCILE ===")
    print(f"{'#':>2} {'scene':22} {'start':>7} {'natural':>8} {'content':>8} {'audio':>7} "
          f"{'pad':>6} {'len':>7} {'enc':>6} {'decision':>16}")
    cum = 0.0
    rows = []
    for s in scenes:
        print(f"{s['i']:>2} {s['label']:22} {s['start']:>7.2f} {s['natural']:>8.2f} "
              f"{s['content']:>8.2f} {s['audio']:>7.2f} {s['pad']:>6.2f} {s['scene_len']:>7.2f} "
              f"{s['file_dur']:>6.2f} {s['decision']:>16}")
        rows.append({**s, "cum_offset": round(cum, 2)})
        cum += s["scene_len"]
    print(f"\nvideo_concat={vc_dur:.2f}s  narration={na_dur:.2f}s  final={final_dur:.2f}s")
    print(f"sum(scene_len)={cum:.2f}s")
    print(f"\n* Final : {out}")
    print(f"* Poster: {poster}")
    (work / "reconcile.json").write_text(json.dumps(
        {"final_dur": final_dur, "video_concat": vc_dur, "narration": na_dur,
         "scenes": rows}, indent=2))


if __name__ == "__main__":
    main()
