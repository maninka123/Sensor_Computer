#!/usr/bin/env bash
set -euo pipefail

NODE_NAME="${1:-/pointcloud_colorizer}"
TOPIC_NAME="${2:-/merged_colored_cloud}"

if ! command -v rosnode >/dev/null || ! command -v rostopic >/dev/null || \
   ! command -v rosmsg >/dev/null || ! command -v ss >/dev/null; then
  echo "ERROR: rosnode, rostopic, rosmsg, and ss must be available." >&2
  exit 1
fi

NODE_INFO="$(rosnode info "$NODE_NAME")" || {
  echo "ERROR: cannot inspect running node $NODE_NAME" >&2
  exit 1
}

NODE_URI="$(awk '/^contacting node / {print $3; exit}' <<<"$NODE_INFO")"
NODE_PID="$(awk '/^ *Pid: / {print $2; exit}' <<<"$NODE_INFO")"
ADVERTISED_ADDRESS="$(sed -nE 's#^https?://([^/:]+).*$#\1#p' <<<"$NODE_URI")"
MESSAGE_TYPE="$(rostopic type "$TOPIC_NAME")" || {
  echo "ERROR: topic $TOPIC_NAME is not currently advertised." >&2
  exit 1
}
MESSAGE_MD5="$(rosmsg md5 "$MESSAGE_TYPE")"

echo "Publisher node:       $NODE_NAME"
echo "Node XML-RPC URI:      ${NODE_URI:-<not reported>}"
echo "Advertised address:   ${ADVERTISED_ADDRESS:-<not reported>}"
echo "Configured address:   ${ROS_IP:-<not set in this shell>}"
echo "Process ID:            ${NODE_PID:-<not reported>}"
echo "Published topic:       $TOPIC_NAME"
echo "Message type:          $MESSAGE_TYPE"
echo "Message definition MD5: $MESSAGE_MD5"
echo
echo "Established TCPROS connections (local -> remote):"

if [ -z "$NODE_PID" ]; then
  echo "  Unable to determine the node PID."
  exit 1
fi

SS_OUTPUT="$(ss -tnpH state established 2>/dev/null || true)"
# The persistent connection to the Master is XML-RPC, not TCPROS. Exclude it
# from the per-node socket list; remaining established sockets are transport
# connections such as publisher/subscriber links (including /rosout).
MASTER_PORT="$(sed -nE 's#^https?://[^/:]+:([0-9]+)/?$#\1#p' <<<"${ROS_MASTER_URI:-http://localhost:11311}")"
if [ -n "$MASTER_PORT" ]; then
  MATCHES="$(grep -F "pid=$NODE_PID," <<<"$SS_OUTPUT" | grep -vE ":${MASTER_PORT}[[:space:]]" || true)"
else
  MATCHES="$(grep -F "pid=$NODE_PID," <<<"$SS_OUTPUT" || true)"
fi
if [ -n "$MATCHES" ]; then
  sed 's/^/  /' <<<"$MATCHES"
else
  echo "  None visible for PID $NODE_PID."
  echo "  If subscribers are connected, rerun with sudo so ss can expose process ownership."
fi
