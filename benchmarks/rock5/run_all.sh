#!/usr/bin/env bash
set -euo pipefail

BENCH_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd -- "$BENCH_DIR/../.." && pwd)"
SHORT_SECONDS=60
WARMUP_SECONDS=20
STABILITY_SECONDS=1800
OUTPUT="$BENCH_DIR/results/$(date +%Y-%m-%d).json"
MAX_TEMPERATURE=80
START_TEMPERATURE=70
ENHANCED_FIRST=false
SKIP_ENHANCEMENT=false
SKIP_STABILITY=false

usage() {
  echo "Usage: $0 [--duration SECONDS] [--warmup SECONDS] [--stability-seconds SECONDS] [--start-temperature CELSIUS] [--max-temperature CELSIUS] [--enhanced-first] [--skip-enhancement] [--skip-stability] [--output FILE]"
}
while (( $# )); do
  case "$1" in
    --duration) SHORT_SECONDS="$2"; shift 2 ;;
    --warmup) WARMUP_SECONDS="$2"; shift 2 ;;
    --stability-seconds) STABILITY_SECONDS="$2"; shift 2 ;;
    --start-temperature) START_TEMPERATURE="$2"; shift 2 ;;
    --enhanced-first) ENHANCED_FIRST=true; shift ;;
    --skip-enhancement) SKIP_ENHANCEMENT=true; shift ;;
    --skip-stability) SKIP_STABILITY=true; shift ;;
    --max-temperature) MAX_TEMPERATURE="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
for value in "$SHORT_SECONDS" "$WARMUP_SECONDS" "$STABILITY_SECONDS"; do
  [[ "$value" =~ ^[0-9]+$ ]] || { echo "Durations must be non-negative integer seconds" >&2; exit 2; }
done
(( SHORT_SECONDS >= 10 && STABILITY_SECONDS >= 10 )) || {
  echo "Measurement durations must be at least 10 seconds" >&2; exit 2;
}
if ! /usr/bin/python3 -c 'import sys; value=float(sys.argv[1]); raise SystemExit(0 if 0 < value <= 90 else 1)' "$MAX_TEMPERATURE"; then
  echo "Maximum temperature must be greater than 0 and no higher than 90 C" >&2
  exit 2
fi
if [[ "$SKIP_ENHANCEMENT" != true ]] && /usr/bin/python3 -c 'import sys; raise SystemExit(0 if float(sys.argv[1]) >= 85 else 1)' "$MAX_TEMPERATURE"; then
  echo "Enhancement runs must abort below the 85 C thermal cutoff" >&2
  exit 2
fi
if ! /usr/bin/python3 -c 'import sys; start=float(sys.argv[1]); maximum=float(sys.argv[2]); raise SystemExit(0 if 0 < start < maximum else 1)' "$START_TEMPERATURE" "$MAX_TEMPERATURE"; then
  echo "Start temperature must be positive and below the maximum temperature" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1091
source "$WS_DIR/src/node_pc/config/network.env"
set +a
set +u
# shellcheck disable=SC1091
source /opt/ros/noetic/setup.bash
# shellcheck disable=SC1091
source "$WS_DIR/devel/setup.bash"
set -u

# Match run_pipeline.sh's ARM/PyTorch static-TLS workaround. Without this the
# enhancement node respawns and an enhancement benchmark is invalid.
SYSTEM_GOMP=/usr/lib/aarch64-linux-gnu/libgomp.so.1
if [[ -r "$SYSTEM_GOMP" && ":${LD_PRELOAD:-}:" != *":$SYSTEM_GOMP:"* ]]; then
  export LD_PRELOAD="$SYSTEM_GOMP${LD_PRELOAD:+:$LD_PRELOAD}"
fi
SOC_TEMP_PATH=/sys/class/thermal/thermal_zone0/temp
if [[ ! -r "$SOC_TEMP_PATH" ]]; then
  echo "[benchmark] Missing SoC thermal sensor: $SOC_TEMP_PATH" >&2
  exit 1
fi
SOC_TEMP="$(<"$SOC_TEMP_PATH")"
if /usr/bin/python3 -c 'import sys; raise SystemExit(0 if float(sys.argv[1])/1000 >= float(sys.argv[2]) else 1)' "$SOC_TEMP" "$START_TEMPERATURE"; then
  echo "[benchmark] SoC is already at ${SOC_TEMP} millidegrees; cool below ${START_TEMPERATURE} C first" >&2
  exit 1
fi

# The production service must not race the benchmark for the physical sensors.
sudo -v
keep_sudo_alive() {
  while true; do
    sleep 45
    sudo -n -v || return 1
  done
}
keep_sudo_alive &
SUDO_KEEPER=$!
BENCH_TEMP="$(mktemp -d /tmp/rock5-benchmark.XXXXXX)"
LAUNCH_PID=""

stop_launch() {
  [[ -n "$LAUNCH_PID" ]] || return 0
  if kill -0 "$LAUNCH_PID" 2>/dev/null; then
    kill -INT "$LAUNCH_PID" 2>/dev/null || true
    for _ in {1..30}; do
      kill -0 "$LAUNCH_PID" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$LAUNCH_PID" 2>/dev/null; then
      kill -TERM -- "-$LAUNCH_PID" 2>/dev/null || true
    fi
  fi
  wait "$LAUNCH_PID" 2>/dev/null || true
  LAUNCH_PID=""
}

restore_production() {
  local result=$?
  trap - EXIT INT TERM
  stop_launch
  echo "[benchmark] Restoring production service..."
  if ! sudo -n systemctl start node-pc.service; then
    echo "[benchmark] Automatic restore failed; run: sudo systemctl start node-pc.service" >&2
    result=1
  fi
  kill "$SUDO_KEEPER" 2>/dev/null || true
  echo "[benchmark] Local launch logs: $BENCH_TEMP"
  exit "$result"
}
trap restore_production EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "[benchmark] Stopping production pipeline and transports..."
sudo -n systemctl stop node-pc-transport-supervisor.service node-pc-rosbridge.service node-pc.service
if systemctl is-active --quiet node-pc.service; then
  echo "[benchmark] Production pipeline is still active; refusing to share sensors" >&2
  exit 1
fi

run_case() {
  local label="$1" stack="$2" enhance="$3" duration="$4"
  local minimum=3
  [[ "$stack" == 1 ]] && minimum=1
  echo "[benchmark] $label: stack=$stack enhance=$enhance, measuring ${duration}s"
  setsid roslaunch "$BENCH_DIR/benchmark.launch" \
    stack:="$stack" enhance:="$enhance" minimum:="$minimum" \
    >"$BENCH_TEMP/$label.launch.log" 2>&1 &
  LAUNCH_PID=$!

  local ready=false actual=""
  for _ in {1..90}; do
    kill -0 "$LAUNCH_PID" 2>/dev/null || break
    actual="$(timeout 2 rosparam get /pointcloud_merger/consecutive_count 2>/dev/null || true)"
    if [[ "$actual" == "$stack" ]]; then
      ready=true
      break
    fi
    sleep 1
  done
  if [[ "$ready" != true ]]; then
    echo "[benchmark] $label failed to load stack override; see $BENCH_TEMP/$label.launch.log" >&2
    return 1
  fi
  local enhance_flag=()
  [[ "$enhance" == true ]] && enhance_flag=(--enhance)
  /usr/bin/python3 "$BENCH_DIR/record.py" \
    --case "$label" --stack "$stack" "${enhance_flag[@]}" \
    --launch-pid "$LAUNCH_PID" --warmup "$WARMUP_SECONDS" \
    --duration "$duration" --max-temperature "$MAX_TEMPERATURE" \
    --output "$BENCH_TEMP/$label.json"
  stop_launch
  sleep 3
}

if [[ "$ENHANCED_FIRST" == true && "$SKIP_ENHANCEMENT" != true ]]; then
  run_case D 10 true "$SHORT_SECONDS"
fi
run_case A 1 false "$SHORT_SECONDS"
run_case B 3 false "$SHORT_SECONDS"
run_case C 10 false "$SHORT_SECONDS"
if [[ "$ENHANCED_FIRST" != true && "$SKIP_ENHANCEMENT" != true ]]; then
  run_case D 10 true "$SHORT_SECONDS"
fi
if [[ "$SKIP_STABILITY" != true ]]; then
  run_case C_stability 10 false "$STABILITY_SECONDS"
fi

summary_inputs=("$BENCH_TEMP/A.json" "$BENCH_TEMP/B.json" "$BENCH_TEMP/C.json")
[[ "$SKIP_ENHANCEMENT" == true ]] || summary_inputs+=("$BENCH_TEMP/D.json")
[[ "$SKIP_STABILITY" == true ]] || summary_inputs+=("$BENCH_TEMP/C_stability.json")
/usr/bin/python3 "$BENCH_DIR/combine.py" "$OUTPUT" "${summary_inputs[@]}"
echo "[benchmark] Compact result: $OUTPUT"
