"""
SageMaker inference handler for Qwen3-TTS (async endpoint).

Loads BOTH models into one ml.g5.xlarge (A10G 24GB):
  - Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice  (named speakers, instruct control)
  - Qwen/Qwen3-TTS-12Hz-1.7B-Base         (3-second reference voice clone)

Request JSON (async, via S3):
  {"mode":"custom_voice","text":...,"language":"en","speaker":"Aiden","instruct":"calm"}
  {"mode":"voice_clone","text":...,"language":"en","ref_audio":<b64|s3|https>,"ref_text":...}

Response JSON:
  {"audio_base64": <wav bytes b64>, "sample_rate": int, "mode": str}

Design notes:
  * bf16 + CUDA required by qwen-tts.
  * FlashAttention2 is RECOMMENDED but OPTIONAL — we try it, fall back to the default
    attention implementation if flash-attn is unavailable. The 1.7B model fits 24GB w/o FA2.
  * No HF token: models are public Apache-2.0.
"""
import base64
import io
import json
import os
import tempfile
import urllib.request

import soundfile as sf

CUSTOM_VOICE_ID = os.environ.get("HF_MODEL_CUSTOM_VOICE", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
BASE_ID = os.environ.get("HF_MODEL_BASE", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")

# Qwen3-TTS expects full language names. Normalize common ISO codes / aliases.
LANG_MAP = {
    "en": "english", "en-us": "english", "en-gb": "english", "eng": "english",
    "de": "german", "deu": "german", "ger": "german",
    "fr": "french", "it": "italian", "ja": "japanese", "jp": "japanese",
    "ko": "korean", "pt": "portuguese", "ru": "russian", "es": "spanish",
    "zh": "chinese", "cn": "chinese",
}


def normalize_language(lang):
    if not lang:
        return "auto"
    return LANG_MAP.get(lang.strip().lower(), lang.strip().lower())


def _load_one(model_id):
    """Load a single Qwen3TTSModel in bf16 on CUDA, FA2 if available else default attn."""
    import torch
    from qwen_tts import Qwen3TTSModel

    # Try FlashAttention2 first (recommended), fall back gracefully.
    for attn in ("flash_attention_2", None):
        try:
            kwargs = dict(torch_dtype=torch.bfloat16, device_map="cuda")
            if attn:
                kwargs["attn_implementation"] = attn
            print(f"[model_fn] loading {model_id} attn={attn or 'default'}")
            m = Qwen3TTSModel.from_pretrained(model_id, **kwargs)
            print(f"[model_fn] loaded {model_id} (attn={attn or 'default'})")
            return m
        except Exception as e:  # noqa: BLE001
            print(f"[model_fn] {model_id} attn={attn} failed: {e}")
    raise RuntimeError(f"Could not load {model_id} with any attention implementation")


def model_fn(model_dir, context=None):
    """Load both models once at container start."""
    print("[model_fn] start — loading CustomVoice + Base")
    models = {
        "custom_voice": _load_one(CUSTOM_VOICE_ID),
        "base": _load_one(BASE_ID),
    }
    print("[model_fn] both models ready")
    return models


def input_fn(request_body, content_type="application/json", context=None):
    if isinstance(request_body, (bytes, bytearray)):
        request_body = request_body.decode("utf-8")
    if content_type and "json" not in content_type:
        print(f"[input_fn] unexpected content_type={content_type}, parsing as JSON anyway")
    return json.loads(request_body)


def _materialize_ref_audio(ref_audio):
    """Return a local wav path from base64, s3://, or https:// reference audio."""
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    if ref_audio.startswith("s3://"):
        import boto3

        bucket, key = ref_audio[5:].split("/", 1)
        boto3.client("s3").download_file(bucket, key, path)
    elif ref_audio.startswith(("http://", "https://")):
        urllib.request.urlretrieve(ref_audio, path)  # noqa: S310
    else:
        with open(path, "wb") as f:
            f.write(base64.b64decode(ref_audio))
    return path


def predict_fn(data, models, context=None):
    mode = data.get("mode", "custom_voice")
    text = data["text"]
    language = normalize_language(data.get("language", "english"))

    if mode == "voice_clone":
        ref_audio = data["ref_audio"]
        ref_text = data.get("ref_text", "")
        ref_path = _materialize_ref_audio(ref_audio)
        try:
            wavs, sr = models["base"].generate_voice_clone(
                text, language=language, ref_audio=ref_path, ref_text=ref_text
            )
        finally:
            try:
                os.remove(ref_path)
            except OSError:
                pass
    else:  # custom_voice
        speaker = data.get("speaker", "Aiden")
        instruct = data.get("instruct")
        kwargs = dict(language=language, speaker=speaker)
        if instruct:
            kwargs["instruct"] = instruct
        wavs, sr = models["custom_voice"].generate_custom_voice(text, **kwargs)

    wav = wavs[0] if isinstance(wavs, (list, tuple)) else wavs
    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV")
    return {"audio_base64": base64.b64encode(buf.getvalue()).decode("utf-8"),
            "sample_rate": int(sr), "mode": mode}


def output_fn(prediction, accept="application/json", context=None):
    # Return the serialized body only (NOT a tuple) so the toolkit doesn't wrap it
    # as [body, content_type]. The client also tolerates the wrapped form for safety.
    return json.dumps(prediction)
