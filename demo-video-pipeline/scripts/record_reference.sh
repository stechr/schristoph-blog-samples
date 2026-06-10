#!/usr/bin/env bash
# record_reference.sh — capture a short voice reference clip for Qwen3-TTS voice cloning.
#
# Records ~10–30s of clear speech to ref_audio.wav (mono, 16 kHz — what the cloning model
# expects). Uses ffmpeg's avfoundation input on macOS, or sox if present. The resulting
# ref_audio.wav is then transcribed by scripts/transcribe_reference.py to produce the exact
# transcript voice_clone needs.
#
# Usage:
#   bash scripts/record_reference.sh                 # 20s default, → ref_audio.wav
#   bash scripts/record_reference.sh 30              # record 30 seconds
#   bash scripts/record_reference.sh 20 my_ref.wav   # custom duration + output path
#
# QuickTime fallback (no command-line recording): record audio in QuickTime Player
# (File → New Audio Recording → record → stop), then File → Export As → Audio Only to get a
# .m4a/.wav, and point the transcribe step at that file:
#   .venv/bin/python scripts/transcribe_reference.py --audio ~/path/to/quicktime-export.wav
set -euo pipefail
export PATH="/usr/local/bin:$PATH"

DURATION="${1:-20}"
OUT="${2:-ref_audio.wav}"

echo "=== Voice reference recorder ==="
echo "Will record ${DURATION}s of audio to: ${OUT}"
echo "Speak naturally and clearly — read a few sentences in your normal pace."
echo

have() { command -v "$1" >/dev/null 2>&1; }

if have ffmpeg; then
  OS="$(uname -s)"
  if [ "$OS" = "Darwin" ]; then
    echo "Available macOS audio input devices (look for your microphone index):"
    # avfoundation lists devices on stderr; this is informational, the ':0' default usually = built-in mic
    ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | grep -iE "audio|microphone" || true
    echo
    MIC_INDEX="${MIC_INDEX:-0}"
    echo "Recording from audio device :${MIC_INDEX} (override with MIC_INDEX=N). Starting in 2s..."
    sleep 2
    echo ">>> RECORDING — speak now <<<"
    ffmpeg -hide_banner -loglevel warning -f avfoundation -i ":${MIC_INDEX}" \
      -t "${DURATION}" -ac 1 -ar 16000 -y "${OUT}"
  else
    # Linux / other: ALSA default capture device
    echo ">>> RECORDING — speak now (${DURATION}s) <<<"
    ffmpeg -hide_banner -loglevel warning -f alsa -i default \
      -t "${DURATION}" -ac 1 -ar 16000 -y "${OUT}"
  fi
elif have rec; then
  # sox 'rec'
  echo ">>> RECORDING — speak now (${DURATION}s) <<<"
  rec -c 1 -r 16000 "${OUT}" trim 0 "${DURATION}"
else
  echo "ERROR: neither ffmpeg nor sox ('rec') found on PATH." >&2
  echo "Install ffmpeg (brew install ffmpeg), or record in QuickTime Player and export a .wav," >&2
  echo "then run: .venv/bin/python scripts/transcribe_reference.py --audio your-clip.wav" >&2
  exit 1
fi

echo
echo "Saved reference clip → ${OUT}"
echo "Next: transcribe it to its exact words —"
echo "  .venv/bin/python scripts/transcribe_reference.py --audio ${OUT} --out ref_text.txt"
