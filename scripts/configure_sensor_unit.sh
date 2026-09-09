#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  configure_sensor_unit.sh [--dry-run] PROFILE INTERFACE ROS_IP CAMERA_IP \
    LIVOX_HOST_IP LIVOX_IP CAMERA_SERIAL LIVOX_BROADCAST_CODE

Example for sensor unit 2:
  ./scripts/configure_sensor_unit.sh "ROS Sensor Unit 2" eth0 \
    10.20.0.31 10.20.0.32 192.168.1.51 192.168.1.126 \
    24519999 3JEDLB300XXXXXX

Run locally: activating the profile briefly interrupts wired networking.
The script calls sudo only for NetworkManager; network.env remains owned by
the invoking user. It records the sensor addresses but does not change the
Livox device IP. Commission Ethernet sensors one unit at a time.
EOF
}

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  shift
fi
if [[ "$#" -ne 8 ]]; then
  usage
  exit 2
fi

PROFILE=$1
INTERFACE=$2
DEVICE_ROS_IP=$3
CAMERA_IP=$4
LIVOX_HOST_IP=$5
LIVOX_DEVICE_IP=$6
CAMERA_SERIAL=$7
LIVOX_BROADCAST_CODE=$8

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
NETWORK_ENV="$WS_DIR/src/node_pc/config/network.env"

python3 - "$DEVICE_ROS_IP" "$CAMERA_IP" "$LIVOX_HOST_IP" "$LIVOX_DEVICE_IP" <<'PY'
import ipaddress
import sys

names = ("ROS_IP", "CAMERA_IP", "LIVOX_HOST_IP", "LIVOX_DEVICE_IP")
values = dict(zip(names, (ipaddress.ip_address(value) for value in sys.argv[1:])))
if any(value.version != 4 for value in values.values()):
    raise SystemExit("ERROR: all addresses must be IPv4")
if len(set(values.values())) != len(values):
    raise SystemExit("ERROR: every host and sensor address must be unique")
if values["ROS_IP"] not in ipaddress.ip_network(str(values["CAMERA_IP"]) + "/24", strict=False):
    raise SystemExit("ERROR: ROS_IP and CAMERA_IP must share a /24 subnet")
if values["LIVOX_HOST_IP"] not in ipaddress.ip_network(str(values["LIVOX_DEVICE_IP"]) + "/24", strict=False):
    raise SystemExit("ERROR: LIVOX_HOST_IP and LIVOX_DEVICE_IP must share a /24 subnet")
PY

if ! [[ "$CAMERA_SERIAL" =~ ^[0-9]+$ ]]; then
  echo "ERROR: CAMERA_SERIAL must contain digits only" >&2
  exit 2
fi
if ! [[ "$LIVOX_BROADCAST_CODE" =~ ^[[:alnum:]]{15}$ ]]; then
  echo "ERROR: LIVOX_BROADCAST_CODE must be exactly 15 letters/numbers" >&2
  exit 2
fi
if ! ip link show "$INTERFACE" >/dev/null 2>&1; then
  echo "ERROR: network interface does not exist: $INTERFACE" >&2
  exit 2
fi

echo "Sensor computer: $DEVICE_ROS_IP/24 (also its ROS master)"
echo "FLIR camera:     $CAMERA_IP/24"
echo "Livox host IP:   $LIVOX_HOST_IP/24"
echo "Livox device:    $LIVOX_DEVICE_IP/24"
echo "Profile/device:  $PROFILE / $INTERFACE"

if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run: no files or network settings changed."
  exit 0
fi

if nmcli -t -f NAME connection show | grep -Fxq "$PROFILE"; then
  sudo nmcli connection modify "$PROFILE" connection.interface-name "$INTERFACE"
else
  sudo nmcli connection add type ethernet ifname "$INTERFACE" con-name "$PROFILE"
fi
sudo nmcli connection modify "$PROFILE" \
  ipv4.method manual \
  ipv4.addresses "$DEVICE_ROS_IP/24,$LIVOX_HOST_IP/24" \
  ipv4.gateway "" \
  ipv4.never-default yes \
  connection.autoconnect yes \
  connection.autoconnect-priority 100

python3 - "$NETWORK_ENV" <<PY
from pathlib import Path
import os
import tempfile

path = Path(os.sys.argv[1])
updates = {
    "ROS_IP": "$DEVICE_ROS_IP",
    "ROS_MASTER_URI": "http://$DEVICE_ROS_IP:11311",
    "FLIR_CAMERA_SERIAL": "$CAMERA_SERIAL",
    "FLIR_CAMERA_IP": "$CAMERA_IP",
    "LIVOX_HOST_IP": "$LIVOX_HOST_IP",
    "LIVOX_DEVICE_IP": "$LIVOX_DEVICE_IP",
    "LIVOX_BROADCAST_CODE": "$LIVOX_BROADCAST_CODE",
}
lines = path.read_text().splitlines()
seen = set()
result = []
for line in lines:
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else ""
    if key in updates:
        result.append(key + "=" + updates[key])
        seen.add(key)
    else:
        result.append(line)
for key, value in updates.items():
    if key not in seen:
        result.append(key + "=" + value)
fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent), text=True)
try:
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(result) + "\n")
    os.chmod(temporary, path.stat().st_mode)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY

sudo nmcli connection up "$PROFILE"

echo
echo "Host and network.env configured. Next:"
echo "  1. Set FLIR $CAMERA_SERIAL persistent IP to $CAMERA_IP/24."
echo "  2. Set Livox $LIVOX_BROADCAST_CODE static IP to $LIVOX_DEVICE_IP/24."
echo "  3. Run: $WS_DIR/check_hardware.sh"
echo "  4. Run: $WS_DIR/run_hardware.sh"
