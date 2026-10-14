#!/usr/bin/env bash
# Reproduce the three runs from the blog post. Starts from an empty history.
set -u
cd "$(dirname "$0")"
rm -rf runs
python3 gate.py --agent baseline --accept;  echo "exit=$?"; echo
python3 gate.py --agent new-model;          echo "exit=$?"; echo
python3 gate.py --agent new-prompt;         echo "exit=$?"
