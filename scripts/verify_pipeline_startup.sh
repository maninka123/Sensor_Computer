#!/usr/bin/env bash
set -euo pipefail

TIMEOUT_SECONDS="${1:-90}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
NETWORK_CONFIG="${NODE_PC_NETWORK_CONFIG:-$WS_DIR/src/node_pc/config/network.env}"

if [[ ! "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || (( TIMEOUT_SECONDS < 15 )); then
  echo "[startup-check] ERROR: timeout must be an integer of at least 15 seconds" >&2
  exit 2
fi
if [[ ! -r "$NETWORK_CONFIG" || ! -r "$WS_DIR/devel/setup.bash" ]]; then
  echo "[startup-check] ERROR: network config or built workspace setup is missing" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$NETWORK_CONFIG"
set +a
set +u
source /opt/ros/noetic/setup.bash
# shellcheck disable=SC1091
source "$WS_DIR/devel/setup.bash"
set -u

deadline=$((SECONDS + TIMEOUT_SECONDS))

wait_for_message() {
  local topic="$1"
  local label="$2"
  while (( SECONDS < deadline )); do
    if timeout 5 rostopic echo -n 1 "$topic" >/dev/null 2>&1; then
      echo "[startup-check] OK: $label is publishing on $topic"
      return 0
    fi
    echo "[startup-check] Waiting for $label on $topic..."
  done
  echo "[startup-check] ERROR: no $label message on $topic within ${TIMEOUT_SECONDS}s" >&2
  return 1
}

echo "[startup-check] Verifying live data before declaring boot successful..."
wait_for_message /camera/image_raw/header "camera"
wait_for_message /livox/lidar/header "LiDAR"
wait_for_message /merged_colored_cloud/header "colourised point cloud"
echo "[startup-check] PASS: camera, LiDAR, and fused output are live"
