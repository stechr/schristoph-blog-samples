"""
Local speech-to-text for auto-filling ref_text.txt, computing WER, and providing
WORD-LEVEL TIMESTAMPS used by the pace (WPM) and pause-profile metrics.

Preferred: faster-whisper (CTranslate2, MIT, fast on CPU). Fallback: openai-whisper.
If neither is installed, returns ("", [], "unavailable") — the take is still scored on
objective + pitch/dynamics metrics, and the user fills ref_text manually.

Enable with:
    uv pip install faster-whisper        # recommended (CPU friendly, MIT)
    # or
    uv pip install openai-whisper
Model size is configurable via VOICE_STUDIO_WHISPER_MODEL (default "base").
"""
from __future__ import annotations

import os
import re
import tempfile
import wave

import numpy as np

from .audio_io import AudioData

_MODEL = os.environ.get("VOICE_STUDIO_WHISPER_MODEL", "base")

# Placeholder token used in the default script; ignored for WER so it never
# inflates the error when the user has not replaced it with their name.
NAME_PLACEHOLDER = "<name>"


def _to_wav16k(audio: AudioData) -> str:
    import shutil
    import subprocess

    s = np.clip(audio.samples, -1, 1)
    fd, raw = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with wave.open(raw, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(audio.sample_rate)
        w.writeframes((s * 32767).astype("<i2").tobytes())
    if audio.sample_rate == 16000 or not shutil.which("ffmpeg"):
        return raw
    out = raw.replace(".wav", "_16k.wav")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", raw, "-ar", "16000", "-ac", "1", out],
                   capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    return out if os.path.exists(out) else raw


def _faster_whisper(audio: AudioData):
    """Return (text, words) with word timestamps, or None if backend unavailable."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:
        return None
    try:
        wav = _to_wav16k(audio)
        model = WhisperModel(_MODEL, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(wav, language="en", word_timestamps=True)
        texts: list[str] = []
        words: list[dict] = []
        for seg in segments:
            texts.append(seg.text.strip())
            for w in (getattr(seg, "words", None) or []):
                if w.start is None or w.end is None:
                    continue
                words.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})
        return " ".join(texts).strip(), words
    except Exception:
        return None


def _openai_whisper(audio: AudioData):
    """Return (text, words) with word timestamps, or None if backend unavailable."""
    try:
        import whisper  # type: ignore
    except Exception:
        return None
    try:
        wav = _to_wav16k(audio)
        model = whisper.load_model(_MODEL)
        result = model.transcribe(wav, language="en", word_timestamps=True)
        text = (result.get("text") or "").strip()
        words: list[dict] = []
        for seg in result.get("segments", []) or []:
            for w in seg.get("words", []) or []:
                start, end = w.get("start"), w.get("end")
                if start is None or end is None:
                    continue
                words.append({"word": (w.get("word") or "").strip(),
                              "start": float(start), "end": float(end)})
        return text, words
    except Exception:
        return None


def transcribe_detailed(audio: AudioData):
    """
    Return (transcript, words, backend).

    `words` is a list of {"word", "start", "end"} dicts (empty if the backend
    cannot produce word timestamps). Empty transcript + 'unavailable' if no engine.
    """
    if os.environ.get("VOICE_STUDIO_DISABLE_WHISPER"):
        return "", [], "disabled"
    res = _faster_whisper(audio)
    if res is not None:
        return res[0], res[1], "faster-whisper"
    res = _openai_whisper(audio)
    if res is not None:
        return res[0], res[1], "openai-whisper"
    return "", [], "unavailable"


def transcribe_audio(audio: AudioData):
    """Back-compat wrapper: return (transcript, backend) only."""
    text, _words, backend = transcribe_detailed(audio)
    return text, backend


def _normalize(text: str, strip_name_placeholder: bool = False):
    if strip_name_placeholder:
        text = text.replace(NAME_PLACEHOLDER, " ")
    return re.sub(r"[^\w\s]", "", text.lower()).split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    """
    Standard Levenshtein-based WER between reference and hypothesis.

    The literal ``<name>`` placeholder is stripped from the reference before
    scoring so an un-filled template token does not inflate the error.
    """
    r = _normalize(reference, strip_name_placeholder=True)
    h = _normalize(hypothesis)
    if not r:
        return 0.0 if not h else 1.0
    # DP edit distance over words
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=np.int32)
    d[:, 0] = np.arange(len(r) + 1)
    d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)
    return float(d[len(r), len(h)]) / len(r)
