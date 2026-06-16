"""
Audio I/O helpers — decode any wav/audio file to a mono float32 numpy array,
without hard-depending on a single backend. Prefers `soundfile`; falls back to
decoding via the `ffmpeg` binary (always present in this environment).

All higher-level scoring works on float32 samples in [-1, 1] plus the original
sample rate / channel count, so the quality engine never needs to know which
backend loaded the file.
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class AudioData:
    samples: np.ndarray  # mono float32 in [-1, 1]
    sample_rate: int
    channels: int  # original channel count (before downmix)
    n_frames: int  # original frames per channel
    bits_per_sample: int | None = None

    @property
    def duration(self) -> float:
        return self.n_frames / self.sample_rate if self.sample_rate else 0.0


def _ffprobe_stream(path: str) -> dict:
    """Return sample_rate / channels / bits / duration via ffprobe (best effort)."""
    if not shutil.which("ffprobe"):
        return {}
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries",
                "stream=sample_rate,channels,bits_per_raw_sample,bits_per_sample:format=duration",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
        )
        data = json.loads(out.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}
        bits = stream.get("bits_per_raw_sample") or stream.get("bits_per_sample")
        return {
            "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
            "channels": int(stream["channels"]) if stream.get("channels") else None,
            "bits_per_sample": int(bits) if bits and str(bits).isdigit() and int(bits) > 0 else None,
            "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        }
    except Exception:
        return {}


def _load_with_soundfile(path: str):
    try:
        import soundfile as sf  # type: ignore
    except Exception:
        return None
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        channels = data.shape[1]
        n_frames = data.shape[0]
        mono = data.mean(axis=1).astype(np.float32)
        info = sf.info(path)
        bits = None
        subtype = (info.subtype or "").upper()
        for tag, b in (("PCM_16", 16), ("PCM_24", 24), ("PCM_32", 32), ("FLOAT", 32), ("PCM_S8", 8)):
            if tag in subtype:
                bits = b
                break
        return AudioData(mono, int(sr), int(channels), int(n_frames), bits)
    except Exception:
        return None


def _load_via_ffmpeg(path: str) -> AudioData:
    """Decode to a temp 32-bit float mono wav and parse it. Always-available fallback."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Neither soundfile nor ffmpeg available to decode audio.")
    meta = _ffprobe_stream(path)
    orig_sr = meta.get("sample_rate") or 0
    with tempfile.TemporaryDirectory() as td:
        tmp = str(Path(td) / "decoded.wav")
        sr = orig_sr or 48000
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-i", path, "-ac", "1", "-ar", str(sr),
             "-c:a", "pcm_f32le", tmp],
            capture_output=True, check=True, timeout=120, stdin=subprocess.DEVNULL,
        )
        with wave.open(tmp, "rb") as w:
            n = w.getnframes()
            raw = w.readframes(n)
        arr = np.frombuffer(raw, dtype="<f4").astype(np.float32)
    return AudioData(
        samples=arr,
        sample_rate=orig_sr or sr,
        channels=meta.get("channels") or 1,
        n_frames=meta.get("channels") and (len(arr)) or len(arr),
        bits_per_sample=meta.get("bits_per_sample"),
    )


def load_audio(path: str | Path) -> AudioData:
    """Load any audio file to mono float32. Tries soundfile, then ffmpeg."""
    p = str(path)
    if not Path(p).exists():
        raise FileNotFoundError(p)
    audio = _load_with_soundfile(p)
    if audio is None:
        audio = _load_via_ffmpeg(p)
    # Enrich missing bit depth from ffprobe if needed.
    if audio.bits_per_sample is None:
        audio.bits_per_sample = _ffprobe_stream(p).get("bits_per_sample")
    return audio
