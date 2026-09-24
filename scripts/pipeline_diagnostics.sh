#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
NETWORK_CONFIG="${NODE_PC_NETWORK_CONFIG:-$WS_DIR/src/node_pc/config/network.env}"

set -a
# shellcheck disable=SC1090
source "$NETWORK_CONFIG"
set +a
set +u
source /opt/ros/noetic/setup.bash
# shellcheck disable=SC1091
source "$WS_DIR/devel/setup.bash"
set -u

echo "=== Pipeline diagnostics: $(date --iso-8601=seconds) ==="
echo
echo "--- Service ---"
systemctl status node-pc.service --no-pager -l 2>&1 | head -n 35
echo
echo "--- Transport services ---"
systemctl status node-pc-rosbridge.service --no-pager -l 2>&1 | head -n 20
systemctl status node-pc-transport-supervisor.service --no-pager -l 2>&1 | head -n 20
echo
echo "--- Active client transport ---"
if [[ -r "${TRANSPORT_STATUS_FILE:-/run/node-pc-transport-status.json}" ]]; then
  cat "${TRANSPORT_STATUS_FILE:-/run/node-pc-transport-status.json}"
else
  echo "Transport supervisor status is not available."
fi
echo
echo "--- Network addresses ---"
ip -4 -o address show 2>&1
echo
echo "--- Sensor routes ---"
ip route get "${FLIR_CAMERA_IP:-missing}" 2>&1
ip route get "${LIVOX_DEVICE_IP:-missing}" 2>&1
echo
echo "--- ROS nodes ---"
timeout 5 rosnode list 2>&1
echo
echo "--- Live topic rates (five-second samples) ---"
for topic in /camera/image_raw /livox/lidar /livox/lidar_filtered /merged_colored_cloud; do
  echo "[$topic]"
  timeout 5 rostopic hz -w 20 "$topic" 2>&1 | tail -n 4
done
echo
echo "--- Recent service log ---"
if sudo -n true 2>/dev/null; then
  sudo -n journalctl -u node-pc.service -u node-pc-rosbridge.service \
    -u node-pc-transport-supervisor.service -n 100 --no-pager -q
else
  journalctl -u node-pc.service -u node-pc-rosbridge.service \
    -u node-pc-transport-supervisor.service -n 100 --no-pager -q 2>&1
  echo "[diagnostics] If logs are incomplete, rerun this command with sudo."
fi
