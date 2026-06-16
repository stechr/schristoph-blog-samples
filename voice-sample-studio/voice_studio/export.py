"""
Export module — produces, per kept take, BOTH:
  1. the full-quality master WAV (kept as recorded), and
  2. a Qwen-ready 24 kHz MONO WAV + a ref_text.txt stub, matching the
     `qwen3-tts-video/recording/` layout so the clip drops straight into the
     voice_clone path.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

QWEN_SAMPLE_RATE = 24000  # matches qwen3-tts-video/recording/user_sample.wav
QWEN_CHANNELS = 1


def export_qwen_reference(master_wav: str | Path, out_dir: str | Path,
                          ref_text: str = "", basename: str = "user_sample") -> dict:
    """
    Convert a master WAV to a 24 kHz mono Qwen reference clip and write the paired
    ref_text.txt. Returns paths. Uses ffmpeg for the resample/downmix.
    """
    master_wav = Path(master_wav)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_out = out_dir / f"{basename}.wav"
    txt_out = out_dir / "ref_text.txt"

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg required for Qwen export.")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-i", str(master_wav),
         "-ar", str(QWEN_SAMPLE_RATE), "-ac", str(QWEN_CHANNELS),
         "-c:a", "pcm_s16le", str(wav_out)],
        capture_output=True, check=True, timeout=120, stdin=subprocess.DEVNULL,
    )
    txt_out.write_text((ref_text or "").strip() + "\n", encoding="utf-8")
    return {
        "qwen_wav": str(wav_out),
        "ref_text": str(txt_out),
        "sample_rate": QWEN_SAMPLE_RATE,
        "channels": QWEN_CHANNELS,
    }


def export_master(src_wav: str | Path, out_dir: str | Path, basename: str) -> str:
    """Copy the full-quality master WAV unchanged into the export dir."""
    src_wav = Path(src_wav)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{basename}_master.wav"
    shutil.copy2(src_wav, dst)
    return str(dst)


def export_take(master_wav: str | Path, out_dir: str | Path, ref_text: str = "",
                basename: str = "user_sample") -> dict:
    """Dual export: master copy + Qwen-ready 24 kHz mono + ref_text."""
    master = export_master(master_wav, out_dir, basename)
    qwen = export_qwen_reference(master_wav, out_dir, ref_text=ref_text, basename=basename)
    return {"master": master, **qwen}
