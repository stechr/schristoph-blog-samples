#!/usr/bin/env bash
# Start the Fair Rating Explorer on http://localhost:${PORT:-8765}
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "Please install uv: https://docs.astral.sh/uv/"; exit 1; }
exec uv run --with playwright python -u server.py
