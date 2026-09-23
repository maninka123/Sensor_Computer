#!/usr/bin/env bash
set -euo pipefail

RETENTION_DAYS=90
APPLY=false
ROS_LOG_DIR="${ROS_LOG_DIR:-/home/rock/.ros/log}"

usage() {
  echo "Usage: $0 [--days N] [--apply]"
  echo "Without --apply, only reports what would be deleted."
}

while (( $# > 0 )); do
  case "$1" in
    --days)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      RETENTION_DAYS="$2"
      shift 2
      ;;
    --apply)
      APPLY=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[log-cleanup] ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || (( RETENTION_DAYS < 7 )); then
  echo "[log-cleanup] ERROR: retention must be an integer of at least 7 days" >&2
  exit 2
fi

resolved_log_dir="$(realpath -m -- "$ROS_LOG_DIR")"
if [[ "$resolved_log_dir" != "/home/rock/.ros/log" ]]; then
  echo "[log-cleanup] ERROR: refusing unexpected log directory: $resolved_log_dir" >&2
  exit 2
fi
if [[ ! -d "$resolved_log_dir" ]]; then
  echo "[log-cleanup] Nothing to do; $resolved_log_dir does not exist"
  exit 0
fi

# Prevent the startup cleanup and daily timer from running simultaneously.
exec 9>/tmp/node-pc-ros-log-cleanup.lock
if ! flock -n 9; then
  echo "[log-cleanup] Another cleanup is already running; skipping"
  exit 0
fi

age_minutes=$((RETENTION_DAYS * 24 * 60))
candidate_list="$(mktemp /tmp/node-pc-old-ros-logs.XXXXXX)"
trap 'rm -f -- "$candidate_list"' EXIT

# Regular files only: do not follow or delete the ROS `latest` symlink.
find "$resolved_log_dir" -xdev -type f -mmin "+$age_minutes" -print0 >"$candidate_list"
candidate_count="$(tr -cd '\0' <"$candidate_list" | wc -c)"
candidate_bytes="$(xargs -0 -r stat -c %s -- <"$candidate_list" 2>/dev/null |
  awk '{total += $1} END {print total + 0}')"

echo "[log-cleanup] $candidate_count files older than $RETENTION_DAYS days ($(numfmt --to=iec-i --suffix=B "$candidate_bytes"))"
if [[ "$APPLY" != true ]]; then
  echo "[log-cleanup] Dry run only; pass --apply to delete them"
  exit 0
fi

while IFS= read -r -d '' file; do
  rm -f -- "$file"
done <"$candidate_list"

# Remove only directories that became empty. Active/current run directories
# and the `latest` symlink are left untouched.
find "$resolved_log_dir" -xdev -depth -mindepth 1 -type d -empty -delete
remaining_bytes="$(du -sb "$resolved_log_dir" | awk '{print $1}')"
echo "[log-cleanup] Deleted $candidate_count old files; remaining log usage $(numfmt --to=iec-i --suffix=B "$remaining_bytes")"
