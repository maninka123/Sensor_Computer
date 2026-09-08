#!/usr/bin/env bash
set -euo pipefail

# Directory containing the bag files; override with BAG_DIR if desired.
SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BAG_DIR="${BAG_DIR:-"$SCRIPT_DIR/Rosbag files"}"

# Extra options passed to rosbag play; override with PLAY_OPTS env var.
# Default includes --clock so sim time is available to nodes.
PLAY_OPTS="${PLAY_OPTS:---clock}"

if [[ ! -d "$BAG_DIR" ]]; then
  echo "Bag directory not found: $BAG_DIR" >&2
  exit 1
fi

shopt -s nullglob
bags=("$BAG_DIR"/*.bag)
shopt -u nullglob

if [[ ${#bags[@]} -eq 0 ]]; then
  echo "No .bag files found in: $BAG_DIR" >&2
  exit 1
fi

# Optional comma-separated topic filter. This is useful for fusion tests where
# every selected bag must contain both raw camera and LiDAR streams.
REQUIRE_TOPICS="${REQUIRE_TOPICS:-}"
if [[ -n "$REQUIRE_TOPICS" ]]; then
  IFS=',' read -r -a required_topics <<< "$REQUIRE_TOPICS"
  selected_bags=()
  for bag in "${bags[@]}"; do
    bag_info="$(rosbag info "$bag")"
    include=true
    for topic in "${required_topics[@]}"; do
      if ! awk -v required="$topic" '$1 == required { found=1 } END { exit !found }' <<< "$bag_info"; then
        echo "Skipping ${bag##*/}: missing $topic"
        include=false
        break
      fi
    done
    if [[ "$include" == true ]]; then
      selected_bags+=("$bag")
    fi
  done
  bags=("${selected_bags[@]}")
  if [[ ${#bags[@]} -eq 0 ]]; then
    echo "No bag files in $BAG_DIR contain every required topic: $REQUIRE_TOPICS" >&2
    exit 1
  fi
fi

echo "Found ${#bags[@]} bag file(s) in $BAG_DIR"
echo "Press Ctrl+C to stop the loop."

cleanup() {
  echo "Stopping rosbag loop..."
  exit 0
}
trap cleanup INT

while true; do
  for bag in "${bags[@]}"; do
    echo "===== Playing ${bag##*/} ====="
    rosbag play $PLAY_OPTS "$bag"
    echo "===== Finished ${bag##*/} ====="
    sleep 1
  done
done
