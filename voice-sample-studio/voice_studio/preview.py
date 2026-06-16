"""
Voice-preview synthesis — listen to a take's cloned voice on sample text.

Given a recorded take (its OWN master WAV as the reference + its transcript as
ref_text), synthesize a chosen/typed paragraph IN THAT VOICE via the Qwen3-TTS
`voice_clone` path, so the user can hear how the clone will sound before
committing the take.

Design:
  * The reference clip is the take's own WAV, downsampled to 24 kHz mono (Qwen's
    reference rate) and sent inline as base64 — no S3 upload needed.
  * ref_text is the take's true transcript (the ICL path needs the EXACT text;
    a wrong ref_text makes generation run over-long / time out).
  * The actual SageMaker call is delegated to the existing
    `qwen3-tts-video/sagemaker/invoke_async.py::synth` (single source of truth
    for the endpoint/bucket wiring).
  * GRACEFUL DEGRADE: if boto3 / creds / the endpoint are unavailable, the app
    disables the button with a clear message; nothing here raises to the UI.

Previews are saved under
  <recordings_root>/exports/<take-id>/previews/<slug>.wav
which is gitignored (exports/ + *.wav).
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

QWEN_SAMPLE_RATE = 24000
QWEN_CHANNELS = 1


# --------------------------------------------------------------------------- #
# Preset sample paragraphs (drafted; ~2-3 sentences each).                     #
# --------------------------------------------------------------------------- #
PRESET_PARAGRAPHS: list[dict] = [
    {
        "key": "technical",
        "label": "Technical",
        "text": (
            "In this walkthrough we deploy the model behind an asynchronous "
            "endpoint, so requests queue instead of timing out under load. "
            "We then stream the results back to the client and cache the "
            "embeddings for reuse. The whole pipeline runs in a single region."
        ),
    },
    {
        "key": "narrative",
        "label": "Narrative",
        "text": (
            "The morning fog rolled off the harbor as the first boats slipped "
            "out to sea. She watched from the pier, coffee in hand, and felt the "
            "quiet pull of a day that had not yet decided what it would become."
        ),
    },
    {
        "key": "conversational",
        "label": "Conversational",
        "text": (
            "Honestly, I wasn't sure this would work at first. But once you get "
            "the hang of it, it's actually pretty fun — you just hit record, read "
            "the script, and let the tool tell you how you did. Give it a try!"
        ),
    },
]


def preset_choices() -> list[str]:
    """Radio labels for the UI (preset labels + a free-text sentinel)."""
    return [p["label"] for p in PRESET_PARAGRAPHS]


def preset_text(label: str) -> str:
    for p in PRESET_PARAGRAPHS:
        if p["label"] == label or p["key"] == label:
            return p["text"]
    return ""


def _slugify(text: str, fallback: str = "preview") -> str:
    words = re.sub(r"[^\w\s-]+", "", (text or "").strip().lower()).split()
    slug = "-".join(words[:6]).strip("-")
    return slug[:48] or fallback


# --------------------------------------------------------------------------- #
# Qwen wiring resolution (no hardcoded user path).                            #
# --------------------------------------------------------------------------- #
def _qwen_sagemaker_dir() -> Path:
    env = os.environ.get("QWEN_TTS_DIR")
    base = Path(env).expanduser() if env else (Path.home() / "projects" / "qwen3-tts-video")
    return base / "sagemaker"


def _import_synth():
    """Import `synth` from the qwen3-tts-video invoke_async module (lazy)."""
    sm = _qwen_sagemaker_dir()
    if not (sm / "invoke_async.py").exists():
        raise FileNotFoundError(f"qwen invoke_async.py not found under {sm} "
                                f"(set QWEN_TTS_DIR to the qwen3-tts-video checkout).")
    if str(sm) not in sys.path:
        sys.path.insert(0, str(sm))
    import invoke_async  # type: ignore
    return invoke_async.synth


def _downsample_to_qwen_ref(master_wav: str | Path) -> str:
    """ffmpeg-convert the master WAV to a temp 24 kHz mono WAV; return its path."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg required to prepare the reference clip.")
    fd, tmp = tempfile.mkstemp(prefix="vss-ref-", suffix=".wav")
    os.close(fd)
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-i", str(master_wav),
         "-ar", str(QWEN_SAMPLE_RATE), "-ac", str(QWEN_CHANNELS),
         "-c:a", "pcm_s16le", tmp],
        capture_output=True, check=True, timeout=120, stdin=subprocess.DEVNULL,
    )
    return tmp


def build_clone_payload(master_wav: str | Path, paragraph: str, ref_text: str,
                        language: str = "en") -> dict:
    """
    Build the Qwen voice_clone payload from a take.

    Pure-ish (needs ffmpeg) and AWS-free, so it is unit-testable as the preview
    "code path" without invoking SageMaker. The take's own WAV becomes the
    base64 ref_audio (24 kHz mono); its transcript is ref_text; the chosen
    paragraph is the target text.
    """
    ref_wav = _downsample_to_qwen_ref(master_wav)
    try:
        b64 = base64.b64encode(Path(ref_wav).read_bytes()).decode("ascii")
    finally:
        try:
            os.remove(ref_wav)
        except OSError:
            pass
    return {
        "mode": "voice_clone",
        "text": (paragraph or "").strip(),
        "language": language,
        "ref_audio": b64,
        "ref_text": (ref_text or "").strip(),
    }


def endpoint_status() -> dict:
    """
    Best-effort check of the Qwen async endpoint. Never raises.

    Returns {available, in_service, instances, message}.
    `available` is True when the endpoint is InService (it can still be scaled to
    zero, in which case the first synth cold-starts ~5-10 min).
    """
    try:
        import boto3
    except Exception as e:  # noqa: BLE001
        return {"available": False, "in_service": False, "instances": 0,
                "message": f"boto3 not installed ({type(e).__name__}) — preview disabled."}
    try:
        import json
        sm_dir = _qwen_sagemaker_dir().parent
        state_file = sm_dir / "deploy_state.json"
        region = os.environ.get("AWS_REGION", "us-east-1")
        endpoint = os.environ.get("ENDPOINT_NAME", "qwen3-tts-async")
        if state_file.exists():
            st = json.loads(state_file.read_text())
            region = st.get("region", region)
            endpoint = st.get("endpoint_name", endpoint)
        sm = boto3.client("sagemaker", region_name=region)
        desc = sm.describe_endpoint(EndpointName=endpoint)
        status = desc.get("EndpointStatus")
        variants = desc.get("ProductionVariants", [{}])
        inst = variants[0].get("CurrentInstanceCount", 0) if variants else 0
        in_service = status == "InService"
        if in_service and inst >= 1:
            msg = f"Endpoint ready ({inst} instance) — preview will synth in your voice."
        elif in_service:
            msg = ("Endpoint is scaled to zero — the first preview cold-starts "
                   "(~5-10 min) while it warms up.")
        else:
            msg = f"Endpoint status: {status} — preview may be unavailable."
        return {"available": in_service, "in_service": in_service,
                "instances": int(inst), "message": msg}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "in_service": False, "instances": 0,
                "message": f"Qwen endpoint unavailable ({type(e).__name__}) — preview disabled."}


def generate_preview(take, paragraph: str, recordings_root: str | Path,
                     slug: str | None = None, timeout: int = 900) -> dict:
    """
    Synthesize `paragraph` in the take's cloned voice and save the wav.

    `take` may be a Take object or a dict; needs `id`, `master_wav`, and a
    scorecard transcript (used as ref_text). Returns:
      success  -> {"wav": <path>, "status": "ok", "slug": slug}
      degraded -> {"wav": None, "status": "error: <reason>"}
    Never raises to the UI.
    """
    try:
        tid = getattr(take, "id", None) or take["id"]
        master = getattr(take, "master_wav", None) or take["master_wav"]
        sc = getattr(take, "scorecard", None) or take.get("scorecard", {})
        ref_text = (sc or {}).get("transcript", "")
        if not paragraph or not paragraph.strip():
            return {"wav": None, "status": "error: no text to synthesize"}
        if not master or not Path(master).exists():
            return {"wav": None, "status": "error: take master WAV not found"}
        if not ref_text.strip():
            return {"wav": None, "status": "error: take has no transcript (ref_text) — "
                                           "re-score it first"}

        slug = slug or _slugify(paragraph)
        out_dir = Path(recordings_root).expanduser() / "exports" / tid / "previews"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{slug}.wav"

        synth = _import_synth()
        payload = build_clone_payload(master, paragraph, ref_text)
        synth(payload, str(out_path), timeout=timeout)
        if not out_path.exists():
            return {"wav": None, "status": "error: synth produced no file"}
        return {"wav": str(out_path), "status": "ok", "slug": slug}
    except Exception as e:  # noqa: BLE001
        return {"wav": None, "status": f"error: {type(e).__name__}: {str(e)[:200]}"}
