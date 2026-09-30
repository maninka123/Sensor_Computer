#!/usr/bin/env bash
set -euo pipefail

WS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NETWORK_CONFIG="${NODE_PC_NETWORK_CONFIG:-$WS_DIR/src/node_pc/config/network.env}"

if [[ ! -r "$NETWORK_CONFIG" ]]; then
  echo "[monitor] ERROR: network config is not readable: $NETWORK_CONFIG" >&2
  exit 1
fi

set +u
source /opt/ros/noetic/setup.bash
source "$WS_DIR/devel/setup.bash"
set -u

set -a
# shellcheck disable=SC1090
source "$NETWORK_CONFIG"
set +a

# rosrun exits with 75 when roscore restarts. Create a new ROS node so its
# subscriptions register with the new master; Ctrl-C and other exits stop.
while true; do
  set +e
  rosrun node_pc monitor_status.py "$@"
  monitor_status=$?
  set -e
  if (( monitor_status != 75 )); then
    exit "$monitor_status"
  fi
  echo "[monitor] ROS master changed; reconnecting in 2 seconds..." >&2
  sleep 2
done
