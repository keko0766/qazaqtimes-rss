#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install pyinstaller
fi

"$PYTHON_BIN" -m PyInstaller --clean --noconfirm GeoNewsBot.spec

echo "Built dist/GeoNewsBot.app"
