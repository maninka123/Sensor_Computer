#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
DEVICE_SERVICE=device

usage() {
  cat >&2 <<EOF
Usage:
  $0 [--delay 5ms] [--rate 25mbit] [--loss 0.1%]
  $0 clear
EOF
}

COMPOSE=(docker compose -f "$COMPOSE_FILE")
if [ "${1:-}" = "clear" ]; then
  if [ "$#" -ne 1 ]; then
    usage
    exit 2
  fi
  "${COMPOSE[@]}" exec -T "$DEVICE_SERVICE" tc qdisc del dev eth0 root
  echo "Cleared link shaping on the sensing device"
  exit 0
fi

DELAY=5ms
RATE=25mbit
LOSS=0.1%
while [ "$#" -gt 0 ]; do
  case "$1" in
    --delay)
      DELAY="${2:?--delay requires a value}"
      shift 2
      ;;
    --rate)
      RATE="${2:?--rate requires a value}"
      shift 2
      ;;
    --loss)
      LOSS="${2:?--loss requires a value}"
      shift 2
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

"${COMPOSE[@]}" exec -T "$DEVICE_SERVICE" tc qdisc replace dev eth0 root netem \
  delay "$DELAY" \
  rate "$RATE" \
  loss "$LOSS"
echo "Applied to sensing device: delay=$DELAY rate=$RATE loss=$LOSS"
"${COMPOSE[@]}" exec -T "$DEVICE_SERVICE" tc qdisc show dev eth0
