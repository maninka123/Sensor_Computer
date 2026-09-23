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

if ! ip link show dev "$INTERFACE" >/dev/null 2>&1; then
  echo "[network-wait] ERROR: interface $INTERFACE does not exist" >&2
  echo "[network-wait] Available interfaces: $(ls -1 /sys/class/net 2>/dev/null | tr '\n' ' ')" >&2
  exit 2
fi

deadline=$((SECONDS + TIMEOUT_SECONDS))
next_report=$SECONDS
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
  if (( SECONDS >= next_report )); then
    observed="$(awk '{print $4}' <<<"$assigned_addresses" | tr '\n' ' ')"
    operstate="$(cat "/sys/class/net/$INTERFACE/operstate" 2>/dev/null || echo unknown)"
    echo "[network-wait] Waiting for ${required_addresses[*]} on $INTERFACE; state=$operstate observed=${observed:-none}"
    next_report=$((SECONDS + 10))
  fi
  sleep 1
done

echo "[network-wait] ERROR: $INTERFACE did not receive ${required_addresses[*]} within ${TIMEOUT_SECONDS}s" >&2
ip -4 -o address show dev "$INTERFACE" >&2 || true
exit 1
