#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SERVICE_SOURCE="$WS_DIR/deploy/node-pc.service"
SERVICE_TARGET="/etc/systemd/system/node-pc.service"

if [[ ! -r "$SERVICE_SOURCE" ]]; then
  echo "ERROR: service file not found: $SERVICE_SOURCE" >&2
  exit 1
fi

sudo install -m 0644 "$SERVICE_SOURCE" "$SERVICE_TARGET"
sudo systemctl daemon-reload
sudo systemctl enable node-pc.service

echo "node-pc.service is enabled for the next boot."
echo "It was not started now. Reboot when ready, then run:"
echo "  systemctl status node-pc.service"
echo "  $WS_DIR/monitor_pipeline.sh"
echo "  $WS_DIR/scripts/pipeline_diagnostics.sh"
