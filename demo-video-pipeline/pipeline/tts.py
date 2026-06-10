"""Text-to-speech abstraction with THREE selectable backends.

  synth_segment(text, out_wav, backend=..., **opts) -> path to a 24kHz-ish mono wav

Backends
--------
  polly         Amazon Polly (neural). Managed API, no AWS deployment beyond the
                synthesize-speech call. DEFAULT — the lowest-barrier path.
  qwen-speaker  Qwen3-TTS on a SageMaker async endpoint, a named English speaker
                (e.g. "Aiden") with an instruct style string.
  qwen-clone    Qwen3-TTS on the same endpoint, voice_clone from a short reference
                clip. You must pass ref_audio (+ the reference's TRUE ref_text).

The default backend is read from the TTS_BACKEND env var (default "polly") or the
`backend` argument. The two qwen-* backends require a deployed endpoint — see
sagemaker/deploy.py. All backends return a wav on disk; ffmpeg handles resampling.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_BACKEND = os.environ.get("TTS_BACKEND", "polly").lower()
POLLY_VOICE = os.environ.get("POLLY_VOICE", "Matthew")
POLLY_ENGINE = os.environ.get("POLLY_ENGINE", "neural")
QWEN_SPEAKER = os.environ.get("QWEN_SPEAKER", "Aiden")
QWEN_INSTRUCT = os.environ.get("QWEN_INSTRUCT", "calm, clear, professional narration")

_SAGEMAKER_DIR = Path(__file__).resolve().parent.parent / "sagemaker"

VALID_BACKENDS = ("polly", "qwen-speaker", "qwen-clone")


def _polly(text: str, out_wav: str) -> str:
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    polly = boto3.client("polly", region_name=region)
    mp3 = str(Path(out_wav).with_suffix(".mp3"))
    resp = polly.synthesize_speech(
        Text=f"<speak><p>{text}</p></speak>", TextType="ssml",
        OutputFormat="mp3", VoiceId=POLLY_VOICE, Engine=POLLY_ENGINE)
    with open(mp3, "wb") as f:
        f.write(resp["AudioStream"].read())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, out_wav], check=True)
    return out_wav


def _qwen_speaker(text: str, out_wav: str, **opts) -> str:
    sys.path.insert(0, str(_SAGEMAKER_DIR))
    from invoke_async import synth  # noqa: E402

    payload = {"mode": "custom_voice", "text": text, "language": "en",
               "speaker": opts.get("speaker", QWEN_SPEAKER),
               "instruct": opts.get("instruct", QWEN_INSTRUCT)}
    synth(payload, out_wav)
    return out_wav


def _qwen_clone(text: str, out_wav: str, **opts) -> str:
    sys.path.insert(0, str(_SAGEMAKER_DIR))
    from invoke_async import synth  # noqa: E402

    ref_audio = opts.get("ref_audio")
    if not ref_audio:
        raise ValueError("qwen-clone backend requires ref_audio (path | s3:// | https://)")
    ref_text = opts.get("ref_text", "")
    # A local file path is sent as base64; s3:// and https:// pass through unchanged.
    if os.path.exists(ref_audio):
        ref_audio = base64.b64encode(Path(ref_audio).read_bytes()).decode("utf-8")
    payload = {"mode": "voice_clone", "text": text, "language": "en",
               "ref_audio": ref_audio, "ref_text": ref_text}
    synth(payload, out_wav)
    return out_wav


def synth_segment(text: str, out_wav: str, backend: str | None = None, **opts) -> str:
    backend = (backend or DEFAULT_BACKEND).lower()
    Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
    if backend == "polly":
        return _polly(text, out_wav)
    if backend == "qwen-speaker":
        return _qwen_speaker(text, out_wav, **opts)
    if backend == "qwen-clone":
        return _qwen_clone(text, out_wav, **opts)
    raise ValueError(f"Unknown TTS backend {backend!r}; choose one of {VALID_BACKENDS}")


def duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())
