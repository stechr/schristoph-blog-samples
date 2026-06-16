"""
Perceptual MOS (Mean Opinion Score) prediction — LOCAL, CPU-only.

DEFAULT backend (v2): **TorchAudio-SQUIM (objective)** — a reference-free, non-intrusive
speech-quality model that estimates wideband PESQ (plus STOI / SI-SDR). PESQ is a
1.0-4.5 MOS-LQO quality scale, so we surface it directly as a MOS-style 1-5 quality
estimate. Licensing:
  * torch — BSD-3-Clause   (permissive)
  * torchaudio — BSD-2-Clause   (permissive)
  * SQUIM_OBJECTIVE model weights — Creative Commons Attribution 4.0 (CC-BY-4.0),
    permissive / commercial-OK with attribution.
  NOTE: we deliberately do NOT use SQUIM_SUBJECTIVE — its weights are CC-BY-NC-4.0
  (non-commercial), which fails the permissive-license policy.

Secondary hooks (used only if explicitly configured): NISQA / DNSMOS.

This module is a thin, graceful-degrade HOOK: if no backend is available it returns
(None, "unavailable") so the rest of the scorer keeps working with objective +
prosody metrics only — a flaky/large model download never blocks the app.

Reference: Kumar et al., "TorchAudio-Squim: Reference-less Speech Quality and
Intelligibility measures in TorchAudio", ICASSP 2023.
"""
from __future__ import annotations

import os
import tempfile
import wave
from pathlib import Path

import numpy as np

from .audio_io import AudioData

_SQUIM_MODEL = None  # cached across takes (loading is the slow part)


def _write_temp_wav(audio: AudioData, sr: int = 16000) -> str:
    """Write a mono 16 kHz 16-bit wav (what most MOS models expect)."""
    import shutil
    import subprocess

    s = np.clip(audio.samples, -1, 1)
    fd, raw_path = tempfile.mkstemp(suffix="_orig.wav")
    os.close(fd)
    with wave.open(raw_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(audio.sample_rate)
        w.writeframes((s * 32767).astype("<i2").tobytes())
    if audio.sample_rate == sr or not shutil.which("ffmpeg"):
        return raw_path
    out_path = raw_path.replace("_orig.wav", f"_{sr}.wav")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", raw_path, "-ar", str(sr), "-ac", "1", out_path],
                   capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    try:
        os.unlink(raw_path)
    except OSError:
        pass
    return out_path


def _predict_squim(audio: AudioData):
    """TorchAudio-SQUIM objective PESQ estimate -> MOS-style 1-5. Reference-free."""
    global _SQUIM_MODEL
    try:
        import torch  # type: ignore
        import torchaudio  # type: ignore
    except Exception:
        return None
    try:
        s = audio.samples.astype(np.float32)
        sr = audio.sample_rate
        if sr != 16000:
            # resample to 16 kHz (SQUIM expects 16 kHz)
            wav = torch.from_numpy(s).unsqueeze(0)
            wav = torchaudio.functional.resample(wav, sr, 16000)
        else:
            wav = torch.from_numpy(s).unsqueeze(0)
        # SQUIM works on short windows; cap to ~15 s for speed/stability.
        max_len = 16000 * 15
        if wav.shape[-1] > max_len:
            wav = wav[..., :max_len]
        if _SQUIM_MODEL is None:
            _SQUIM_MODEL = torchaudio.pipelines.SQUIM_OBJECTIVE.get_model()
        with torch.no_grad():
            stoi, pesq, si_sdr = _SQUIM_MODEL(wav)
        pesq_val = float(pesq.item() if hasattr(pesq, "item") else np.ravel(pesq)[0])
        # PESQ (wideband) ~1.0-4.5 maps directly onto a MOS-style quality scale.
        return max(1.0, min(5.0, pesq_val))
    except Exception:
        return None


def _predict_nisqa(audio: AudioData):
    try:
        from nisqa.NISQA_model import nisqaModel  # type: ignore
    except Exception:
        return None
    try:
        wav = _write_temp_wav(audio, 48000)
        weights = os.environ.get("VOICE_STUDIO_NISQA_WEIGHTS", "weights/nisqa.tar")
        args = {"mode": "predict_file", "pretrained_model": weights, "deg": wav,
                "ms_channel": None, "output_dir": tempfile.gettempdir()}
        model = nisqaModel(args)
        out = model.predict()
        return float(out["mos_pred"].iloc[0])
    except Exception:
        return None


def _predict_dnsmos(audio: AudioData):
    try:
        import onnxruntime as ort  # type: ignore
    except Exception:
        return None
    model_dir = os.environ.get("VOICE_STUDIO_DNSMOS_DIR", "")
    sig = Path(model_dir) / "sig.onnx"
    if not model_dir or not sig.exists():
        return None
    try:
        wav = _write_temp_wav(audio, 16000)
        with wave.open(wav, "rb") as w:
            raw = w.readframes(w.getnframes())
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32767.0
        sess = ort.InferenceSession(str(sig))
        inp = sess.get_inputs()[0]
        feed = {inp.name: samples[: inp.shape[-1]].reshape(1, -1).astype(np.float32)}
        res = sess.run(None, feed)
        return float(np.ravel(res[0])[0])
    except Exception:
        return None


def predict_mos(audio: AudioData):
    """
    Return (mos_value_or_None, backend_name).

    Order: TorchAudio-SQUIM objective (default, permissive) -> NISQA -> DNSMOS ->
    (None, "unavailable"). Set VOICE_STUDIO_DISABLE_MOS=1 to skip entirely.
    """
    if os.environ.get("VOICE_STUDIO_DISABLE_MOS"):
        return None, "disabled"
    val = _predict_squim(audio)
    if val is not None:
        return val, "torchaudio-squim-objective (PESQ→MOS, CC-BY-4.0)"
    val = _predict_nisqa(audio)
    if val is not None:
        return val, "nisqa"
    val = _predict_dnsmos(audio)
    if val is not None:
        return val, "dnsmos"
    return None, "unavailable"
