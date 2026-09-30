#!/usr/bin/env bash
# Restart a stalled hardware roslaunch by signaling its supervised process.
set -euo pipefail

launch_pid="${1:?usage: watch_pipeline_streams.sh ROSLAUNCH_PID}"
grace="${PIPELINE_WATCHDOG_GRACE_SECONDS:-45}"
interval="${PIPELINE_WATCHDOG_INTERVAL_SECONDS:-10}"
probe_timeout="${PIPELINE_WATCHDOG_PROBE_TIMEOUT_SECONDS:-6}"
miss_limit="${PIPELINE_WATCHDOG_MISS_LIMIT:-2}"
window="${PIPELINE_WATCHDOG_WINDOW_SECONDS:-300}"
window_miss_limit="${PIPELINE_WATCHDOG_WINDOW_MISS_LIMIT:-4}"

for value in "$launch_pid" "$grace" "$interval" "$probe_timeout" "$miss_limit" "$window" "$window_miss_limit"; do
  if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < 1 )); then
    echo "[stream-watchdog] ERROR: expected positive integer, got '$value'" >&2
    exit 2
  fi
done

sleep "$grace"
misses=0
recent_misses=()
while kill -0 "$launch_pid" 2>/dev/null; do
  missing_topic=""
  for topic in /camera/image_raw/header /livox/lidar/header /merged_colored_cloud/header; do
    if ! timeout "$probe_timeout" rostopic echo -n 1 "$topic" >/dev/null 2>&1; then
      missing_topic="$topic"
      break
    fi
  done

  if [[ -n "$missing_topic" ]]; then
    (( misses += 1 ))
    now=$SECONDS
    kept=()
    for missed_at in "${recent_misses[@]}"; do
      if (( now - missed_at <= window )); then
        kept+=("$missed_at")
      fi
    done
    recent_misses=("${kept[@]}" "$now")
    echo "[stream-watchdog] No fresh message on $missing_topic (consecutive $misses/$miss_limit; recent ${#recent_misses[@]}/$window_miss_limit)" >&2
    if (( misses >= miss_limit || ${#recent_misses[@]} >= window_miss_limit )); then
      echo "[stream-watchdog] Restarting stalled ROS launch PID $launch_pid" >&2
      kill -INT "$launch_pid" 2>/dev/null || true
      exit 1
    fi
  else
    if (( misses > 0 )); then
      echo "[stream-watchdog] Camera, LiDAR, and fused cloud recovered"
    fi
    misses=0
  fi

  sleep "$interval"
done
