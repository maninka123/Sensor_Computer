#!/usr/bin/env bash
set -euo pipefail

ROSBRIDGE_MODE="${ROSBRIDGE:-true}"
ROSBRIDGE_PORT="${ROSBRIDGE_PORT:-9090}"
LINK_DELAY="${LINK_DELAY:-5ms}"
LINK_RATE="${LINK_RATE:-25mbit}"
LINK_LOSS="${LINK_LOSS:-0.1%}"

if [ -r "${NODE_PC_NETWORK_CONFIG:-}" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$NODE_PC_NETWORK_CONFIG"
  set +a
fi

: "${ROS_IP:?ROS_IP must be set by the per-device env file}"
: "${ROS_MASTER_URI:?ROS_MASTER_URI must be set by the per-device env file}"

if [ -r /catkin_ws/devel/setup.bash ]; then
  # Use an existing mounted workspace build when available. The synthetic
  # publisher itself can also be found directly in the source package.
  # shellcheck disable=SC1091
  source /catkin_ws/devel/setup.bash
fi

# Start with a constrained 25 Mb/s link rather than an unrealistically perfect
# Docker bridge. docker/shape_link.sh can replace or clear this qdisc later.
tc qdisc replace dev eth0 root netem \
  delay "$LINK_DELAY" \
  rate "$LINK_RATE" \
  loss "$LINK_LOSS"

echo "[device] ROS_IP=${ROS_IP} Master=${ROS_MASTER_URI}"
echo "[device] link delay=${LINK_DELAY} rate=${LINK_RATE} loss=${LINK_LOSS}"

# --wait keeps the container alive and retries until the single surface Master
# is available. It does not create an accidental per-device Master.
exec roslaunch --wait node_pc container_test.launch \
  rosbridge:="$ROSBRIDGE_MODE" \
  rosbridge_port:="$ROSBRIDGE_PORT" \
  ros_ip:="$ROS_IP" \
  ros_master_uri:="$ROS_MASTER_URI"
