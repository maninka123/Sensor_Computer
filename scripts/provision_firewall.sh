#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: sudo $0 <surface-subnet-CIDR> [--rosbridge]" >&2
  echo "Example: sudo $0 10.20.0.0/24 --rosbridge" >&2
}

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  usage
  exit 2
fi

SURFACE_SUBNET="$1"
OPEN_ROSBRIDGE=false
if [ "$#" -eq 2 ]; then
  if [ "$2" != "--rosbridge" ]; then
    usage
    exit 2
  fi
  OPEN_ROSBRIDGE=true
fi

if [ "${EUID}" -ne 0 ]; then
  echo "ERROR: run this script as root so it can update UFW." >&2
  exit 1
fi

python3 - "$SURFACE_SUBNET" <<'PY'
import ipaddress
import sys

try:
    network = ipaddress.ip_network(sys.argv[1], strict=False)
except ValueError as error:
    raise SystemExit("ERROR: invalid surface subnet: {}".format(error))
if network.version != 4:
    raise SystemExit("ERROR: the surface subnet must be IPv4")
PY

read -r EPHEMERAL_LOW EPHEMERAL_HIGH < /proc/sys/net/ipv4/ip_local_port_range
if ! [[ "$EPHEMERAL_LOW" =~ ^[0-9]+$ && "$EPHEMERAL_HIGH" =~ ^[0-9]+$ ]] || \
   [ "$EPHEMERAL_LOW" -lt 1 ] || [ "$EPHEMERAL_HIGH" -gt 65535 ] || \
   [ "$EPHEMERAL_LOW" -gt "$EPHEMERAL_HIGH" ]; then
  echo "ERROR: invalid kernel ephemeral port range." >&2
  exit 1
fi

echo "Allowing the surface subnet $SURFACE_SUBNET to reach this device:"
echo "  ROS Master: TCP 11311"
echo "  ROS dynamic ports: TCP ${EPHEMERAL_LOW}:${EPHEMERAL_HIGH}"
ufw allow proto tcp from "$SURFACE_SUBNET" to any port 11311 comment 'ROS Master from surface'
ufw allow proto tcp from "$SURFACE_SUBNET" to any port "${EPHEMERAL_LOW}:${EPHEMERAL_HIGH}" comment 'ROS TCPROS and XML-RPC from surface'

if [ "$OPEN_ROSBRIDGE" = true ]; then
  echo "  ROSBridge: TCP 9090"
  ufw allow proto tcp from "$SURFACE_SUBNET" to any port 9090 comment 'ROSBridge from surface'
fi

echo
ufw status verbose
echo "Rules are provisioned. This script does not enable or disable UFW."
