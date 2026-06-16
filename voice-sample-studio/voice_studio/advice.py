"""
Actionable advice for the NEXT recording, in two flavours:

  * BASIC  — a deterministic, OFFLINE, rule-based function of the Scorecard. It
    maps the existing metrics/labels to forward-looking "to improve your next
    recording" tips. Pure function of the scorecard dict -> unit-testable
    (see selftest.py). No network, no model, no randomness.

  * RICH   — an LLM-generated variant (Bedrock Claude on us-east-1 via the
    Converse API). It is fed the SAME scorecard numbers + labels and asked for
    concise, friendly, actionable next-recording advice. It GRACEFULLY DEGRADES:
    if boto3 / creds / the model are unavailable it returns (None, reason) and
    the app shows basic-only with a small "rich advice unavailable" note. It
    never raises.

Both are deliberately UI-independent so the app stays a thin layer.

The basic rules reuse the very same thresholds the scoring engine uses
(imported from `quality`) so advice never drifts from the verdict.
"""
from __future__ import annotations

import os

from . import quality as q


# --------------------------------------------------------------------------- #
# BASIC — deterministic, offline, rule-based.                                  #
# --------------------------------------------------------------------------- #
def basic_advice(sc: dict, keyed: bool = False):
    """
    Map a scorecard dict to a list of forward-looking, next-recording tips.

    Pure function: same scorecard in -> same advice out. Each tip has a stable
    `key` (for testing/telemetry) and a human-readable `text`.

    Returns:
      keyed=False -> list[str]                 (just the texts, for display)
      keyed=True  -> list[tuple[str, str]]     [(key, text), ...]  (for tests)
    """
    tips: list[tuple[str, str]] = []

    def add(key: str, text: str):
        tips.append((key, text))

    g = sc.get  # shorthand

    # ---- Acoustic (signal) --------------------------------------------------
    clip = g("clipping_fraction") or 0.0
    if clip > q.CLIP_SAMPLE_FRACTION_MAX:
        add("clipping",
            f"You clipped ({clip * 100:.2f}% of samples near full-scale) — lower the "
            f"input gain a few dB or move ~10 cm back from the mic so peaks don't distort.")
    tp = g("true_peak_dbtp")
    if clip <= q.CLIP_SAMPLE_FRACTION_MAX and tp is not None and tp > q.TRUE_PEAK_CLIP_DBTP:
        add("true_peak",
            f"Peaks are right at the ceiling ({tp:.1f} dBTP) — drop the input gain a "
            f"few dB to leave headroom (aim below {q.TRUE_PEAK_CLIP_DBTP:.0f} dBTP).")

    snr = g("snr_db")
    nf = g("noise_floor_dbfs")
    noisy = (snr is not None and snr < q.SNR_MIN_DB) or \
            (nf is not None and nf > q.NOISE_FLOOR_MAX_DBFS)
    if noisy:
        snr_txt = f"SNR {snr:.0f} dB" if snr is not None else f"noise floor {nf:.0f} dBFS"
        add("noise",
            f"Background noise is high ({snr_txt}) — record in a quieter room, close "
            f"windows/fans, and get closer to the mic (aim SNR ≥ {q.SNR_MIN_DB:.0f} dB).")

    bw = g("bandwidth_hz") or 0.0
    if bw and bw < q.BANDWIDTH_MIN_HZ:
        add("muffled",
            f"Sounds muffled / band-limited (rolloff ~{bw:.0f} Hz) — make sure nothing "
            f"covers the mic and use a full-band mic, not a phone/headset line.")

    lufs = g("integrated_lufs")
    if lufs is not None and lufs < q.LUFS_MIN:
        add("too_quiet",
            f"A little quiet ({lufs:.0f} LUFS) — speak up or move closer; we normalize "
            f"to {q.TARGET_LUFS:.0f} LUFS but a stronger signal clones better.")
    elif lufs is not None and lufs > q.LUFS_MAX:
        add("too_loud",
            f"A bit hot ({lufs:.0f} LUFS) — back the input gain off slightly.")

    dur = g("duration") or 0.0
    if dur < q.MIN_DURATION_S:
        add("too_short",
            f"Too short ({dur:.0f} s) — aim for {q.IDEAL_DURATION_LO:.0f}–"
            f"{q.IDEAL_DURATION_HI:.0f} s so the clone captures your full range.")
    elif dur > q.MAX_DURATION_S:
        add("too_long",
            f"A bit long ({dur:.0f} s) — trim toward {q.IDEAL_DURATION_LO:.0f}–"
            f"{q.IDEAL_DURATION_HI:.0f} s; very long takes drift.")

    sr = g("sample_rate") or 0
    if sr and sr < q.MIN_SAMPLE_RATE:
        add("sample_rate",
            f"Recorded at {sr} Hz — record at ≥ {q.MIN_SAMPLE_RATE} Hz "
            f"(Qwen's reference rate) for a faithful clone.")

    lead = g("lead_trim_s") or 0.0
    if lead > 0.5:
        add("lead_silence",
            f"Trim ~{lead:.1f} s of leading silence — start speaking a touch sooner.")
    tail = g("tail_trim_s") or 0.0
    if tail > 0.5:
        add("tail_silence",
            f"Trim ~{tail:.1f} s of trailing silence — stop the recording right after "
            f"your last word.")

    sil = g("silence_ratio")
    if sil is not None and sil > q.SILENCE_RATIO_MAX:
        add("too_much_silence",
            f"Lots of dead air ({sil * 100:.0f}% silence) — keep a steady flow with "
            f"shorter gaps between sentences.")

    # ---- Delivery / prosody -------------------------------------------------
    wpm = g("wpm")
    if wpm is not None:
        if wpm > q.WPM_OK_HI:
            add("fast",
                f"A touch fast at {wpm:.0f} WPM — slow down and aim "
                f"{q.WPM_GOOD_LO:.0f}–{q.WPM_GOOD_HI:.0f} WPM so the clone doesn't rush.")
        elif wpm < q.WPM_TOO_SLOW:
            add("slow",
                f"A bit slow/draggy at {wpm:.0f} WPM — pick up the pace toward "
                f"{q.WPM_GOOD_LO:.0f}–{q.WPM_GOOD_HI:.0f} WPM.")
        elif wpm < q.WPM_SLOW:
            add("slightly_slow",
                f"Slightly slow at {wpm:.0f} WPM — nudge toward "
                f"{q.WPM_GOOD_LO:.0f}–{q.WPM_GOOD_HI:.0f} WPM.")

    pstd = g("pitch_std_semitones")
    if pstd is not None:
        if pstd < q.PITCH_STD_MONOTONE:
            add("monotone",
                f"Fairly monotone (pitch variation {pstd:.1f} st) — add a little vocal "
                f"variation/intonation so the clone isn't flat.")
        elif pstd > q.PITCH_STD_SINGSONGY:
            add("singsongy",
                f"Quite sing-songy (pitch variation {pstd:.1f} st) — even out the "
                f"intonation a little.")

    dyn = g("loudness_dynamics_db")
    if dyn is not None and dyn and dyn < q.DYN_FLAT_DB:
        add("flat_dynamics",
            f"Flat delivery (loudness dynamics {dyn:.1f} dB) — vary your emphasis "
            f"on the words that matter.")

    ppm = g("pauses_per_min")
    if ppm is not None and ppm and ppm > q.PAUSE_CHOPPY_RATE:
        add("choppy",
            f"Choppy / hesitant ({ppm:.0f} pauses/min) — read in smoother, connected "
            f"phrases.")

    wer = g("wer")
    if wer is not None and wer > 0.15:
        add("wer",
            f"Transcript differs from the script (WER {wer * 100:.0f}%) — read the "
            f"prompt more closely, or double-check ref_text.txt before exporting.")

    # ---- Nothing wrong: a positive, still-actionable note -------------------
    if not tips:
        add("all_good",
            "This take looks great — clean, well-paced, and expressive. Re-record "
            "only if you want to A/B a different tone or energy.")

    if keyed:
        return tips
    return [t for _, t in tips]


def basic_advice_markdown(sc: dict) -> str:
    """Render basic advice as a Markdown bullet list."""
    tips = basic_advice(sc)
    return "\n".join(f"- {t}" for t in tips)


# --------------------------------------------------------------------------- #
# RICH — Bedrock Claude (Converse). Graceful-degrade, never raises.            #
# --------------------------------------------------------------------------- #
DEFAULT_BEDROCK_MODEL = os.environ.get(
    "VOICE_STUDIO_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)
BEDROCK_REGION = os.environ.get("VOICE_STUDIO_BEDROCK_REGION",
                                os.environ.get("AWS_REGION", "us-east-1"))


def _scorecard_facts(sc: dict) -> str:
    """A compact, model-friendly digest of the scorecard numbers + labels."""
    def f(key, suffix="", nd=1):
        v = sc.get(key)
        return f"{v:.{nd}f}{suffix}" if isinstance(v, (int, float)) else "n/a"

    labels = ", ".join(sc.get("labels", [])) or "(none)"
    issues = "; ".join(sc.get("issues", [])) or "(none)"
    return (
        f"verdict={sc.get('verdict')}, overall_score={f('overall_score')}/100, "
        f"stars={sc.get('stars')}\n"
        f"duration={f('duration','s')}, sample_rate={sc.get('sample_rate')}Hz, "
        f"loudness={f('integrated_lufs',' LUFS')}, true_peak={f('true_peak_dbtp',' dBTP',2)}, "
        f"clipping={f('clipping_fraction','',6)}\n"
        f"snr={f('snr_db',' dB')}, noise_floor={f('noise_floor_dbfs',' dBFS')}, "
        f"bandwidth={f('bandwidth_hz',' Hz',0)}, silence_ratio={f('silence_ratio')}, "
        f"lead_trim={f('lead_trim_s','s')}, tail_trim={f('tail_trim_s','s')}\n"
        f"speaking_rate={f('wpm',' WPM',0)} (good band 120-165), "
        f"pitch_variation={f('pitch_std_semitones',' st')} (monotone<1.5, lively 2-6), "
        f"loudness_dynamics={f('loudness_dynamics_db',' dB')}, "
        f"pauses_per_min={f('pauses_per_min','',0)}\n"
        f"mos={f('mos','',2)}, wer={f('wer')}\n"
        f"labels: {labels}\n"
        f"issues: {issues}"
    )


_RICH_SYSTEM = (
    "You are a friendly voice-coaching assistant. The user is recording a short "
    "voice reference clip that an AI will clone (it inherits the clip's pace, pitch, "
    "energy, and cleanliness). Given the objective measurements of their last take, "
    "give concise, encouraging, ACTIONABLE advice for their NEXT recording. "
    "Lead with what's good, then 2-4 specific, concrete tips (mic technique, pacing, "
    "intonation, environment). Use plain language and refer to the numbers only when "
    "it helps. Keep it under ~120 words. Use short markdown bullets. Do not invent "
    "metrics that aren't provided."
)


def rich_advice(sc: dict, model_id: str | None = None,
                region: str | None = None, timeout: float = 30.0):
    """
    Generate LLM advice via Bedrock Claude (Converse API).

    Returns (advice_markdown_or_None, status_str). NEVER raises:
      success  -> (text, f"bedrock:{model_id}")
      degraded -> (None, "unavailable: <reason>")
    """
    model_id = model_id or DEFAULT_BEDROCK_MODEL
    region = region or BEDROCK_REGION
    try:
        import boto3  # noqa: F401
        from botocore.config import Config
    except Exception as e:  # noqa: BLE001
        return None, f"unavailable: boto3 not installed ({type(e).__name__})"

    try:
        import boto3
        from botocore.config import Config
        client = boto3.client(
            "bedrock-runtime", region_name=region,
            config=Config(connect_timeout=10, read_timeout=timeout, retries={"max_attempts": 1}),
        )
        prompt = (
            "Here are the measurements of my last voice-reference take:\n\n"
            f"{_scorecard_facts(sc)}\n\n"
            "Give me friendly, actionable advice for my next recording."
        )
        resp = client.converse(
            modelId=model_id,
            system=[{"text": _RICH_SYSTEM}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 400, "temperature": 0.3},
        )
        parts = resp.get("output", {}).get("message", {}).get("content", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            return None, "unavailable: empty response"
        return text, f"bedrock:{model_id}"
    except Exception as e:  # noqa: BLE001
        return None, f"unavailable: {type(e).__name__}: {str(e)[:160]}"
