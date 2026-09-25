#!/usr/bin/env python3
"""Combine only small benchmark summaries for version control."""

import json
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Usage: combine.py OUTPUT RUN.json [RUN.json ...]")
    destination = Path(sys.argv[1])
    cases = {}
    for path in map(Path, sys.argv[2:]):
        item = json.loads(path.read_text(encoding="utf-8"))
        cases[item["case"]] = item
    try:
        board = Path("/proc/device-tree/model").read_bytes().rstrip(b"\0").decode()
    except OSError:
        board = "unknown"
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    result = {
        "schema_version": 1,
        "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "board": board,
        "kernel": platform.release(),
        "ros_distro": "noetic",
        "code_commit": commit,
        "cases": cases,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
