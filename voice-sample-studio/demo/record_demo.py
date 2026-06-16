#!/usr/bin/env python3
"""
record_demo.py — PASS 1 of the audio-first narrated demo for Voice Sample Studio v3.

Seeds an ISOLATED store (3 takes: clean->KEEP, clipped->REJECT, quiet/flat->REVIEW),
launches the real Gradio app in-process, and drives a calm, completion-gated FULL
feature tour with Playwright recordVideo. Writes:
  - <out>/video.webm        the raw screen capture
  - <out>/marks.json        scene-start offsets (sec, relative to video start)
  - <out>/seed-info.json    seeded take ids/names/verdicts

This is the on-screen pass only. Narration is synthesized separately and reconciled
in stitch_demo.py. A single LIVE Qwen voice_clone preview synth runs during the tour
(the feature being demoed); the endpoint must already be warm.

Run with the project venv (gradio/playwright/boto3/etc already installed) and AWS
creds exported into the env so rich advice (Bedrock) + the preview light up:

    eval "$(aws configure export-credentials --profile <aws-profile> --format env)"
    export AWS_REGION=us-east-1
    .venv/bin/python demo/record_demo.py --out /tmp/vss-demo-pass1
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLEAN_SRC = Path("/tmp/vss-clean/clean.wav")          # pre-synth'd clean studio read (cloned voice)
CLEAN_TXT = Path("/tmp/vss-clean/clean_text.txt")
VIEWPORT = {"width": 1280, "height": 720}


def _ffmpeg(args: list[str]):
    subprocess.run(["ffmpeg", "-nostdin", "-y", *args],
                   capture_output=True, check=True, stdin=subprocess.DEVNULL)


def _ffmpeg_fc(in_path, fc, out_path):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", str(in_path),
                    "-filter_complex", fc, "-map", "[a]", str(out_path)],
                   capture_output=True, check=True, stdin=subprocess.DEVNULL)


def seed_store(root: Path):
    """Seed 3 takes from a clean cloned-voice studio read so verdicts + advice
    visibly differ (recipes verified offline):
       take1 clean                  -> KEEP   (~77)
       take2 +20 dB                 -> REJECT (clipping, ~45)
       take3 +noise & band-limited  -> REVIEW (~63, SNR>20 so no hard-reject)."""
    sys.path.insert(0, str(REPO))
    from voice_studio.quality import score_file
    from voice_studio.store import TakeStore

    if not CLEAN_SRC.exists():
        raise SystemExit(f"Clean source not found: {CLEAN_SRC} (run the clean-clip synth first)")
    target = CLEAN_TXT.read_text().strip() if CLEAN_TXT.exists() else None

    store = TakeStore(root)

    # Take 1 — clean studio read (KEEP).
    clean = root / "src-clean.wav"
    shutil.copy2(CLEAN_SRC, clean)
    sc1 = score_file(str(clean), target_text=target)
    t1 = store.add(str(clean), sc1.to_dict(), name="Studio read")
    print(f"  take1 clean : {t1.id} verdict={sc1.verdict} overall={sc1.overall_score:.0f}", flush=True)

    # Take 2 — hot/clipped (REJECT via clipping hard-reject).
    clipped = root / "src-clipped.wav"
    _ffmpeg(["-i", str(clean), "-af", "volume=20dB", str(clipped)])
    sc2 = score_file(str(clipped), target_text=target)
    t2 = store.add(str(clipped), sc2.to_dict(), name="Recorded too hot")
    print(f"  take2 clipped: {t2.id} verdict={sc2.verdict} overall={sc2.overall_score:.0f}", flush=True)

    # Take 3 — noisy room + dull/narrow band (REVIEW).
    review = root / "src-review.wav"
    _ffmpeg_fc(clean,
               "anoisesrc=color=white:amplitude=0.012:d=30[n];"
               "[0:a][n]amix=inputs=2:duration=first,lowpass=f=3200[a]",
               review)
    sc3 = score_file(str(review), target_text=target)
    t3 = store.add(str(review), sc3.to_dict(), name="Noisy room")
    print(f"  take3 review: {t3.id} verdict={sc3.verdict} overall={sc3.overall_score:.0f}", flush=True)
    return store, t1, t2, t3


def launch_app(store, port: int):
    from voice_studio.app import build_app, _CSS
    demo = build_app(store)
    demo.launch(server_name="127.0.0.1", server_port=port, inbrowser=False,
                show_error=True, prevent_thread_lock=True, css=_CSS,
                allowed_paths=[str(store.root)], quiet=True)
    return demo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/vss-demo-pass1")
    ap.add_argument("--store", default="/tmp/vss-demo-store")
    ap.add_argument("--port", type=int, default=7874)
    ap.add_argument("--synth-timeout", type=int, default=240,
                    help="max sec to wait for the live preview synth")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    store_root = Path(args.store)
    if store_root.exists():
        shutil.rmtree(store_root)
    store_root.mkdir(parents=True)

    print(f"* Seeding isolated store at {store_root}", flush=True)
    store, t1, t2, t3 = seed_store(store_root)
    (out / "seed-info.json").write_text(json.dumps({
        "store": str(store_root),
        "takes": [{"id": t.id, "name": t.name, "verdict": t.verdict,
                   "overall": t.overall_score} for t in (t1, t2, t3)],
    }, indent=2))

    print(f"* Launching app in-process on :{args.port}", flush=True)
    appdemo = launch_app(store, args.port)
    base_url = f"http://127.0.0.1:{args.port}"
    time.sleep(2)

    from playwright.sync_api import sync_playwright

    marks: list[dict] = []
    t0 = [0.0]

    def mark(label: str):
        marks.append({"label": label, "t": round(time.monotonic() - t0[0], 3)})
        print(f"  [mark] {label:24s} @ {marks[-1]['t']:7.2f}s", flush=True)

    rc = 1
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport=VIEWPORT,
                record_video_dir=str(out),
                record_video_size=VIEWPORT,
            )
            t0[0] = time.monotonic()  # ~ video start (context creation)
            page = context.new_page()
            page.set_default_timeout(30000)
            run_tour(page, base_url, store, t1, t2, t3, mark, args.synth_timeout)
            # settle tail then close (flush video)
            page.wait_for_timeout(1500)
            mark("video_end")
            video = page.video
            context.close()  # finalizes the webm
            vid_path = Path(video.path())
            browser.close()
            # rename to a stable name
            final = out / "video.webm"
            if vid_path.exists() and vid_path != final:
                shutil.move(str(vid_path), str(final))
            (out / "marks.json").write_text(json.dumps({"viewport": VIEWPORT,
                                                         "marks": marks}, indent=2))
            print(f"\n* Video: {final}", flush=True)
            print(f"* Marks: {out / 'marks.json'}", flush=True)
            rc = 0
    finally:
        try:
            appdemo.close()
        except Exception:
            pass
    sys.exit(rc)


def run_tour(page, base_url, store, t1, t2, t3, mark, synth_timeout):
    """Calm full feature tour with START/END marks per scene.

    Heavy 'dead' time (the ~10s live-Bedrock detail render after a select, and the
    ~60s live preview synth) is performed in the GAP between a scene's end mark and
    the next scene's start mark, so the stitch step drops it. Each scene's window is
    [<label>, <label>__end]; narration is reconciled into that window."""

    def scroll_to(selector, block="center"):
        try:
            page.eval_on_selector(selector, f"el => el.scrollIntoView({{block:'{block}', behavior:'smooth'}})")
        except Exception:
            pass
        page.wait_for_timeout(900)

    def settle_on(tid):
        """Wait until the detail card shows THIS take id (handler incl. Bedrock done)."""
        page.wait_for_function(
            "(tid) => { const el=document.querySelector('#detail-card'); "
            "return el && el.innerText.includes(tid); }",
            arg=tid, timeout=45000)
        page.wait_for_timeout(1200)

    def select_take(tid):
        page.get_by_role("button", name=tid, exact=True).first.click()
        settle_on(tid)

    def start(lbl): mark(lbl)
    def end(lbl): mark(lbl + "__end")

    tbl = page.locator("#takes-table")

    # ---- Scene 1: INTRO (app header) ----
    page.goto(base_url, wait_until="domcontentloaded")
    tbl.get_by_role("button", name=t1.id, exact=True).first.wait_for(timeout=30000)
    page.evaluate("window.scrollTo({top:0})")
    page.wait_for_timeout(600)
    start("01_intro"); page.wait_for_timeout(3000); end("01_intro")

    # ---- Scene 2: TAKES TABLE ----
    scroll_to("#takes-table")
    start("02_table"); page.wait_for_timeout(3000); end("02_table")

    # ---- Scene 3: MASTER-DETAIL — show the click open the detail (render inside) ----
    start("03_select")
    page.get_by_role("button", name=t1.id, exact=True).first.click()
    settle_on(t1.id)
    scroll_to("#detail-card", block="start")
    page.wait_for_timeout(1200)
    end("03_select")

    # ---- Scene 4: VERDICT CARD (settled t1) ----
    scroll_to("#detail-card", block="start")
    start("04_verdict"); page.wait_for_timeout(2500); end("04_verdict")

    # ---- Scene 5: SCORECARD (acoustic) ----
    page.evaluate("window.scrollBy({top:260, behavior:'smooth'})")
    page.wait_for_timeout(900)
    start("05_scorecard"); page.wait_for_timeout(2500); end("05_scorecard")

    # ---- Scene 6: DELIVERY + REPLAY ----
    page.evaluate("window.scrollBy({top:300, behavior:'smooth'})")
    page.wait_for_timeout(900)
    start("06_delivery_replay"); page.wait_for_timeout(2500); end("06_delivery_replay")

    # ---- Scene 7: RENAME ----
    box = page.get_by_placeholder("rename this take…")
    box.scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    start("07_rename")
    box.fill("Calm studio read v2")
    page.wait_for_timeout(700)
    page.get_by_role("button", name="💾 Save name").click()
    for _ in range(40):
        page.wait_for_timeout(500)
        if "Calm studio read v2" in tbl.inner_text():
            break
    page.wait_for_timeout(1500)
    end("07_rename")

    # ---- Scene 8: REJECT + ADVICE (clipped) — select+render in the gap, then mark ----
    page.evaluate("window.scrollTo({top:0, behavior:'smooth'})")
    page.wait_for_timeout(500)
    select_take(t2.id)                       # ~render time (dropped, pre-mark)
    scroll_to("#detail-card", block="start")
    start("08_reject_advice")
    page.wait_for_timeout(1800)
    try:
        page.get_by_text("Basic advice (offline)").first.scroll_into_view_if_needed()
    except Exception:
        page.evaluate("window.scrollBy({top:520, behavior:'smooth'})")
    page.wait_for_timeout(2200)
    end("08_reject_advice")

    # ---- Scene 9: REVIEW (noisy) ----
    page.evaluate("window.scrollTo({top:0, behavior:'smooth'})")
    page.wait_for_timeout(500)
    select_take(t3.id)                       # dropped
    scroll_to("#detail-card", block="start")
    start("09_review")
    page.wait_for_timeout(2000)
    try:
        page.get_by_text("Basic advice (offline)").first.scroll_into_view_if_needed()
    except Exception:
        pass
    page.wait_for_timeout(1500)
    end("09_review")

    # ---- Scene 10: KEEP / REJECT / DELETE (back on clean take1) ----
    page.evaluate("window.scrollTo({top:0, behavior:'smooth'})")
    page.wait_for_timeout(400)
    select_take(t1.id)                       # dropped
    keep_btn = page.get_by_role("button", name="✓ Keep")
    keep_btn.scroll_into_view_if_needed()
    page.wait_for_timeout(600)
    start("10_keep_reject_delete")
    page.wait_for_timeout(800)
    keep_btn.click()
    settle_on(t1.id)                         # keep re-renders detail (Bedrock)
    page.wait_for_timeout(1500)
    end("10_keep_reject_delete")

    # ---- Scene 11: EXPORT ----
    exp = page.get_by_role("button", name="⬇ Export (master + Qwen ref)")
    exp.scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    start("11_export")
    exp.click()
    for _ in range(25):
        page.wait_for_timeout(400)
        if "Qwen 24" in page.locator("body").inner_text() or "ref_text.txt" in page.locator("body").inner_text():
            break
    page.wait_for_timeout(2200)
    end("11_export")

    # ---- Scene 12: VOICE PREVIEW — pick preset + click generate (synth wait dropped) ----
    try:
        page.get_by_text("Voice preview", exact=False).first.scroll_into_view_if_needed()
    except Exception:
        page.evaluate("window.scrollTo({top:document.body.scrollHeight, behavior:'smooth'})")
    page.wait_for_timeout(900)
    start("12_preview_intro")
    try:
        page.get_by_role("radio", name="Conversational").check()
    except Exception:
        pass
    page.wait_for_timeout(1500)
    gen = page.get_by_role("button", name="🎤 Generate preview")
    gen.scroll_into_view_if_needed()
    page.wait_for_timeout(800)
    gen.click()
    mark("12b_preview_click")
    page.wait_for_timeout(2200)               # show the "generating" state briefly
    end("12_preview_intro")

    # ---- (gap) wait for the REAL synth result — dropped in stitch ----
    got = False
    deadline = time.monotonic() + synth_timeout
    while time.monotonic() < deadline:
        page.wait_for_timeout(1000)
        body = page.locator("body").inner_text()
        if "Preview generated" in body or "preview failed" in body.lower() or "unavailable" in body.lower():
            got = True
            break

    # ---- Scene 13: PREVIEW RESULT + player (payoff) ----
    if got:
        try:
            page.get_by_text("Cloned-voice preview", exact=False).first.scroll_into_view_if_needed()
        except Exception:
            pass
    page.wait_for_timeout(800)
    start("13_preview_result")
    page.wait_for_timeout(4000)
    end("13_preview_result")


if __name__ == "__main__":
    main()
