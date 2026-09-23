#!/usr/bin/env bash
set -euo pipefail

WS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
NETWORK_CONFIG="${NODE_PC_NETWORK_CONFIG:-$WS_DIR/src/node_pc/config/network.env}"

if [[ ! -r "$NETWORK_CONFIG" ]]; then
  echo "[monitor] ERROR: network config is not readable: $NETWORK_CONFIG" >&2
  exit 1
fi

source /opt/ros/noetic/setup.bash
source "$WS_DIR/devel/setup.bash"

set -a
# shellcheck disable=SC1090
source "$NETWORK_CONFIG"
set +a

exec rosrun node_pc monitor_status.py "$@"
