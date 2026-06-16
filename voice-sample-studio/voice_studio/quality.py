"""
Quality scoring engine for voice reference clips (Qwen3-TTS voice_clone).

ALL metrics are local / CPU-only. The engine is deliberately UI-independent so it
can be unit-tested headless (see selftest.py). The public entry point is
`score_file(path)` -> Scorecard.

Two metric families:
  * ACOUSTIC (signal quality): SNR, noise floor, clipping, true-peak, LUFS, occupied
    bandwidth, duration, sample-rate, silence/lead-tail trim.
  * DELIVERY (prosody — how the clone will SOUND): speaking rate (WPM), pitch
    variation / intonation, loudness dynamics, and pause profile.

Design rationale (see README for the full table): the Qwen voice_clone path
INHERITS the cadence, pace, pitch and timbre of the reference clip, so a good
reference is clean (high SNR, low noise floor), un-clipped, loud enough to normalize
to ~-16 LUFS, >=24 kHz mono-able, the right length, AND delivered with a calm, well
paced, expressive (not monotone) voice with smooth (not choppy) phrasing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import numpy as np

from .audio_io import AudioData, load_audio

# ---- Acoustic thresholds (documented in README) ----------------------------
TARGET_LUFS = -16.0           # post-normalization target the pipeline uses
LUFS_MIN, LUFS_MAX = -30.0, -12.0   # acceptable integrated loudness band (pre-norm)
TRUE_PEAK_CLIP_DBTP = -1.0    # peaks above this risk inter-sample clipping
CLIP_SAMPLE_FRACTION_MAX = 0.0005  # >0.05% near-full-scale samples => clipping
SNR_GOOD_DB = 35.0            # >= this is excellent
SNR_MIN_DB = 20.0             # below this is a reject for a reference clip
NOISE_FLOOR_MAX_DBFS = -50.0  # noise floor should sit below this
MIN_DURATION_S = 8.0          # too short => not enough range
MAX_DURATION_S = 45.0         # too long => unwieldy / drifts
IDEAL_DURATION_LO, IDEAL_DURATION_HI = 12.0, 35.0
MIN_SAMPLE_RATE = 24000       # Qwen reference is 24 kHz; below is upsampled junk
SILENCE_RATIO_MAX = 0.45      # >45% silence => mostly dead air
LEAD_TAIL_TRIM_DB = -40.0     # threshold for detecting lead/tail silence
BANDWIDTH_MIN_HZ = 5000.0     # below this rolloff => muffled / band-limited (telephone)
BANDWIDTH_GOOD_HZ = 9000.0    # full, natural speech bandwidth

# ---- Delivery / prosody thresholds (tunable; documented in README) ----------
# Speaking rate (words per minute), measured over the spoken span.
WPM_TOO_SLOW = 105.0          # < this => "too slow / draggy"
WPM_SLOW = 120.0              # [TOO_SLOW, this) => "a touch slow"
WPM_GOOD_LO, WPM_GOOD_HI = 120.0, 165.0   # "good pace"
WPM_OK_HI = 175.0             # (GOOD_HI, this] => still ok; above => "too fast"
# Pitch variation (standard deviation of F0 in SEMITONES over voiced frames).
PITCH_STD_MONOTONE = 1.5      # < this => "monotone / flat / boring"
PITCH_STD_GOOD_LO = 2.0       # healthy expressiveness starts around here
PITCH_STD_GOOD_HI = 6.0       # expressive / lively
PITCH_STD_SINGSONGY = 9.0     # > this => "very sing-songy"
# Loudness dynamics (p95 - p10 of voiced frame RMS, dB).
DYN_FLAT_DB = 6.0             # < this => "flat delivery"
DYN_GOOD_LO, DYN_GOOD_HI = 8.0, 22.0   # "good dynamics"
# Pause profile.
PAUSE_GAP_MIN_S = 0.30        # gap >= this counts as a pause
PAUSE_LONG_S = 0.8            # a "long" pause
PAUSE_CHOPPY_RATE = 18.0      # pauses-per-minute above this => "choppy / hesitant"

# Star-rating bands (overall score 0-100).
STAR_BANDS = [(85.0, 5), (70.0, 4), (55.0, 3), (40.0, 2), (0.0, 1)]

EPS = 1e-12


def _dbfs(x: float) -> float:
    return 20.0 * math.log10(max(abs(x), EPS))


def _rms(a: np.ndarray) -> float:
    if a.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(a.astype(np.float64) ** 2)))


# ---- Acoustic metric helpers -----------------------------------------------
def integrated_lufs(audio: AudioData) -> float | None:
    """Integrated loudness (LUFS). Prefers pyloudnorm; falls back to ffmpeg loudnorm."""
    try:
        import pyloudnorm as pyln  # type: ignore
        meter = pyln.Meter(audio.sample_rate)
        loud = meter.integrated_loudness(audio.samples.astype(np.float64))
        if loud == float("-inf") or math.isnan(loud):
            return None
        return float(loud)
    except Exception:
        return _lufs_via_ffmpeg(audio)


def _lufs_via_ffmpeg(audio: AudioData) -> float | None:
    """Measure integrated loudness with ffmpeg's loudnorm (EBU R128) JSON pass."""
    import json
    import shutil
    import subprocess
    import tempfile
    import wave
    from pathlib import Path

    if not shutil.which("ffmpeg"):
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = str(Path(td) / "m.wav")
            ints = np.clip(audio.samples, -1, 1)
            with wave.open(tmp, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(audio.sample_rate)
                w.writeframes((ints * 32767).astype("<i2").tobytes())
            proc = subprocess.run(
                ["ffmpeg", "-nostdin", "-i", tmp, "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
            )
            txt = proc.stderr
            start = txt.rfind("{")
            end = txt.rfind("}")
            if start == -1 or end == -1:
                return None
            data = json.loads(txt[start:end + 1])
            val = float(data.get("input_i", "nan"))
            return None if math.isnan(val) else val
    except Exception:
        return None


def true_peak_dbtp(audio: AudioData) -> float:
    """Approximate true-peak in dBTP via 4x oversampling of the peak region."""
    s = audio.samples
    if s.size == 0:
        return -120.0
    try:
        x = np.arange(s.size)
        xi = np.linspace(0, s.size - 1, s.size * 4)
        up = np.interp(xi, x, s)
        peak = float(np.max(np.abs(up)))
    except Exception:
        peak = float(np.max(np.abs(s)))
    return _dbfs(peak)


def clipping_fraction(audio: AudioData, thresh: float = 0.999) -> float:
    """Fraction of samples at/above near-full-scale (hard-clip indicator)."""
    s = audio.samples
    if s.size == 0:
        return 0.0
    return float(np.mean(np.abs(s) >= thresh))


def _frame_rms_db(audio: AudioData, frame_ms: float = 50.0):
    s = audio.samples
    fl = max(1, int(audio.sample_rate * frame_ms / 1000.0))
    n = s.size // fl
    if n == 0:
        return np.array([_dbfs(_rms(s))])
    frames = s[: n * fl].reshape(n, fl)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    return 20.0 * np.log10(np.maximum(rms, EPS))


def noise_floor_and_snr(audio: AudioData):
    """Noise floor (dBFS) and SNR (dB) from the distribution of frame energies."""
    db = _frame_rms_db(audio)
    if db.size == 0:
        return -120.0, 0.0
    noise = float(np.percentile(db, 10))
    speech = float(np.percentile(db, 90))
    snr = speech - noise
    return noise, max(snr, 0.0)


def spectral_rolloff_hz(audio: AudioData, floor_db: float = 40.0) -> float:
    """
    Estimate the occupied audio bandwidth: the highest frequency whose averaged
    (voiced) power-spectrum level is within `floor_db` dB of the spectral peak.
    Robust band-limiting indicator (telephone-band ~3.4 kHz vs full speech ~8-11 kHz).
    """
    s = audio.samples
    sr = audio.sample_rate
    if s.size < 1024 or sr <= 0:
        return float(sr) / 2.0
    frame = 2048
    hop = 1024
    db_frames = _frame_rms_db(audio, frame_ms=hop / sr * 1000.0)
    thresh = float(np.percentile(db_frames, 60))  # gate to voiced frames
    win = np.hanning(frame)
    accum = None
    for start in range(0, s.size - frame, hop):
        seg = s[start:start + frame]
        if 20.0 * math.log10(max(_rms(seg), EPS)) < thresh:
            continue
        spec = np.abs(np.fft.rfft(seg * win)) ** 2
        accum = spec if accum is None else accum + spec
    if accum is None:
        return float(sr) / 2.0
    freqs = np.fft.rfftfreq(frame, d=1.0 / sr)
    power_db = 10.0 * np.log10(np.maximum(accum, accum.max() * EPS))
    peak_db = float(power_db.max())
    above = np.where(power_db >= (peak_db - floor_db))[0]
    if above.size == 0:
        return float(sr) / 2.0
    return float(freqs[int(above.max())])


def silence_analysis(audio: AudioData, thresh_db: float = LEAD_TAIL_TRIM_DB):
    """Return (silence_ratio, lead_trim_s, tail_trim_s) using frame energies."""
    frame_ms = 50.0
    db = _frame_rms_db(audio, frame_ms)
    voiced = db > thresh_db
    ratio = float(1.0 - np.mean(voiced)) if voiced.size else 1.0
    sec_per_frame = frame_ms / 1000.0
    lead = 0
    for v in voiced:
        if v:
            break
        lead += 1
    tail = 0
    for v in voiced[::-1]:
        if v:
            break
        tail += 1
    return ratio, lead * sec_per_frame, tail * sec_per_frame


# ---- Delivery / prosody metric helpers -------------------------------------
def pitch_variation(audio: AudioData):
    """
    Pitch / intonation analysis via librosa.pyin (ISC). Returns a dict with:
      mean_f0_hz, f0_std_semitones, pitch_range_semitones, voiced_ratio, backend.

    f0_std_semitones is the headline number behind the monotone/"boring" label.
    Computed in semitones (perceptually uniform) over voiced frames. Returns
    backend="unavailable" with None values if librosa can't load.
    """
    out = {"mean_f0_hz": None, "f0_std_semitones": None,
           "pitch_range_semitones": None, "voiced_ratio": None, "backend": "unavailable"}
    try:
        import librosa  # type: ignore
    except Exception:
        return out
    try:
        s = audio.samples.astype(np.float32)
        sr = audio.sample_rate
        # Downsample to 16 kHz for speed (pyin is the slow part).
        if sr > 16000:
            try:
                s = librosa.resample(s, orig_sr=sr, target_sr=16000)
                sr = 16000
            except Exception:
                pass
        if s.size < sr // 2:  # < 0.5 s of audio
            return out
        f0, voiced_flag, _vp = librosa.pyin(
            s, sr=sr, fmin=65.0, fmax=400.0,
            frame_length=2048, hop_length=256,
        )
        voiced = f0[np.isfinite(f0)]
        voiced = voiced[voiced > 0]
        ratio = float(np.mean(np.isfinite(f0))) if f0.size else 0.0
        out["backend"] = "librosa-pyin"
        out["voiced_ratio"] = round(ratio, 3)
        if voiced.size < 8:
            return out
        mean_f0 = float(np.median(voiced))
        semis = 12.0 * np.log2(np.maximum(voiced, EPS) / max(mean_f0, EPS))
        # Robust spread: percentile-based to resist pyin octave-jump outliers.
        lo, hi = np.percentile(semis, [5, 95])
        out["mean_f0_hz"] = round(mean_f0, 1)
        out["f0_std_semitones"] = round(float(np.std(semis)), 2)
        out["pitch_range_semitones"] = round(float(hi - lo), 2)
        return out
    except Exception:
        return out


def loudness_dynamics_db(audio: AudioData) -> float:
    """Dynamic range of voiced loudness: p95 - p10 of voiced frame RMS (dB)."""
    db = _frame_rms_db(audio, frame_ms=50.0)
    if db.size == 0:
        return 0.0
    voiced = db[db > (float(np.max(db)) - 40.0)]  # gate out dead air
    if voiced.size < 4:
        voiced = db
    return float(np.percentile(voiced, 95) - np.percentile(voiced, 10))


def pace_and_pauses(audio: AudioData, words: list | None):
    """
    Speaking-rate + pause profile.

    If word timestamps are available (`words`), compute WPM over the spoken span,
    articulation rate (excluding pauses), and pause stats from inter-word gaps.
    Otherwise fall back to a silence-gap-based pause estimate (no WPM).

    Returns dict: wpm, articulation_wpm, word_count, pause_count, mean_pause_s,
    pauses_per_min, backend.
    """
    out = {"wpm": None, "articulation_wpm": None, "word_count": None,
           "pause_count": 0, "mean_pause_s": 0.0, "pauses_per_min": 0.0,
           "backend": "silence-fallback"}
    if words:
        wc = len(words)
        span = max(words[-1]["end"] - words[0]["start"], EPS)
        speak_time = sum(max(w["end"] - w["start"], 0.0) for w in words)
        gaps = []
        for a, b in zip(words[:-1], words[1:]):
            g = b["start"] - a["end"]
            if g >= PAUSE_GAP_MIN_S:
                gaps.append(g)
        out["backend"] = "word-timestamps"
        out["word_count"] = wc
        out["wpm"] = round(wc / (span / 60.0), 1)
        if speak_time > 0:
            out["articulation_wpm"] = round(wc / (speak_time / 60.0), 1)
        out["pause_count"] = len(gaps)
        out["mean_pause_s"] = round(float(np.mean(gaps)), 2) if gaps else 0.0
        out["pauses_per_min"] = round(len(gaps) / (audio.duration / 60.0), 1) if audio.duration else 0.0
        return out
    # Fallback: detect silent gaps between voiced regions from frame energies.
    frame_ms = 50.0
    db = _frame_rms_db(audio, frame_ms)
    if db.size == 0:
        return out
    voiced = db > LEAD_TAIL_TRIM_DB
    sec_per_frame = frame_ms / 1000.0
    gaps = []
    run = 0
    started = False
    for i, v in enumerate(voiced):
        if v:
            if started and run * sec_per_frame >= PAUSE_GAP_MIN_S:
                gaps.append(run * sec_per_frame)
            started = True
            run = 0
        else:
            if started:
                run += 1
    out["pause_count"] = len(gaps)
    out["mean_pause_s"] = round(float(np.mean(gaps)), 2) if gaps else 0.0
    out["pauses_per_min"] = round(len(gaps) / (audio.duration / 60.0), 1) if audio.duration else 0.0
    return out


# ---- Scorecard --------------------------------------------------------------
@dataclass
class Scorecard:
    path: str = ""
    duration: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    bits_per_sample: int | None = None
    integrated_lufs: float | None = None
    true_peak_dbtp: float = -120.0
    clipping_fraction: float = 0.0
    noise_floor_dbfs: float = -120.0
    snr_db: float = 0.0
    silence_ratio: float = 0.0
    lead_trim_s: float = 0.0
    tail_trim_s: float = 0.0
    bandwidth_hz: float = 0.0
    # delivery / prosody
    wpm: float | None = None
    articulation_wpm: float | None = None
    word_count: int | None = None
    pitch_mean_hz: float | None = None
    pitch_std_semitones: float | None = None
    pitch_range_semitones: float | None = None
    loudness_dynamics_db: float = 0.0
    pause_count: int = 0
    mean_pause_s: float = 0.0
    pauses_per_min: float = 0.0
    pace_backend: str = "unavailable"
    pitch_backend: str = "unavailable"
    # perceptual
    mos: float | None = None
    mos_backend: str = "unavailable"
    transcript: str = ""
    transcript_backend: str = "unavailable"
    wer: float | None = None
    # derived
    objective_score: float = 0.0   # 0-100 acoustic
    delivery_score: float = 0.0    # 0-100 prosody (None sub-metrics excluded)
    overall_score: float = 0.0     # 0-100 blended
    stars: int = 1                 # 1-5
    verdict: str = "reject"        # keep | review | reject
    labels: list = field(default_factory=list)
    issues: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _score_band(value, lo, hi, ideal_lo, ideal_hi) -> float:
    """1.0 inside [ideal_lo, ideal_hi], ramping to 0.0 at [lo, hi] bounds, 0 outside."""
    if value is None:
        return 0.0
    if ideal_lo <= value <= ideal_hi:
        return 1.0
    if value < lo or value > hi:
        return 0.0
    if value < ideal_lo:
        return (value - lo) / max(ideal_lo - lo, EPS)
    return (hi - value) / max(hi - ideal_hi, EPS)


def _compute_objective_score(sc: Scorecard) -> float:
    snr_s = max(0.0, min(1.0, (sc.snr_db - SNR_MIN_DB) / (SNR_GOOD_DB - SNR_MIN_DB)))
    nf_s = max(0.0, min(1.0, (NOISE_FLOOR_MAX_DBFS - sc.noise_floor_dbfs) / 15.0))
    clip_s = 1.0 - min(1.0, sc.clipping_fraction / max(CLIP_SAMPLE_FRACTION_MAX, EPS))
    tp_s = max(0.0, min(1.0, (0.0 - sc.true_peak_dbtp) / 1.0)) if sc.true_peak_dbtp > TRUE_PEAK_CLIP_DBTP else 1.0
    lufs_s = _score_band(sc.integrated_lufs, LUFS_MIN, LUFS_MAX, -24.0, -14.0)
    dur_s = _score_band(sc.duration, MIN_DURATION_S, MAX_DURATION_S, IDEAL_DURATION_LO, IDEAL_DURATION_HI)
    sr_s = 1.0 if sc.sample_rate >= MIN_SAMPLE_RATE else max(0.0, sc.sample_rate / MIN_SAMPLE_RATE)
    sil_s = max(0.0, min(1.0, (SILENCE_RATIO_MAX - sc.silence_ratio) / SILENCE_RATIO_MAX)) if sc.silence_ratio <= SILENCE_RATIO_MAX else 0.0
    bw_s = max(0.0, min(1.0, (sc.bandwidth_hz - BANDWIDTH_MIN_HZ) / (BANDWIDTH_GOOD_HZ - BANDWIDTH_MIN_HZ)))

    weights = {
        "snr": 0.24, "noise": 0.14, "clip": 0.13, "tp": 0.07,
        "lufs": 0.11, "dur": 0.09, "sr": 0.06, "sil": 0.06, "bw": 0.10,
    }
    total = (
        snr_s * weights["snr"] + nf_s * weights["noise"] + clip_s * weights["clip"]
        + tp_s * weights["tp"] + lufs_s * weights["lufs"] + dur_s * weights["dur"]
        + sr_s * weights["sr"] + sil_s * weights["sil"] + bw_s * weights["bw"]
    )
    return round(total * 100.0, 1)


def _pace_subscore(wpm) -> float | None:
    if wpm is None:
        return None
    if WPM_GOOD_LO <= wpm <= WPM_GOOD_HI:
        return 1.0
    if wpm < WPM_TOO_SLOW:
        return max(0.0, wpm / WPM_TOO_SLOW * 0.5)            # draggy
    if wpm < WPM_GOOD_LO:
        return 0.5 + 0.5 * (wpm - WPM_TOO_SLOW) / (WPM_GOOD_LO - WPM_TOO_SLOW)
    if wpm <= WPM_OK_HI:
        return 1.0 - 0.4 * (wpm - WPM_GOOD_HI) / (WPM_OK_HI - WPM_GOOD_HI)
    return max(0.0, 0.6 - 0.6 * (wpm - WPM_OK_HI) / WPM_OK_HI)  # too fast


def _pitch_subscore(std_semi) -> float | None:
    if std_semi is None:
        return None
    if PITCH_STD_GOOD_LO <= std_semi <= PITCH_STD_GOOD_HI:
        return 1.0
    if std_semi < PITCH_STD_MONOTONE:
        return max(0.0, std_semi / PITCH_STD_MONOTONE * 0.4)   # monotone
    if std_semi < PITCH_STD_GOOD_LO:
        return 0.4 + 0.6 * (std_semi - PITCH_STD_MONOTONE) / (PITCH_STD_GOOD_LO - PITCH_STD_MONOTONE)
    if std_semi <= PITCH_STD_SINGSONGY:
        return 1.0 - 0.5 * (std_semi - PITCH_STD_GOOD_HI) / (PITCH_STD_SINGSONGY - PITCH_STD_GOOD_HI)
    return 0.5


def _dynamics_subscore(dyn_db) -> float | None:
    if dyn_db is None:
        return None
    if DYN_GOOD_LO <= dyn_db <= DYN_GOOD_HI:
        return 1.0
    if dyn_db < DYN_FLAT_DB:
        return max(0.0, dyn_db / DYN_FLAT_DB * 0.4)
    if dyn_db < DYN_GOOD_LO:
        return 0.4 + 0.6 * (dyn_db - DYN_FLAT_DB) / (DYN_GOOD_LO - DYN_FLAT_DB)
    return max(0.4, 1.0 - (dyn_db - DYN_GOOD_HI) / DYN_GOOD_HI)


def _pause_subscore(ppm) -> float | None:
    if ppm is None:
        return None
    if ppm <= PAUSE_CHOPPY_RATE:
        return 1.0
    return max(0.0, 1.0 - (ppm - PAUSE_CHOPPY_RATE) / PAUSE_CHOPPY_RATE)


def _compute_delivery_score(sc: Scorecard) -> float:
    """Mean of AVAILABLE delivery sub-scores (0-100). Missing metrics are excluded."""
    parts = []
    for s in (_pace_subscore(sc.wpm), _pitch_subscore(sc.pitch_std_semitones),
              _dynamics_subscore(sc.loudness_dynamics_db), _pause_subscore(sc.pauses_per_min)):
        if s is not None:
            parts.append(s)
    if not parts:
        return 0.0
    return round(float(np.mean(parts)) * 100.0, 1)


def _stars(score: float) -> int:
    for lo, n in STAR_BANDS:
        if score >= lo:
            return n
    return 1


def _collect_labels(sc: Scorecard) -> list:
    """Human-readable chips derived from the measures."""
    labels: list[str] = []
    # acoustic
    if sc.snr_db >= SNR_GOOD_DB and (sc.bandwidth_hz or 0) >= BANDWIDTH_GOOD_HZ:
        labels.append("clear")
    if sc.bandwidth_hz and sc.bandwidth_hz < BANDWIDTH_MIN_HZ:
        labels.append("muffled")
    if sc.snr_db < SNR_MIN_DB or sc.noise_floor_dbfs > NOISE_FLOOR_MAX_DBFS:
        labels.append("noisy")
    if sc.clipping_fraction > CLIP_SAMPLE_FRACTION_MAX or sc.true_peak_dbtp > TRUE_PEAK_CLIP_DBTP:
        labels.append("clipped/distorted")
    if sc.integrated_lufs is not None and sc.integrated_lufs < LUFS_MIN:
        labels.append("too quiet")
    if sc.integrated_lufs is not None and sc.integrated_lufs > LUFS_MAX:
        labels.append("too loud")
    if sc.duration < MIN_DURATION_S:
        labels.append("too short")
    elif sc.duration > MAX_DURATION_S:
        labels.append("too long")
    # pace
    if sc.wpm is not None:
        if sc.wpm > WPM_OK_HI:
            labels.append("too fast")
        elif sc.wpm < WPM_TOO_SLOW:
            labels.append("too slow/draggy")
        elif WPM_GOOD_LO <= sc.wpm <= WPM_GOOD_HI:
            labels.append("good pace")
    # pitch
    if sc.pitch_std_semitones is not None:
        if sc.pitch_std_semitones < PITCH_STD_MONOTONE:
            labels.append("monotone/flat/boring")
        elif sc.pitch_std_semitones > PITCH_STD_SINGSONGY:
            labels.append("very sing-songy")
        elif PITCH_STD_GOOD_LO <= sc.pitch_std_semitones <= PITCH_STD_GOOD_HI:
            labels.append("expressive/lively")
    # dynamics
    if sc.loudness_dynamics_db and sc.loudness_dynamics_db < DYN_FLAT_DB:
        labels.append("flat delivery")
    elif DYN_GOOD_LO <= sc.loudness_dynamics_db <= DYN_GOOD_HI:
        labels.append("good dynamics")
    # pauses
    if sc.pauses_per_min and sc.pauses_per_min > PAUSE_CHOPPY_RATE:
        labels.append("choppy/hesitant")
    elif sc.pace_backend != "unavailable" and sc.pauses_per_min <= PAUSE_CHOPPY_RATE:
        labels.append("smooth")
    # perceptual
    if sc.mos is not None:
        if sc.mos >= 3.8:
            labels.append("natural")
        elif sc.mos < 2.8:
            labels.append("synthetic-sounding")
    # de-dupe, preserve order
    seen = set()
    return [x for x in labels if not (x in seen or seen.add(x))]


def _collect_issues(sc: Scorecard) -> list:
    issues = []
    if sc.snr_db < SNR_MIN_DB:
        issues.append(f"Low SNR {sc.snr_db:.1f} dB (< {SNR_MIN_DB:.0f} dB) — noisy environment.")
    if sc.noise_floor_dbfs > NOISE_FLOOR_MAX_DBFS:
        issues.append(f"High noise floor {sc.noise_floor_dbfs:.1f} dBFS (> {NOISE_FLOOR_MAX_DBFS:.0f}).")
    if sc.clipping_fraction > CLIP_SAMPLE_FRACTION_MAX:
        issues.append(f"Clipping detected ({sc.clipping_fraction*100:.3f}% near-full-scale samples).")
    if sc.true_peak_dbtp > TRUE_PEAK_CLIP_DBTP:
        issues.append(f"True peak {sc.true_peak_dbtp:.2f} dBTP exceeds {TRUE_PEAK_CLIP_DBTP:.0f} dBTP.")
    if sc.integrated_lufs is not None and not (LUFS_MIN <= sc.integrated_lufs <= LUFS_MAX):
        issues.append(f"Loudness {sc.integrated_lufs:.1f} LUFS outside [{LUFS_MIN:.0f}, {LUFS_MAX:.0f}].")
    if sc.duration < MIN_DURATION_S:
        issues.append(f"Too short ({sc.duration:.1f}s < {MIN_DURATION_S:.0f}s) — insufficient range.")
    elif sc.duration > MAX_DURATION_S:
        issues.append(f"Too long ({sc.duration:.1f}s > {MAX_DURATION_S:.0f}s).")
    if sc.sample_rate < MIN_SAMPLE_RATE:
        issues.append(f"Sample rate {sc.sample_rate} Hz < {MIN_SAMPLE_RATE} Hz.")
    if sc.silence_ratio > SILENCE_RATIO_MAX:
        issues.append(f"Mostly silence ({sc.silence_ratio*100:.0f}%).")
    if sc.bandwidth_hz and sc.bandwidth_hz < BANDWIDTH_MIN_HZ:
        issues.append(f"Band-limited / muffled (rolloff {sc.bandwidth_hz:.0f} Hz < {BANDWIDTH_MIN_HZ:.0f} Hz).")
    if sc.lead_trim_s > 0.5:
        issues.append(f"Trim ~{sc.lead_trim_s:.1f}s of leading silence.")
    if sc.tail_trim_s > 0.5:
        issues.append(f"Trim ~{sc.tail_trim_s:.1f}s of trailing silence.")
    # delivery
    if sc.wpm is not None and sc.wpm > WPM_OK_HI:
        issues.append(f"Speaking too fast ({sc.wpm:.0f} WPM > {WPM_OK_HI:.0f}) — the clone will rush.")
    if sc.wpm is not None and sc.wpm < WPM_TOO_SLOW:
        issues.append(f"Speaking too slow / draggy ({sc.wpm:.0f} WPM < {WPM_TOO_SLOW:.0f}).")
    if sc.pitch_std_semitones is not None and sc.pitch_std_semitones < PITCH_STD_MONOTONE:
        issues.append(f"Monotone delivery (pitch variation {sc.pitch_std_semitones:.1f} st "
                      f"< {PITCH_STD_MONOTONE:.1f} st) — the clone will sound flat/boring.")
    if sc.loudness_dynamics_db and sc.loudness_dynamics_db < DYN_FLAT_DB:
        issues.append(f"Flat delivery (loudness dynamics {sc.loudness_dynamics_db:.1f} dB "
                      f"< {DYN_FLAT_DB:.0f} dB).")
    if sc.pauses_per_min and sc.pauses_per_min > PAUSE_CHOPPY_RATE:
        issues.append(f"Choppy / hesitant ({sc.pauses_per_min:.0f} pauses/min, "
                      f"mean {sc.mean_pause_s:.1f}s).")
    return issues


def _verdict(sc: Scorecard) -> str:
    # Hard rejects regardless of blended score (acoustic only — delivery never hard-rejects).
    if sc.snr_db < SNR_MIN_DB:
        return "reject"
    if sc.clipping_fraction > CLIP_SAMPLE_FRACTION_MAX:
        return "reject"
    if sc.duration < MIN_DURATION_S or sc.duration > MAX_DURATION_S:
        return "reject"
    if sc.sample_rate < MIN_SAMPLE_RATE:
        return "reject"
    score = sc.overall_score
    if score >= 75.0:
        return "keep"
    if score >= 55.0:
        return "review"
    return "reject"


def score_audio(audio: AudioData, path: str = "", target_text: str | None = None,
                with_mos: bool = True, with_transcript: bool = True,
                with_pitch: bool = True) -> Scorecard:
    sc = Scorecard(path=path)
    sc.duration = round(audio.duration, 3)
    sc.sample_rate = audio.sample_rate
    sc.channels = audio.channels
    sc.bits_per_sample = audio.bits_per_sample
    sc.integrated_lufs = integrated_lufs(audio)
    sc.true_peak_dbtp = round(true_peak_dbtp(audio), 2)
    sc.clipping_fraction = round(clipping_fraction(audio), 6)
    nf, snr = noise_floor_and_snr(audio)
    sc.noise_floor_dbfs = round(nf, 2)
    sc.snr_db = round(snr, 2)
    ratio, lead, tail = silence_analysis(audio)
    sc.silence_ratio = round(ratio, 3)
    sc.lead_trim_s = round(lead, 2)
    sc.tail_trim_s = round(tail, 2)
    sc.bandwidth_hz = round(spectral_rolloff_hz(audio), 1)
    sc.objective_score = _compute_objective_score(sc)

    # Loudness dynamics (always available, local).
    sc.loudness_dynamics_db = round(loudness_dynamics_db(audio), 2)

    # Transcription + word timestamps (graceful degrade) — feeds WPM + pauses + WER.
    words: list = []
    if with_transcript:
        try:
            from .transcribe import transcribe_detailed, word_error_rate
            text, words, backend = transcribe_detailed(audio)
            sc.transcript = text
            sc.transcript_backend = backend
            if target_text and text:
                sc.wer = round(word_error_rate(target_text, text), 4)
        except Exception as e:
            sc.transcript = ""
            sc.transcript_backend = f"error: {type(e).__name__}"

    # Pace + pause profile (uses word timestamps if present, else silence fallback).
    try:
        pp = pace_and_pauses(audio, words or None)
        sc.wpm = pp["wpm"]
        sc.articulation_wpm = pp["articulation_wpm"]
        sc.word_count = pp["word_count"]
        sc.pause_count = pp["pause_count"]
        sc.mean_pause_s = pp["mean_pause_s"]
        sc.pauses_per_min = pp["pauses_per_min"]
        sc.pace_backend = pp["backend"]
    except Exception as e:
        sc.pace_backend = f"error: {type(e).__name__}"

    # Pitch variation (librosa pyin; graceful degrade).
    if with_pitch:
        try:
            pv = pitch_variation(audio)
            sc.pitch_mean_hz = pv["mean_f0_hz"]
            sc.pitch_std_semitones = pv["f0_std_semitones"]
            sc.pitch_range_semitones = pv["pitch_range_semitones"]
            sc.pitch_backend = pv["backend"]
        except Exception as e:
            sc.pitch_backend = f"error: {type(e).__name__}"

    sc.delivery_score = _compute_delivery_score(sc)

    # Perceptual MOS (graceful degrade).
    if with_mos:
        try:
            from .mos import predict_mos
            mos_val, backend = predict_mos(audio)
            sc.mos = round(mos_val, 2) if mos_val is not None else None
            sc.mos_backend = backend
        except Exception as e:
            sc.mos = None
            sc.mos_backend = f"error: {type(e).__name__}"

    # Blend: acoustic + delivery, then fold in MOS if present.
    has_delivery = any(v is not None for v in
                       (sc.wpm, sc.pitch_std_semitones)) or sc.delivery_score > 0
    base = 0.75 * sc.objective_score + 0.25 * sc.delivery_score if has_delivery else sc.objective_score
    if sc.mos is not None:
        mos_pct = max(0.0, min(1.0, (sc.mos - 1.0) / 4.0)) * 100.0
        sc.overall_score = round(0.6 * base + 0.4 * mos_pct, 1)
    else:
        sc.overall_score = round(base, 1)

    sc.stars = _stars(sc.overall_score)
    sc.labels = _collect_labels(sc)
    sc.issues = _collect_issues(sc)
    sc.verdict = _verdict(sc)
    return sc


def score_file(path: str, target_text: str | None = None,
               with_mos: bool = True, with_transcript: bool = True,
               with_pitch: bool = True) -> Scorecard:
    audio = load_audio(path)
    return score_audio(audio, path=str(path), target_text=target_text,
                       with_mos=with_mos, with_transcript=with_transcript,
                       with_pitch=with_pitch)
