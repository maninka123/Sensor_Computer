#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SERVICE_SOURCE="$WS_DIR/deploy/node-pc.service"
SERVICE_TARGET="/etc/systemd/system/node-pc.service"
LOG_CLEANUP_SERVICE_SOURCE="$WS_DIR/deploy/node-pc-log-cleanup.service"
LOG_CLEANUP_TIMER_SOURCE="$WS_DIR/deploy/node-pc-log-cleanup.timer"
ROSBRIDGE_SERVICE_SOURCE="$WS_DIR/deploy/node-pc-rosbridge.service"
TRANSPORT_SERVICE_SOURCE="$WS_DIR/deploy/node-pc-transport-supervisor.service"
TRANSPORT_SCRIPT_SOURCE="$WS_DIR/scripts/transport_supervisor.py"
TRANSPORT_ENV_SOURCE="$WS_DIR/src/node_pc/config/network.env"

for required in "$SERVICE_SOURCE" "$ROSBRIDGE_SERVICE_SOURCE" \
  "$TRANSPORT_SERVICE_SOURCE" "$LOG_CLEANUP_SERVICE_SOURCE" \
  "$LOG_CLEANUP_TIMER_SOURCE" "$TRANSPORT_SCRIPT_SOURCE" \
  "$TRANSPORT_ENV_SOURCE"; do
  if [[ ! -r "$required" ]]; then
    echo "ERROR: deployment file not found: $required" >&2
    exit 1
  fi
done

sudo install -m 0644 "$SERVICE_SOURCE" "$SERVICE_TARGET"
sudo install -m 0644 "$ROSBRIDGE_SERVICE_SOURCE" /etc/systemd/system/node-pc-rosbridge.service
sudo install -m 0644 "$TRANSPORT_SERVICE_SOURCE" /etc/systemd/system/node-pc-transport-supervisor.service
sudo install -d -m 0755 /usr/local/lib/node-pc /etc/node-pc
sudo install -m 0755 "$TRANSPORT_SCRIPT_SOURCE" /usr/local/lib/node-pc/transport_supervisor.py
sudo install -m 0644 "$TRANSPORT_ENV_SOURCE" /etc/node-pc/transport.env
sudo install -m 0644 "$LOG_CLEANUP_SERVICE_SOURCE" /etc/systemd/system/node-pc-log-cleanup.service
sudo install -m 0644 "$LOG_CLEANUP_TIMER_SOURCE" /etc/systemd/system/node-pc-log-cleanup.timer
sudo systemctl daemon-reload
sudo systemctl enable node-pc.service node-pc-rosbridge.service \
  node-pc-transport-supervisor.service node-pc-log-cleanup.timer

echo "node-pc.service is enabled for the next boot."
echo "ROSBridge fallback and automatic TCPROS transport selection are enabled."
echo "ROS logs older than 90 days will be cleaned at startup and daily."
echo "It was not started now. Reboot when ready, then run:"
echo "  systemctl status node-pc.service"
echo "  systemctl status node-pc-rosbridge.service node-pc-transport-supervisor.service"
echo "  $WS_DIR/monitor_pipeline.sh"
echo "  $WS_DIR/scripts/pipeline_diagnostics.sh"
