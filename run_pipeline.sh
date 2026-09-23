#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$SCRIPT_DIR"
NETWORK_CONFIG="${NODE_PC_NETWORK_CONFIG:-$WS_DIR/src/node_pc/config/network.env}"

# PyTorch 1.12 on this ARM board otherwise fails with "cannot allocate memory
# in static TLS block" when ROS loads other shared libraries first.
SYSTEM_GOMP=/usr/lib/aarch64-linux-gnu/libgomp.so.1
if [[ -r "$SYSTEM_GOMP" && ":${LD_PRELOAD:-}:" != *":$SYSTEM_GOMP:"* ]]; then
  export LD_PRELOAD="$SYSTEM_GOMP${LD_PRELOAD:+:$LD_PRELOAD}"
fi

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
# ROS/catkin setup scripts probe variables that may legitimately be unset in a
# clean systemd environment. Temporarily disable nounset only while sourcing
# them, then restore strict mode for this wrapper.
set +u
source /opt/ros/noetic/setup.bash
if [[ ! -r "$WS_DIR/devel/setup.bash" ]]; then
  echo "[pipeline] ERROR: $WS_DIR/devel/setup.bash is missing." >&2
  echo "[pipeline] Build the workspace with: cd $WS_DIR && catkin_make" >&2
  exit 1
fi
source "$WS_DIR/devel/setup.bash"
set -u

required_executables=(
  "$WS_DIR/devel/lib/node_pc/lidar_timestamp_shift_node"
  "$WS_DIR/devel/lib/node_pc/pointcloud_merge_node"
  "$WS_DIR/devel/lib/node_pc/pointcloud_voxel_filter_node"
  "$WS_DIR/devel/lib/node_pc/pointcloud_colorize_node"
)
for executable in "${required_executables[@]}"; do
  if [[ ! -x "$executable" ]]; then
    echo "[pipeline] ERROR: required executable is missing: $executable" >&2
    echo "[pipeline] Rebuild the workspace with: cd $WS_DIR && catkin_make" >&2
    exit 1
  fi
done

ROSBAG_MODE="${ROSBAG:-false}"
ROSBRIDGE_MODE="${ROSBRIDGE:-true}"
ROSBRIDGE_ADDRESS="${ROSBRIDGE_ADDRESS:-0.0.0.0}"
ROSBRIDGE_PORT="${ROSBRIDGE_PORT:-9090}"
PIPELINE_RESTART_DELAY="${PIPELINE_RESTART_DELAY:-10}"

if [[ ! "$ROSBRIDGE_PORT" =~ ^[0-9]+$ ]] || (( ROSBRIDGE_PORT < 1 || ROSBRIDGE_PORT > 65535 )); then
  echo "[pipeline] ERROR: ROSBRIDGE_PORT must be between 1 and 65535" >&2
  exit 1
fi
if [[ ! "$PIPELINE_RESTART_DELAY" =~ ^[0-9]+$ ]] || (( PIPELINE_RESTART_DELAY < 1 )); then
  echo "[pipeline] ERROR: PIPELINE_RESTART_DELAY must be a positive integer" >&2
  exit 1
fi

echo "[pipeline] Network: ROS_IP=${ROS_IP}, ROS_MASTER_URI=${ROS_MASTER_URI}"
echo "[pipeline] ROSBridge: ws://${ROS_IP}:${ROSBRIDGE_PORT} (bind ${ROSBRIDGE_ADDRESS})"
echo "[pipeline] Starting full pipeline launch (rosbag=${ROSBAG_MODE}, rosbridge=${ROSBRIDGE_MODE})"
echo "  - rosbag=false : start the Livox/FLIR drivers and the processing pipeline"
echo "  - rosbag=true  : skip sensor drivers; raw topics come from rosbag playback"
echo "  - rosbridge=true: also start rosbridge and the TF web republisher"

# roslaunch returns success when a required child exits cleanly. That would
# leave an older Restart=on-failure systemd unit inactive, even though the
# sensor pipeline is gone. Supervise roslaunch here as a second recovery layer
# so both old and newly installed service units recover from child-node exits.
shutdown_requested=false
child_pid=""
request_shutdown() {
  shutdown_requested=true
  if [[ -n "$child_pid" ]]; then
    kill -INT "$child_pid" 2>/dev/null || true
  fi
}
trap request_shutdown INT TERM

while true; do
  echo "[pipeline] Launching ROS pipeline..."
  set +e
  roslaunch node_pc pipeline.launch \
    rosbag:="${ROSBAG_MODE}" \
    rosbridge:="${ROSBRIDGE_MODE}" \
    rosbridge_address:="${ROSBRIDGE_ADDRESS}" \
    rosbridge_port:="${ROSBRIDGE_PORT}" \
    ros_ip:="${ROS_IP}" \
    ros_master_uri:="${ROS_MASTER_URI}" \
    "$@" &
  child_pid=$!
  wait "$child_pid"
  launch_status=$?
  set -e
  child_pid=""

  if [[ "$shutdown_requested" == true ]]; then
    echo "[pipeline] Shutdown requested; not restarting"
    exit 0
  fi

  echo "[pipeline] ERROR: roslaunch exited with status $launch_status; restarting in ${PIPELINE_RESTART_DELAY}s" >&2
  sleep "$PIPELINE_RESTART_DELAY" &
  child_pid=$!
  set +e
  wait "$child_pid"
  set -e
  child_pid=""
  if [[ "$shutdown_requested" == true ]]; then
    echo "[pipeline] Shutdown requested during restart delay"
    exit 0
  fi
done
