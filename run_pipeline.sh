#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$SCRIPT_DIR"
NETWORK_CONFIG="${NODE_PC_NETWORK_CONFIG:-$WS_DIR/src/node_pc/config/network.env}"

if [ ! -r "$NETWORK_CONFIG" ]; then
  echo "[pipeline] ERROR: network config is not readable: $NETWORK_CONFIG" >&2
  exit 1
fi

# network.env is the canonical source for these variables for both interactive
# and service starts. Export every assignment while loading it.
set -a
# shellcheck disable=SC1090
source "$NETWORK_CONFIG"
set +a

if ! python3 - "${ROS_IP:-}" <<'PY'
import ipaddress
import sys

try:
    address = ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if address.version == 4 else 1)
PY
then
  echo "[pipeline] ERROR: ROS_IP must be a literal IPv4 address in $NETWORK_CONFIG" >&2
  exit 1
fi
if [[ ! "${ROS_MASTER_URI:-}" =~ ^http://[^/]+:[0-9]+/?$ ]]; then
  echo "[pipeline] ERROR: ROS_MASTER_URI is invalid in $NETWORK_CONFIG" >&2
  exit 1
fi

echo "[pipeline] Sourcing workspace..."
if [ -f "$WS_DIR/devel/setup.bash" ]; then
  source "$WS_DIR/devel/setup.bash"
else
  echo "[pipeline] WARNING: devel/setup.bash not found; did you run catkin_make?"
fi

ROSBAG_MODE="${ROSBAG:-true}"
ROSBRIDGE_MODE="${ROSBRIDGE:-true}"
ROSBRIDGE_ADDRESS="${ROSBRIDGE_ADDRESS:-0.0.0.0}"
ROSBRIDGE_PORT="${ROSBRIDGE_PORT:-9090}"

if [[ ! "$ROSBRIDGE_PORT" =~ ^[0-9]+$ ]] || (( ROSBRIDGE_PORT < 1 || ROSBRIDGE_PORT > 65535 )); then
  echo "[pipeline] ERROR: ROSBRIDGE_PORT must be between 1 and 65535" >&2
  exit 1
fi

echo "[pipeline] Network: ROS_IP=${ROS_IP}, ROS_MASTER_URI=${ROS_MASTER_URI}"
echo "[pipeline] ROSBridge: ws://${ROS_IP}:${ROSBRIDGE_PORT} (bind ${ROSBRIDGE_ADDRESS})"
echo "[pipeline] Starting full pipeline launch (rosbag=${ROSBAG_MODE}, rosbridge=${ROSBRIDGE_MODE})"
echo "  - rosbag=true  : run shift/merge/colorize + imu filter"
echo "  - rosbag=false : also start livox_ros_driver and spinnaker_camera_driver"
echo "  - rosbridge=true: also start rosbridge and the TF web republisher"

exec roslaunch node_pc pipeline.launch \
  rosbag:="${ROSBAG_MODE}" \
  rosbridge:="${ROSBRIDGE_MODE}" \
  rosbridge_address:="${ROSBRIDGE_ADDRESS}" \
  rosbridge_port:="${ROSBRIDGE_PORT}" \
  ros_ip:="${ROS_IP}" \
  ros_master_uri:="${ROS_MASTER_URI}"
