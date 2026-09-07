#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

RAW_TOPIC="${RAW_TOPIC:-/camera/image_raw}"
ENH_TOPIC="${ENH_TOPIC:-/camera/image_enhanced}"
TOGGLE_TOPIC="${TOGGLE_TOPIC:-/image_enhancement}"
TARGET_H="${TARGET_H:-480}"
WINDOW_NAME="${WINDOW_NAME:-Raw vs Enhanced}"

RVIZ_CFG="$SCRIPT_DIR/pipeline_visual_debug.rviz"
COMPARE_SCRIPT="$SCRIPT_DIR/compare_image_streams.py"

if ! command -v rviz >/dev/null 2>&1; then
  echo "[visual-debug] rviz not found. Source ROS first." >&2
  exit 1
fi

if [ ! -f "$COMPARE_SCRIPT" ]; then
  echo "[visual-debug] Missing compare script: $COMPARE_SCRIPT" >&2
  exit 1
fi

source /opt/ros/noetic/setup.bash
if [ -f "$WS_DIR/devel/setup.bash" ]; then
  source "$WS_DIR/devel/setup.bash"
fi

cleanup() {
  if [ -n "${CMP_PID:-}" ] && kill -0 "$CMP_PID" 2>/dev/null; then
    kill "$CMP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[visual-debug] Starting side-by-side image viewer"
python3 "$COMPARE_SCRIPT" \
  _raw_topic:="$RAW_TOPIC" \
  _enhanced_topic:="$ENH_TOPIC" \
  _toggle_topic:="$TOGGLE_TOPIC" \
  _target_height:="$TARGET_H" \
  _window_name:="$WINDOW_NAME" &
CMP_PID=$!

echo "[visual-debug] Starting RViz with $RVIZ_CFG"
rviz -d "$RVIZ_CFG"
