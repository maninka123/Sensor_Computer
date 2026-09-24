#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NETWORK_CONFIG="${NODE_PC_NETWORK_CONFIG:-$SCRIPT_DIR/src/node_pc/config/network.env}"

if [[ ! -r "$NETWORK_CONFIG" ]]; then
  echo "[rosbridge] ERROR: network config is not readable: $NETWORK_CONFIG" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$NETWORK_CONFIG"
set +a

set +u
source /opt/ros/noetic/setup.bash
source "$SCRIPT_DIR/devel/setup.bash"
set -u

# Do not let this separate launch create a competing ROS master during boot.
deadline=$((SECONDS + 90))
until rosnode list >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "[rosbridge] ERROR: ROS master was not ready within 90 seconds" >&2
    exit 1
  fi
  sleep 2
done

echo "[rosbridge] Starting fallback WebSocket transport on ${ROSBRIDGE_ADDRESS:-0.0.0.0}:${ROSBRIDGE_PORT:-9090}"
exec roslaunch node_pc rosbridge.launch \
  address:="${ROSBRIDGE_ADDRESS:-0.0.0.0}" \
  port:="${ROSBRIDGE_PORT:-9090}"
