#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$SCRIPT_DIR"

echo "[pipeline] Sourcing workspace..."
if [ -f "$WS_DIR/devel/setup.bash" ]; then
  source "$WS_DIR/devel/setup.bash"
else
  echo "[pipeline] WARNING: devel/setup.bash not found; did you run catkin_make?"
fi

ROSBAG_MODE="${ROSBAG:-true}"

echo "[pipeline] Starting full pipeline launch (rosbag=${ROSBAG_MODE})"
echo "  - rosbag=true  : run shift/merge/colorize + tf republisher + imu filter + rosbridge"
echo "  - rosbag=false : also start livox_ros_driver and spinnaker_camera_driver"

exec roslaunch node_pc pipeline.launch rosbag:=${ROSBAG_MODE}
