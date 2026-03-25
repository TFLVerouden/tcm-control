#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f .gitmodules ]]; then
  echo "No .gitmodules found. Run from the twente-cough-machine repository root."
  exit 1
fi

echo "Syncing and initializing submodules..."
git submodule sync --recursive
git submodule update --init --recursive

echo "Installing Python packages in editable mode (best effort)..."
if [[ -d utils ]]; then
  python -m pip install -e ./utils
fi
if [[ -d control ]]; then
  python -m pip install -e ./control
fi

echo "Done. Open twente-cough-machine.code-workspace in VS Code."
