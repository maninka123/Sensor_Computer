#!/usr/bin/env bash
set -euo pipefail

WS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export ROSBAG=false
export ROSBRIDGE="${ROSBRIDGE:-true}"

exec "$WS_DIR/run_pipeline.sh" "$@"
