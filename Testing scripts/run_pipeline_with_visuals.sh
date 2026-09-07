#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

source /opt/ros/noetic/setup.bash
if [ -f "$WS_DIR/devel/setup.bash" ]; then
  source "$WS_DIR/devel/setup.bash"
fi

cleanup() {
  if [ -n "${PIPE_PID:-}" ] && kill -0 "$PIPE_PID" 2>/dev/null; then
    kill "$PIPE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[pipeline+visuals] Starting pipeline..."
"$WS_DIR/run_pipeline.sh" &
PIPE_PID=$!

sleep 3

echo "[pipeline+visuals] Starting visual debug windows..."
"$SCRIPT_DIR/run_visual_debug.sh"
