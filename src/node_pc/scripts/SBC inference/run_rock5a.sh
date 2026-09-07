#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "Run ./install_rock5a.sh first." >&2
  exit 1
fi

exec .venv/bin/python infer.py "$@"
