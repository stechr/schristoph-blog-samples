#!/usr/bin/env python3
"""Record the sample app with Playwright, holding each segment for its narration length.

This is the *fixed-pause* recording method (best when the app has predictable latency,
like our static sample app): each narration segment occupies EXACTLY its measured audio
duration on screen, so the audio can later be laid back-to-back with no drift.

Layout produced:  [lead-in] [seg1 = d1s] [seg2 = d2s] ... [segN = dNs] [tail]
The lead-in is a quiet hold giving the video a little breathing room before it begins.

Usage (normally called by pipeline/render.py, but runnable directly):
  python pipeline/record.py --script sample-content/narration.json \
      --durations 8.1,9.3,5.0,7.2,6.4,8.8,9.0 --out media/screen.mp4

Requires: playwright (pip) + `playwright install chromium`, and ffmpeg on PATH.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))
from script_model import Script, load_script  # noqa: E402


def _do_step(page, step: dict) -> float:
    """Execute one step. Returns seconds explicitly consumed by the step (for pacing)."""
    action = step.get("action", "wait")
    if action in ("wait", "pause"):
        secs = float(step.get("seconds", 0.0))
        if secs:
            time.sleep(secs)
        return secs
    if action == "click":
        page.click(f"[data-testid={step['testid']}]")
        return 0.0
    if action == "type":
        sel = f"[data-testid={step['testid']}]"
        page.click(sel)
        page.fill(sel, "")
        page.type(sel, step["text"], delay=55)  # visible typing
        if step.get("submit"):
            page.press(sel, "Enter")
        return 0.0
    if action == "eval":
        call = step["call"]
        args = step.get("args", [])
        page.evaluate(f"(a) => window.__demo['{call}'].apply(null, a)", args)
        return 0.0
    raise ValueError(f"unknown step action: {action!r}")


def record(script: Script, durations: list[float], out_mp4: str | Path) -> str:
    from playwright.sync_api import sync_playwright

    assert len(durations) == len(script.segments), "durations/segments length mismatch"
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    vid_dir = Path(tempfile.mkdtemp(prefix="rec_"))
    entry = (REPO / script.entry).resolve()
    if not entry.exists():
        sys.exit(f"[record] app entry not found: {entry}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": script.width, "height": script.height},
            record_video_dir=str(vid_dir),
            record_video_size={"width": script.width, "height": script.height},
        )
        page = ctx.new_page()
        page.goto(entry.as_uri())
        page.wait_for_load_state("networkidle")

        # quiet lead-in (breathing room before the walkthrough begins)
        if script.lead_in_seconds:
            time.sleep(script.lead_in_seconds)

        for seg, dur in zip(script.segments, durations):
            t0 = time.monotonic()
            for step in seg.steps:
                _do_step(page, step)
            # hold the remainder so this segment occupies exactly `dur` seconds
            remaining = dur - (time.monotonic() - t0)
            if remaining > 0:
                time.sleep(remaining)
            print(f"[record] {seg.id}: target {dur:.2f}s "
                  f"(actual {time.monotonic() - t0:.2f}s)")

        if script.tail_seconds:
            time.sleep(script.tail_seconds)

        ctx.close()   # flushes the .webm
        browser.close()

    webm = next(vid_dir.glob("*.webm"))
    # re-encode to mp4 (webm VP8/VP9 doesn't mux into mp4 directly)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm),
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-r", str(script.fps), str(out_mp4)],
        check=True)
    print(f"[record] wrote {out_mp4}")
    return str(out_mp4)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--script", default="sample-content/narration.json")
    ap.add_argument("--durations", required=True,
                    help="comma-separated per-segment audio durations in seconds")
    ap.add_argument("--out", default="media/screen.mp4")
    a = ap.parse_args()
    script = load_script(REPO / a.script)
    durs = [float(x) for x in a.durations.split(",")]
    record(script, durs, REPO / a.out)


if __name__ == "__main__":
    main()
