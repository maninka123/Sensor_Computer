#!/usr/bin/env bash
set -euo pipefail

WS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/noetic/setup.bash
[[ -r "$WS_DIR/devel/setup.bash" ]] && source "$WS_DIR/devel/setup.bash"
[[ -r "$WS_DIR/src/node_pc/config/network.env" ]] && source "$WS_DIR/src/node_pc/config/network.env"

echo "Architecture: $(uname -m)"
echo "ROS: ${ROS_DISTRO:-not sourced}"
echo "Spinnaker: $(dpkg-query -W -f='${Version}' libspinnaker 2>/dev/null || echo missing)"
echo "Livox driver: $(rospack find livox_ros_driver 2>/dev/null || echo missing)"
echo "FLIR driver: $(rospack find spinnaker_camera_driver 2>/dev/null || echo missing)"
echo "USB buffer: $(cat /sys/module/usbcore/parameters/usbfs_memory_mb 2>/dev/null || echo unavailable) MB"
echo "Network interfaces:"
ip -br address
if [[ -n "${ROS_IP:-}" ]] && ! ip -4 -o address show | rg -q "[[:space:]]${ROS_IP}/"; then
  echo "WARNING: configured ROS_IP $ROS_IP is not assigned to this computer" >&2
fi
if [[ -n "${LIVOX_HOST_IP:-}" ]] && ! ip -4 -o address show | rg -q "[[:space:]]${LIVOX_HOST_IP}/"; then
  echo "WARNING: configured LIVOX_HOST_IP $LIVOX_HOST_IP is not assigned to this computer" >&2
fi
echo "USB devices:"
lsusb || true

if command -v timeout >/dev/null && [[ -x /opt/spinnaker/bin/Enumeration ]]; then
  echo "FLIR enumeration:"
  timeout 10 /opt/spinnaker/bin/Enumeration || true
fi

if [[ -n "${FLIR_CAMERA_IP:-}" ]]; then
  echo "FLIR reachability ($FLIR_CAMERA_IP):"
  ping -c 1 -W 1 "$FLIR_CAMERA_IP" || true
fi

if [[ -n "${LIVOX_DEVICE_IP:-}" ]]; then
  echo "Livox reachability ($LIVOX_DEVICE_IP):"
  ping -c 1 -W 1 "$LIVOX_DEVICE_IP" || true
fi

if command -v timeout >/dev/null && [[ -x /opt/spinnaker/bin/GigEConfig ]] \
   && [[ -n "${FLIR_CAMERA_SERIAL:-}" ]]; then
  echo "FLIR network configuration:"
  camera_info="$(timeout 10 /opt/spinnaker/bin/GigEConfig -s "$FLIR_CAMERA_SERIAL" 2>&1 || true)"
  printf '%s\n' "$camera_info"
  if [[ -n "${FLIR_CAMERA_IP:-}" ]] \
     && ! printf '%s\n' "$camera_info" | rg -q "GevDeviceIPAddress : ${FLIR_CAMERA_IP}$"; then
    echo "WARNING: FLIR camera $FLIR_CAMERA_SERIAL is not using expected IP $FLIR_CAMERA_IP" >&2
  fi
fi
