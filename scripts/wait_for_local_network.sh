#!/usr/bin/env bash
set -euo pipefail

INTERFACE="${1:-eth0}"
TIMEOUT_SECONDS="${2:-60}"

if [[ ! "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || (( TIMEOUT_SECONDS < 1 )); then
  echo "[network-wait] ERROR: timeout must be a positive integer" >&2
  exit 2
fi

required_addresses=("${ROS_IP:-}" "${LIVOX_HOST_IP:-}")
for address in "${required_addresses[@]}"; do
  if [[ -z "$address" ]]; then
    echo "[network-wait] ERROR: ROS_IP and LIVOX_HOST_IP must be configured" >&2
    exit 2
  fi
done

deadline=$((SECONDS + TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  assigned_addresses="$(ip -4 -o address show dev "$INTERFACE" 2>/dev/null || true)"
  ready=true
  for address in "${required_addresses[@]}"; do
    if ! grep -Fq " ${address}/" <<<"$assigned_addresses"; then
      ready=false
      break
    fi
  done

  if [[ "$ready" == true ]]; then
    echo "[network-wait] $INTERFACE ready with ${required_addresses[*]}"
    exit 0
  fi
  sleep 1
done

echo "[network-wait] ERROR: $INTERFACE did not receive ${required_addresses[*]} within ${TIMEOUT_SECONDS}s" >&2
exit 1
