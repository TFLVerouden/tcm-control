#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-.venv/bin/python}"
TCM_UTILS_PATH="${1:-../tcm-utils}"

if [[ ! -d "$TCM_UTILS_PATH" ]]; then
  echo "Missing folder: $TCM_UTILS_PATH"
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "Python executable not found or not executable: $PYTHON"
  echo "Set PYTHON, e.g. PYTHON=.venv/bin/python ./scripts/dev_setup.sh"
  exit 1
fi

"$PYTHON" -m pip install -U pip
"$PYTHON" -m pip install -e "$TCM_UTILS_PATH"
"$PYTHON" -m pip install -e .

echo "Development environment ready."
