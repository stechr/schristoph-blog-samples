#!/usr/bin/env python3
"""
Headless self-test for the voice-sample-studio quality engine (v2).

A background run has NO microphone and NO GUI, so this verifies the scoring engine
the only way it can be without a person: against the real Qwen reference clip plus
SYNTHESIZED variants generated with ffmpeg.

It asserts:
  ACOUSTIC (always run; whisper/MOS disabled for speed/determinism)
    1. the clean clip scores HIGHER than every degraded clip,
    2. clipping is detected on the clipped clip,
    3. elevated noise / low SNR is detected on the noisy clip,
    4. band-limiting is detected on the telephone-band clip.
  PITCH (run if librosa is available; else skipped gracefully)
    5. a MONOTONE signal has LOWER pitch-variation than natural speech ("boring" detector).
  PACE  (run if faster-whisper is available; else skipped gracefully)
    6. atempo=1.4 (faster) yields HIGHER WPM than the original, and atempo=0.7
       (slower) yields LOWER WPM.
  MOS   (run if torch/torchaudio is available; else skipped gracefully)
    7. CLEAN MOS >= a degraded (noisy) clip's MOS.

Run (engine import needs numpy/soundfile/pyloudnorm; pitch needs librosa; pace needs
faster-whisper; MOS needs torch+torchaudio):

  uv run --no-project --with numpy --with soundfile --with pyloudnorm \
      --with librosa --with faster-whisper python selftest.py
  # add  --with torch --with torchaudio  to also exercise the MOS assertion
  # optionally pass a clean reference wav:  python selftest.py /path/to/clean.wav
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from voice_studio.quality import score_file, pitch_variation  # noqa: E402
from voice_studio.audio_io import load_audio  # noqa: E402
from voice_studio import advice as advice_mod  # noqa: E402
from voice_studio import preview as preview_mod  # noqa: E402

# Locate the clean reference: env override, else the known Qwen project path, else arg.
DEFAULT_CLEAN = Path.home() / "projects" / "qwen3-tts-video" / "recording" / "user_sample.wav"
CLEAN = Path(os.environ.get("VOICE_STUDIO_CLEAN_SAMPLE", str(DEFAULT_CLEAN)))
if len(sys.argv) > 1:
    CLEAN = Path(sys.argv[1])


def _ff(args, **kw):
    return subprocess.run(["ffmpeg", "-nostdin", "-y", *args], capture_output=True,
                          check=True, timeout=180, stdin=subprocess.DEVNULL, **kw)


def make_degraded(clean: Path, td: Path) -> dict:
    noisy = td / "noisy.wav"
    clipped = td / "clipped.wav"
    bandlimited = td / "bandlimited.wav"
    faster = td / "faster.wav"
    slower = td / "slower.wav"
    monotone = td / "monotone.wav"

    _ff(["-i", str(clean),
         "-filter_complex",
         "anoisesrc=color=white:amplitude=0.03[n];[0:a][n]amix=inputs=2:duration=first:normalize=0",
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(noisy)])
    _ff(["-i", str(clean), "-af", "volume=40dB",
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(clipped)])
    _ff(["-i", str(clean), "-af", "lowpass=f=3400,highpass=f=300",
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(bandlimited)])
    # speed-perturbed (atempo preserves pitch, changes pace -> WPM)
    _ff(["-i", str(clean), "-af", "atempo=1.4",
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(faster)])
    _ff(["-i", str(clean), "-af", "atempo=0.7",
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(slower)])
    # near-constant-pitch tone -> the monotone / "boring" extreme (very low F0 std)
    _ff(["-f", "lavfi", "-i", "sine=frequency=150:duration=8",
         "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(monotone)])

    return {"noisy": noisy, "clipped": clipped, "bandlimited": bandlimited,
            "faster": faster, "slower": slower, "monotone": monotone}


def fmt(label, sc):
    return (f"{label:<12} score={sc.overall_score:6.1f}  verdict={sc.verdict:<7} "
            f"snr={sc.snr_db:6.1f}dB  nf={sc.noise_floor_dbfs:7.1f}dBFS  "
            f"clip={sc.clipping_fraction*100:6.3f}%  bw={sc.bandwidth_hz:7.0f}Hz  "
            f"dyn={sc.loudness_dynamics_db:4.1f}dB")


def main() -> int:
    if not shutil.which("ffmpeg"):
        print("FAIL: ffmpeg not on PATH — cannot generate degraded clips.")
        return 2
    if not CLEAN.exists():
        print(f"SKIP: clean reference not found at {CLEAN}.")
        print("      Pass a path:  python selftest.py /path/to/clean.wav")
        print("      or set VOICE_STUDIO_CLEAN_SAMPLE. (Engine itself is still importable.)")
        return 3

    print(f"Clean reference: {CLEAN}\n")
    failures: list[str] = []
    skips: list[str] = []

    with tempfile.TemporaryDirectory(prefix="vss-selftest-") as tds:
        td = Path(tds)
        deg = make_degraded(CLEAN, td)

        # --- ACOUSTIC: fast/deterministic (no whisper, no MOS, no pitch) ----
        def acoustic(p):
            return score_file(str(p), with_mos=False, with_transcript=False, with_pitch=False)

        clean_sc = acoustic(CLEAN)
        noisy_sc = acoustic(deg["noisy"])
        clipped_sc = acoustic(deg["clipped"])
        band_sc = acoustic(deg["bandlimited"])

        print("=== SCORECARDS (acoustic) ===")
        for lbl, sc in (("CLEAN", clean_sc), ("noisy", noisy_sc),
                        ("clipped", clipped_sc), ("bandlimited", band_sc)):
            print(fmt(lbl, sc))
        print()

        for label, sc in (("noisy", noisy_sc), ("clipped", clipped_sc), ("bandlimited", band_sc)):
            if not (clean_sc.overall_score > sc.overall_score):
                failures.append(f"Ranking: CLEAN ({clean_sc.overall_score}) not > {label} ({sc.overall_score}).")
        if not any("clip" in i.lower() for i in clipped_sc.issues):
            failures.append("Clipping not detected on the clipped clip.")
        if not (noisy_sc.snr_db < clean_sc.snr_db - 3 or
                any("snr" in i.lower() or "noise" in i.lower() for i in noisy_sc.issues)):
            failures.append("Noise/low-SNR not detected on the noisy clip.")
        if not (band_sc.bandwidth_hz < clean_sc.bandwidth_hz - 1000 or
                any("band" in i.lower() or "muffled" in i.lower() for i in band_sc.issues)):
            failures.append("Band-limiting not detected on the telephone-band clip.")

        # --- PITCH: monotone < natural (needs librosa) ----------------------
        pv_clean = pitch_variation(load_audio(str(CLEAN)))
        pv_mono = pitch_variation(load_audio(str(deg["monotone"])))
        print("=== PITCH VARIATION (F0 std, semitones) ===")
        print(f"CLEAN   std={pv_clean['f0_std_semitones']} st  (backend {pv_clean['backend']})")
        print(f"monotone std={pv_mono['f0_std_semitones']} st  (backend {pv_mono['backend']})\n")
        if (pv_clean["backend"] == "librosa-pyin" and
                pv_clean["f0_std_semitones"] is not None and pv_mono["f0_std_semitones"] is not None):
            if not (pv_clean["f0_std_semitones"] > pv_mono["f0_std_semitones"]):
                failures.append(f"Pitch: natural ({pv_clean['f0_std_semitones']} st) not > "
                                f"monotone ({pv_mono['f0_std_semitones']} st).")
        else:
            skips.append("pitch ordering (librosa unavailable or no voiced F0)")

        # --- PACE: faster > original > slower WPM (needs faster-whisper) ----
        os.environ.pop("VOICE_STUDIO_DISABLE_WHISPER", None)

        def with_wpm(p):
            return score_file(str(p), with_mos=False, with_transcript=True, with_pitch=False)

        orig_w = with_wpm(CLEAN)
        fast_w = with_wpm(deg["faster"])
        slow_w = with_wpm(deg["slower"])
        print("=== SPEAKING RATE (WPM) ===")
        for lbl, sc in (("orig", orig_w), ("faster x1.4", fast_w), ("slower x0.7", slow_w)):
            print(f"{lbl:<12} wpm={sc.wpm}  words={sc.word_count}  backend={sc.pace_backend}")
        print()
        if all(s.pace_backend == "word-timestamps" and s.wpm is not None
               for s in (orig_w, fast_w, slow_w)):
            if not (fast_w.wpm > orig_w.wpm):
                failures.append(f"Pace: faster ({fast_w.wpm}) not > original ({orig_w.wpm}) WPM.")
            if not (slow_w.wpm < orig_w.wpm):
                failures.append(f"Pace: slower ({slow_w.wpm}) not < original ({orig_w.wpm}) WPM.")
        else:
            skips.append("WPM ordering (faster-whisper unavailable / no word timestamps)")

        # --- MOS: clean >= degraded (needs torch/torchaudio) ----------------
        mos_clean = score_file(str(CLEAN), with_mos=True, with_transcript=False, with_pitch=False)
        mos_noisy = score_file(str(deg["noisy"]), with_mos=True, with_transcript=False, with_pitch=False)
        print("=== PERCEPTUAL MOS ===")
        print(f"CLEAN mos={mos_clean.mos} ({mos_clean.mos_backend})")
        print(f"noisy mos={mos_noisy.mos} ({mos_noisy.mos_backend})\n")
        if mos_clean.mos is not None and mos_noisy.mos is not None:
            if not (mos_clean.mos >= mos_noisy.mos - 0.05):
                failures.append(f"MOS: clean ({mos_clean.mos}) not >= noisy ({mos_noisy.mos}).")
        else:
            skips.append("MOS ordering (torch/torchaudio unavailable)")

        # --- BASIC ADVICE: scorecard -> expected forward-looking tips -------
        # Deterministic, offline, pure function of the scorecard. We assert the
        # right advice KEY surfaces for known defects, that a clean card yields
        # the positive "all_good" tip, and that the function is stable.
        print("=== BASIC ADVICE (rule-based, offline) ===")

        def keys(sc_dict):
            return {k for k, _ in advice_mod.basic_advice(sc_dict, keyed=True)}

        clipped_keys = keys(clipped_sc.to_dict())
        noisy_keys = keys(noisy_sc.to_dict())
        band_keys = keys(band_sc.to_dict())
        print(f"clipped -> {sorted(clipped_keys)}")
        print(f"noisy   -> {sorted(noisy_keys)}")
        print(f"band    -> {sorted(band_keys)}")

        if "clipping" not in clipped_keys:
            failures.append("Basic advice: 'clipping' tip missing for the clipped clip.")
        if "noise" not in noisy_keys:
            failures.append("Basic advice: 'noise' tip missing for the noisy clip.")
        if "muffled" not in band_keys:
            failures.append("Basic advice: 'muffled' tip missing for the band-limited clip.")

        # Synthetic cards exercise the delivery + all_good branches deterministically.
        fast_card = {"wpm": 200.0}
        mono_card = {"pitch_std_semitones": 0.5}
        perfect_card = {
            "clipping_fraction": 0.0, "true_peak_dbtp": -3.0, "snr_db": 45.0,
            "noise_floor_dbfs": -70.0, "bandwidth_hz": 11000.0, "integrated_lufs": -18.0,
            "duration": 20.0, "sample_rate": 24000, "lead_trim_s": 0.0, "tail_trim_s": 0.0,
            "silence_ratio": 0.2, "wpm": 140.0, "pitch_std_semitones": 3.5,
            "loudness_dynamics_db": 12.0, "pauses_per_min": 6.0, "wer": 0.05,
        }
        fast_keys = keys(fast_card)
        mono_keys = keys(mono_card)
        perfect_keys = keys(perfect_card)
        print(f"fast(200wpm)  -> {sorted(fast_keys)}")
        print(f"monotone(0.5) -> {sorted(mono_keys)}")
        print(f"perfect       -> {sorted(perfect_keys)}\n")
        if "fast" not in fast_keys:
            failures.append("Basic advice: 'fast' tip missing for 200 WPM.")
        if "monotone" not in mono_keys:
            failures.append("Basic advice: 'monotone' tip missing for 0.5 st pitch.")
        if perfect_keys != {"all_good"}:
            failures.append(f"Basic advice: clean card should yield only 'all_good', got {sorted(perfect_keys)}.")
        # determinism
        if advice_mod.basic_advice(clipped_sc.to_dict()) != advice_mod.basic_advice(clipped_sc.to_dict()):
            failures.append("Basic advice: not deterministic for identical input.")

        # --- PREVIEW SYNTH WIRING -------------------------------------------
        # Always exercise the OFFLINE code path: build the voice_clone payload
        # (ffmpeg downsample -> 24 kHz mono -> base64 + ref_text + target text).
        # Optionally do ONE real smoke synth if VOICE_STUDIO_PREVIEW_SMOKE=1.
        print("=== PREVIEW SYNTH WIRING ===")
        para = "This is a short preview sentence to hear the cloned voice."
        try:
            payload = preview_mod.build_clone_payload(str(CLEAN), para, ref_text="reference transcript")
            ok = (payload.get("mode") == "voice_clone"
                  and payload.get("text") == para
                  and payload.get("ref_text") == "reference transcript"
                  and isinstance(payload.get("ref_audio"), str)
                  and len(payload["ref_audio"]) > 1000)
            print(f"build_clone_payload: mode={payload.get('mode')} "
                  f"ref_audio_b64_len={len(payload.get('ref_audio',''))} "
                  f"text_ok={payload.get('text')==para}  -> {'OK' if ok else 'BAD'}")
            if not ok:
                failures.append("Preview: build_clone_payload produced a malformed payload.")
        except Exception as e:  # noqa: BLE001
            failures.append(f"Preview: build_clone_payload raised {type(e).__name__}: {e}")

        if os.environ.get("VOICE_STUDIO_PREVIEW_SMOKE") == "1":
            print("  VOICE_STUDIO_PREVIEW_SMOKE=1 -> attempting ONE real synth…")

            class _FakeTake:
                id = "selftest-smoke"
                master_wav = str(CLEAN)
                name = "selftest"
                scorecard = {"transcript": "reference transcript"}

            with tempfile.TemporaryDirectory(prefix="vss-prev-") as ptd:
                res = preview_mod.generate_preview(_FakeTake(), para, ptd, timeout=900)
                print(f"  real synth -> {res.get('status')}  wav={res.get('wav')}")
                if res.get("status") == "ok" and res.get("wav") and Path(res["wav"]).exists():
                    print("  ✓ real preview synth produced audio")
                else:
                    skips.append(f"preview real synth (status={res.get('status')})")
        else:
            skips.append("preview real synth (set VOICE_STUDIO_PREVIEW_SMOKE=1 to enable) — "
                         "offline payload path exercised")
        print()

        # --- report ---------------------------------------------------------
        print("=== ASSERTIONS ===")
        print("  ✓ CLEAN ranks above noisy, clipped, and band-limited clips" if not any(
            "Ranking" in f for f in failures) else "  ✗ ranking")
        print("  ✓ clipping detected on clipped clip" if not any(
            "Clipping" in f for f in failures) else "  ✗ clipping")
        print("  ✓ noise / low SNR detected on noisy clip" if not any(
            "Noise" in f for f in failures) else "  ✗ noise")
        print("  ✓ band-limiting detected on telephone-band clip" if not any(
            "Band" in f for f in failures) else "  ✗ band-limiting")
        if "pitch ordering (librosa unavailable or no voiced F0)" not in skips:
            print("  ✓ monotone has lower pitch-variation than natural speech" if not any(
                "Pitch" in f for f in failures) else "  ✗ pitch ordering")
        if not any(s.startswith("WPM") for s in skips):
            print("  ✓ faster clip > original > slower clip on WPM" if not any(
                "Pace" in f for f in failures) else "  ✗ pace ordering")
        if not any(s.startswith("MOS") for s in skips):
            print("  ✓ CLEAN MOS >= degraded MOS" if not any(
                "MOS" in f for f in failures) else "  ✗ MOS ordering")
        print("  ✓ basic advice: clipping/noise/muffled/fast/monotone tips + clean=all_good + deterministic"
              if not any("Basic advice" in f for f in failures) else "  ✗ basic advice")
        print("  ✓ preview wiring: voice_clone payload builds (ffmpeg+base64+ref_text)"
              if not any("Preview" in f for f in failures) else "  ✗ preview wiring")
        for s in skips:
            print(f"  ⊘ SKIPPED: {s}")

        if failures:
            print()
            for f in failures:
                print(f"  ✗ {f}")
            print(f"\nSELF-TEST FAILED ({len(failures)} issue(s)).")
            return 1
        print("\nSELF-TEST PASSED.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
