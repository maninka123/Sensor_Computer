#!/usr/bin/env bash
set -euo pipefail

WS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/noetic/setup.bash
[[ -r "$WS_DIR/devel/setup.bash" ]] && source "$WS_DIR/devel/setup.bash"

echo "Architecture: $(uname -m)"
echo "ROS: ${ROS_DISTRO:-not sourced}"
echo "Spinnaker: $(dpkg-query -W -f='${Version}' libspinnaker 2>/dev/null || echo missing)"
echo "Livox driver: $(rospack find livox_ros_driver 2>/dev/null || echo missing)"
echo "FLIR driver: $(rospack find spinnaker_camera_driver 2>/dev/null || echo missing)"
echo "USB buffer: $(cat /sys/module/usbcore/parameters/usbfs_memory_mb 2>/dev/null || echo unavailable) MB"
echo "Network interfaces:"
ip -br address
echo "USB devices:"
lsusb || true

if command -v timeout >/dev/null && [[ -x /opt/spinnaker/bin/Enumeration ]]; then
  echo "FLIR enumeration:"
  timeout 10 /opt/spinnaker/bin/Enumeration || true
fi
