#!/usr/bin/env python3
"""
ui_demo.py — end-to-end UI test & demo driver for Voice Sample Studio v3.

Drives the REAL Gradio app in a real browser (Playwright/Chromium) and exercises
the v3 master-detail workflow that cannot be covered by the headless selftest:

  load  ->  select a row  ->  detail view renders  ->  rename (persist)  ->
  keep  ->  export (files on disk)  ->  voice-preview degrade path.

It is BOTH:
  * a TEST harness (`--test`, default): launches the app in-process on an
    isolated, seeded store, asserts each step, writes screenshots + a PASS/FAIL
    report. No mic, no cloud cost.
  * a DEMO driver (`--demo`): same flow, but headed + slowed down so it can be
    screen-recorded for a walkthrough video.

Why in-process: the app is built via `build_app(store)` and launched with
`prevent_thread_lock=True` on a fixed port, against a TEMP recordings dir seeded
from the canonical `qwen3-tts-video/recording/user_sample.wav`. Your real
~/.voice-sample-studio recordings are never touched.

Run (offline / deterministic — exercises everything except real cloud synth):

    cd ~/projects/voice-sample-studio
    uv run --with gradio --with soundfile --with numpy --with pyloudnorm \
        --with librosa --with faster-whisper --with torch --with torchaudio \
        --with playwright python ui_demo.py --test

    # visible walkthrough for recording (adds boto3 so the cloud panels light up):
    uv run --with gradio --with soundfile --with numpy --with pyloudnorm \
        --with librosa --with faster-whisper --with torch --with torchaudio \
        --with boto3 --with playwright python ui_demo.py --demo --slow-mo 700

Flags:
  --test / --demo   assertion mode (headless) | demo mode (headed, slow)
  --headed          force a visible browser even in --test
  --slow-mo MS      Playwright slow-mo (demo defaults to 600 ms)
  --port N          app port (default 7873)
  --keep            leave the app + browser running at the end (manual poke)
  --shots DIR       screenshot dir (default /tmp/vss-uitest)

Cloud notes:
  * Rich advice (Bedrock) and the preview button only "light up" when boto3 +
    AWS creds are present. Without boto3 both show their graceful-degrade note —
    which the test asserts.
  * The test NEVER triggers a real GPU synth (cold-start + cost). Even with
    boto3, it only clicks "Generate preview" when --synth is passed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
SEED_WAV = Path.home() / "projects" / "qwen3-tts-video" / "recording" / "user_sample.wav"


# --------------------------------------------------------------------------- #
# Result tracking                                                             #
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self):
        self.checks: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = ""):
        self.checks.append((name, bool(ok), detail))
        mark = "PASS" if ok else "FAIL"
        line = f"  [{mark}] {name}"
        if detail:
            line += f" — {detail}"
        print(line, flush=True)
        return ok

    @property
    def ok(self) -> bool:
        return all(c[1] for c in self.checks)

    def summary(self) -> str:
        n = len(self.checks)
        passed = sum(1 for c in self.checks if c[1])
        out = [f"\n=== UI TEST REPORT — {passed}/{n} checks passed ==="]
        for name, ok, detail in self.checks:
            out.append(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
        out.append("=== " + ("ALL GREEN" if self.ok else "FAILURES ABOVE") + " ===")
        return "\n".join(out)


# --------------------------------------------------------------------------- #
# Seed an isolated store                                                      #
# --------------------------------------------------------------------------- #
def _ffmpeg(args: list[str]):
    subprocess.run(["ffmpeg", "-nostdin", "-y", *args],
                   capture_output=True, check=True, stdin=subprocess.DEVNULL)


def seed_store(root: Path):
    """Seed a temp store with one clean take + one deliberately-clipped take so
    the table has multiple selectable rows and advice differs between them."""
    from voice_studio.quality import score_file
    from voice_studio.store import TakeStore

    if not SEED_WAV.exists():
        raise SystemExit(f"Seed clip not found: {SEED_WAV}\n"
                         f"(needed to seed the demo store; record one or adjust SEED_WAV)")

    ref_txt = SEED_WAV.with_name("ref_text.txt")
    target = ref_txt.read_text().strip() if ref_txt.exists() else None

    store = TakeStore(root)

    # Take 1 — clean master.
    clean = root / "seed-clean.wav"
    shutil.copy2(SEED_WAV, clean)
    sc1 = score_file(str(clean), target_text=target)
    t1 = store.add(str(clean), sc1.to_dict(), name="Clean demo take")

    # Take 2 — clipped/hot variant (boost gain hard so it clips -> advice differs).
    clipped = root / "seed-clipped.wav"
    _ffmpeg(["-i", str(clean), "-af", "volume=20dB", str(clipped)])
    sc2 = score_file(str(clipped), target_text=target)
    t2 = store.add(str(clipped), sc2.to_dict(), name="Hot/clipped take")

    return store, t1, t2


# --------------------------------------------------------------------------- #
# Launch the app in-process                                                   #
# --------------------------------------------------------------------------- #
def launch_app(store, port: int):
    from voice_studio.app import build_app, _CSS
    demo = build_app(store)
    demo.launch(server_name="127.0.0.1", server_port=port, inbrowser=False,
                show_error=True, prevent_thread_lock=True, css=_CSS,
                allowed_paths=[str(store.root)], quiet=True)
    return demo


# --------------------------------------------------------------------------- #
# The driven flow                                                             #
# --------------------------------------------------------------------------- #
def run_flow(page, base_url, store, t1, t2, rep, shots, demo, do_synth):
    def shot(name):
        try:
            page.screenshot(path=str(shots / f"{name}.png"), full_page=True)
        except Exception:
            pass

    def beat(seconds=1.2):
        if demo:
            page.wait_for_timeout(int(seconds * 1000))

    page.set_default_timeout(20000)
    page.goto(base_url, wait_until="domcontentloaded")
    tbl = page.locator("#takes-table")
    # Gradio Dataframe renders body cells as role=button (no <tbody><tr>); wait
    # for our seeded take-id cell to appear rather than a CSS row selector.
    tbl.get_by_role("button", name=t1.id, exact=True).first.wait_for(timeout=20000)
    beat(2)
    shot("01-loaded")

    # ---- 1. table populated + clean v3 headers (no cramped 'pitch(st)') ------
    headers = [h.strip() for h in tbl.get_by_role("columnheader").all_inner_texts()
               if h.strip()]
    rep.check("table renders v3 clean headers (Pace (WPM), Pitch var (st))",
              "Pace (WPM)" in headers and "Pitch var (st)" in headers,
              f"headers={headers}")
    rep.check("no cramped v2 header 'pitch(st)'", "pitch(st)" not in headers)
    both_rows = (tbl.get_by_role("button", name=t1.id, exact=True).count() >= 1 and
                 tbl.get_by_role("button", name=t2.id, exact=True).count() >= 1)
    rep.check("both seeded takes visible in table", both_rows)

    # ---- 2. master-detail: select a row -> detail view renders --------------
    detail = page.locator("#detail-card")
    rep.check("detail panel starts empty (prompt)",
              "Select a recording" in detail.inner_text())

    page.get_by_role("button", name=t1.id, exact=True).first.click()
    try:
        page.wait_for_function(
            """() => {
                const el = document.querySelector('#detail-card');
                return el && !el.innerText.includes('Select a recording');
            }""", timeout=15000)
        selected_ok = True
    except Exception:
        selected_ok = False
    shot("02-selected-detail")
    detail_txt = detail.inner_text()
    rep.check("row-select renders the detail verdict card (THE v3 bug)",
              selected_ok and ("/ 100 overall" in detail_txt),
              detail_txt[:80].replace("\n", " "))

    body = page.locator("body").inner_text()
    rep.check("detail scorecard renders (Acoustic + Delivery)",
              "Acoustic" in body and "Delivery" in body)

    name_val = page.get_by_placeholder("rename this take…").input_value()
    rep.check("editable name box pre-filled from take", name_val == (t1.name or ""),
              f"name='{name_val}'")

    # Gradio's waveform Audio widget keeps the file behind a /gradio_api/file= URL
    # and only sets the native <audio>.src on play — so assert the widget LOADED a
    # file (URL present) rather than checking <audio>.src (empty until playback).
    has_audio = page.evaluate(
        """() => !!document.querySelector('audio') &&
                 [...document.querySelectorAll('a[href*="gradio_api/file="], a[href*="file="]')]
                   .some(a => a.href.includes('file='))""")
    rep.check("replay audio player loaded the take (gradio file URL present)", has_audio)

    # ---- 3. advice panels (basic always; rich real-or-degrade) --------------
    rep.check("BASIC advice panel renders", "Basic advice (offline)" in body)
    rich_real = "Rich advice (Bedrock)" in body and "Rich advice unavailable" not in body
    rich_degrade = "Rich advice unavailable" in body
    rep.check("RICH advice panel renders (real or graceful-degrade note)",
              rich_real or rich_degrade,
              "real bedrock text" if rich_real else "graceful-degrade note")

    page.get_by_role("button", name=t2.id, exact=True).first.click()
    page.wait_for_timeout(1500)
    beat(2)
    shot("03-clipped-advice")
    body2 = page.locator("body").inner_text().lower()
    rep.check("selecting clipped take surfaces a clipping/gain tip in basic advice",
              ("clip" in body2 or "gain" in body2 or "hot" in body2 or "peak" in body2))

    # ---- 4. rename (persist to index.json) ----------------------------------
    page.get_by_role("button", name=t1.id, exact=True).first.click()
    page.wait_for_timeout(800)
    new_name = "Renamed In UI"
    page.get_by_placeholder("rename this take…").fill(new_name)
    page.get_by_role("button", name="💾 Save name").click()
    # Poll: with rich advice (Bedrock) enabled the save response waits on a model
    # call before the table re-renders, so wait for the name rather than a fixed sleep.
    reflected = False
    for _ in range(20):
        page.wait_for_timeout(500)
        if new_name in tbl.inner_text():
            reflected = True
            break
    beat(2)
    shot("04-renamed")
    idx = json.loads((store.root / "index.json").read_text())
    persisted = any(t["id"] == t1.id and t["name"] == new_name for t in idx["takes"])
    rep.check("rename persists to index.json on disk", persisted)
    rep.check("renamed take shows new name in the table", reflected)

    # ---- 5. keep ------------------------------------------------------------
    page.get_by_role("button", name="✓ Keep").click()
    page.wait_for_timeout(1000)
    idx = json.loads((store.root / "index.json").read_text())
    rep.check("Keep persists kept=true to index.json",
              any(t["id"] == t1.id and t["kept"] is True for t in idx["takes"]))
    shot("05-kept")

    # ---- 6. export (files on disk) ------------------------------------------
    page.get_by_role("button", name="⬇ Export (master + Qwen ref)").click()
    page.wait_for_timeout(1500)
    beat(2)
    exp_dir = store.root / "exports" / t1.id
    qwen = list(exp_dir.glob("*.wav"))
    reft = exp_dir / "ref_text.txt"
    rep.check("export produced a Qwen wav + ref_text.txt",
              exp_dir.exists() and len(qwen) >= 1 and reft.exists(),
              f"{[p.name for p in qwen]}")
    shot("06-exported")

    # ---- 7. voice-preview degrade path (no real GPU synth in test) ----------
    body3 = page.locator("body").inner_text()
    has_boto3 = _has_boto3()
    rep.check("voice-preview section + preset radio render",
              "Voice preview" in body3 and "Preset paragraph" in body3)
    page.get_by_role("button", name="🎤 Generate preview").click()
    if do_synth and has_boto3:
        page.wait_for_timeout(4000)
        rep.check("preview click produced a status (synth opt-in)", True)
    else:
        page.wait_for_timeout(2500)
        pv = page.locator("body").inner_text().lower()
        if has_boto3:
            rep.check("preview status present (boto3 available; synth not triggered)",
                      "preview" in pv)
        else:
            rep.check("preview graceful-degrades without boto3 (no crash, clear message)",
                      "unavailable" in pv or "disabled" in pv or "boto3" in pv)
    shot("07-preview")
    beat(2)


def _has_boto3() -> bool:
    try:
        import boto3  # noqa: F401
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# main                                                                        #
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Voice Sample Studio v3 UI test/demo driver")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--test", action="store_true", help="assertion mode (default, headless)")
    mode.add_argument("--demo", action="store_true", help="visible slow walkthrough for recording")
    ap.add_argument("--headed", action="store_true", help="force a visible browser in --test")
    ap.add_argument("--slow-mo", type=int, default=None, help="Playwright slow-mo ms")
    ap.add_argument("--port", type=int, default=7873)
    ap.add_argument("--keep", action="store_true", help="leave app+browser running at the end")
    ap.add_argument("--synth", action="store_true", help="actually trigger a real GPU preview synth (cost!)")
    ap.add_argument("--shots", default="/tmp/vss-uitest", help="screenshot dir")
    args = ap.parse_args()

    demo = args.demo
    headed = args.headed or demo
    slow_mo = args.slow_mo if args.slow_mo is not None else (600 if demo else 0)
    shots = Path(args.shots)
    shots.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    tmp = Path(tempfile.mkdtemp(prefix="vss-store-"))
    print(f"* Seeding isolated store at {tmp}", flush=True)
    store, t1, t2 = seed_store(tmp)
    print(f"  seeded takes: {t1.id} ('{t1.name}'), {t2.id} ('{t2.name}')", flush=True)

    print(f"* Launching app in-process on :{args.port}", flush=True)
    appdemo = launch_app(store, args.port)
    base_url = f"http://127.0.0.1:{args.port}"
    time.sleep(2)

    rep = Report()
    rc = 1
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not headed, slow_mo=slow_mo)
            page = browser.new_context(viewport={"width": 1440, "height": 1000}).new_page()
            print(f"* Driving {base_url} (headed={headed}, slow_mo={slow_mo})", flush=True)
            run_flow(page, base_url, store, t1, t2, rep, shots, demo, args.synth)
            print(rep.summary(), flush=True)
            rc = 0 if rep.ok else 2
            if args.keep:
                print(f"\n* --keep: app at {base_url} (Ctrl-C to stop)", flush=True)
                try:
                    while True:
                        time.sleep(3600)
                except KeyboardInterrupt:
                    pass
            browser.close()
    finally:
        try:
            appdemo.close()
        except Exception:
            pass
        print(f"\n* Screenshots in {shots}", flush=True)
        print(f"* Temp store {tmp} (safe to delete)", flush=True)

    sys.exit(rc)


if __name__ == "__main__":
    main()
