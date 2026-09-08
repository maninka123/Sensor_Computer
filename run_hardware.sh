#!/usr/bin/env bash
set -euo pipefail

WS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export ROSBAG=false
export ROSBRIDGE="${ROSBRIDGE:-true}"

# PyTorch 1.12 on this ARM board must load the system OpenMP runtime first.
SYSTEM_GOMP=/usr/lib/aarch64-linux-gnu/libgomp.so.1
if [[ -r "$SYSTEM_GOMP" ]]; then
  export LD_PRELOAD="$SYSTEM_GOMP${LD_PRELOAD:+:$LD_PRELOAD}"
fi

exec "$WS_DIR/run_pipeline.sh" "$@"
