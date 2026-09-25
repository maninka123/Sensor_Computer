#!/usr/bin/env python3
"""Record compact, observer-side ROCK 5 pipeline benchmark summaries."""

import argparse
import collections
import json
import math
from pathlib import Path
import statistics
import struct
import threading
import time

import psutil
import rospy
from std_msgs.msg import Bool, UInt32


CLOUDS = {
    "lidar": "/livox/lidar",
    "shifted": "/livox/lidar_shifted",
    "merged": "/livox/lidar_merged",
    "filtered": "/livox/lidar_filtered",
    "final": "/merged_colored_cloud",
}
TEMPERATURE = Path("/sys/class/thermal/thermal_zone0/temp")


def cloud_meta(message):
    """Read PointCloud2 metadata without deserializing its large point array."""
    data = message._buff
    _, sec, nsec, frame_len = struct.unpack_from("<IIII", data)
    offset = 16 + frame_len
    height, width, fields = struct.unpack_from("<III", data, offset)
    offset += 12
    for _ in range(fields):
        name_len = struct.unpack_from("<I", data, offset)[0]
        offset += 4 + name_len + 4 + 1 + 4
    offset += 1  # is_bigendian
    _, _, payload_bytes = struct.unpack_from("<III", data, offset)
    return (sec, nsec), width * height, payload_bytes


def mean_or_none(values):
    return round(statistics.mean(values), 3) if values else None


def timing(values):
    if not values:
        return {"median_ms": None, "p95_ms": None, "samples": 0}
    ordered = sorted(values)
    return {
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 3),
        "samples": len(ordered),
    }


class Recorder:
    def __init__(self, launch_pid):
        self.lock = threading.Lock()
        self.collecting = False
        self.counts = collections.Counter()
        self.point_counts = {key: [] for key in CLOUDS}
        self.payload_bytes = {key: [] for key in CLOUDS}
        self.arrivals = {key: collections.OrderedDict() for key in CLOUDS}
        self.delays = {key: [] for key in ("merge", "filter", "colorize", "total")}
        self.negative_pairs = collections.Counter()
        self.matched_total = 0
        self.input_total = 0
        self.dropped_first = None
        self.dropped_last = None
        self.latest_dropped = None
        self.enhancement_states = []
        self.latest_enhancement_state = None
        self.cpu_system = []
        self.cpu_pipeline_cores = []
        self.cpu_nodes = collections.defaultdict(list)
        self.ram_mb = []
        self.temperature_c = []
        self.launch_pid = launch_pid
        self.previous_cpu = {}
        self.previous_sample = None

        for key, topic in CLOUDS.items():
            rospy.Subscriber(topic, rospy.AnyMsg, self.cloud_callback,
                             callback_args=key, queue_size=1, buff_size=64 * 1024 * 1024)
        rospy.Subscriber("/camera/image_raw", rospy.AnyMsg, self.camera_callback,
                         queue_size=1, buff_size=4 * 1024 * 1024)
        rospy.Subscriber("/merged_colored_cloud/matched_frames", UInt32,
                         self.matched_callback, queue_size=10)
        rospy.Subscriber("/merged_colored_cloud/input_frames", UInt32,
                         self.input_callback, queue_size=10)
        rospy.Subscriber("/merged_colored_cloud/dropped_batches", UInt32,
                         self.dropped_callback, queue_size=10)
        rospy.Subscriber("/image_enhancement/status", Bool,
                         self.enhancement_callback, queue_size=10)

    def cloud_callback(self, message, key):
        try:
            stamp, points, size = cloud_meta(message)
        except (struct.error, ValueError):
            return
        now = time.monotonic()
        with self.lock:
            if not self.collecting:
                return
            self.counts[key] += 1
            self.point_counts[key].append(points)
            self.payload_bytes[key].append(size)
            history = self.arrivals[key]
            history[stamp] = now
            while len(history) > 256:
                history.popitem(last=False)
            for stage, earlier, later in (
                ("merge", "shifted", "merged"),
                ("filter", "merged", "filtered"),
                ("colorize", "filtered", "final"),
                ("total", "shifted", "final"),
            ):
                if key != later or stamp not in self.arrivals[earlier]:
                    continue
                delay = (now - self.arrivals[earlier][stamp]) * 1000.0
                if delay >= 0:
                    self.delays[stage].append(delay)
                else:
                    self.negative_pairs[stage] += 1

    def camera_callback(self, _message):
        with self.lock:
            if self.collecting:
                self.counts["camera"] += 1

    def matched_callback(self, message):
        with self.lock:
            if self.collecting:
                self.matched_total += message.data

    def input_callback(self, message):
        with self.lock:
            if self.collecting:
                self.input_total += message.data

    def dropped_callback(self, message):
        with self.lock:
            self.latest_dropped = message.data
            if self.collecting:
                if self.dropped_first is None:
                    self.dropped_first = message.data
                self.dropped_last = message.data

    def enhancement_callback(self, message):
        with self.lock:
            self.latest_enhancement_state = bool(message.data)

    def sample_resources(self):
        now = time.monotonic()
        with self.lock:
            self.enhancement_states.append(self.latest_enhancement_state)
        self.cpu_system.append(psutil.cpu_percent(interval=None))
        self.ram_mb.append((psutil.virtual_memory().total -
                            psutil.virtual_memory().available) / 1e6)
        try:
            raw = float(TEMPERATURE.read_text(encoding="ascii").strip())
            temperature = raw / 1000.0 if abs(raw) >= 1000 else raw
            self.temperature_c.append(temperature)
        except (OSError, ValueError):
            temperature = None

        try:
            root = psutil.Process(self.launch_pid)
            processes = [root] + root.children(recursive=True)
        except psutil.Error:
            processes = []
        current = {}
        total_delta = 0.0
        node_delta = collections.Counter()
        for process in processes:
            try:
                cpu = process.cpu_times()
                elapsed = cpu.user + cpu.system
                name = " ".join(process.cmdline())
            except psutil.Error:
                continue
            current[process.pid] = elapsed
            previous = self.previous_cpu.get(process.pid)
            if previous is None:
                continue
            delta = max(0.0, elapsed - previous)
            total_delta += delta
            for label, pattern in (
                ("merge", "pointcloud_merge_node"),
                ("filter", "pointcloud_voxel_filter_node"),
                ("colorize", "pointcloud_colorize_node"),
                ("enhancer", "image_enhancer.py"),
            ):
                if pattern in name:
                    node_delta[label] += delta
                    break
        if self.previous_sample is not None:
            interval = now - self.previous_sample
            if interval > 0:
                self.cpu_pipeline_cores.append(100.0 * total_delta / interval)
                for label in ("merge", "filter", "colorize", "enhancer"):
                    self.cpu_nodes[label].append(100.0 * node_delta[label] / interval)
        self.previous_cpu = current
        self.previous_sample = now
        return temperature

    def summary(self, args, elapsed):
        with self.lock:
            counts = dict(self.counts)
            drop_delta = (self.dropped_last - self.dropped_first
                          if self.dropped_first is not None else None)
            return {
                "schema_version": 1,
                "case": args.case,
                "stack": args.stack,
                "enhancement_requested": args.enhance,
                "warmup_seconds": args.warmup,
                "measurement_seconds": round(elapsed, 3),
                "rates_hz": {key: round(counts.get(key, 0) / elapsed, 3)
                             for key in ("lidar", "camera", "merged", "filtered", "final")},
                "message_counts": counts,
                "latency_ms_observer": {key: timing(values)
                                        for key, values in self.delays.items()},
                "negative_latency_pairs": dict(self.negative_pairs),
                "points_per_message": {key: mean_or_none(values)
                                       for key, values in self.point_counts.items()
                                       if key in ("lidar", "merged", "filtered", "final")},
                "final_mb_per_message": (round(statistics.mean(self.payload_bytes["final"]) / 1e6, 3)
                                         if self.payload_bytes["final"] else None),
                "final_mb_per_second": round(sum(self.payload_bytes["final"]) / elapsed / 1e6, 3),
                "cpu_system_percent": mean_or_none(self.cpu_system[1:]),
                "cpu_pipeline_core_percent": mean_or_none(self.cpu_pipeline_cores),
                "cpu_node_core_percent": {key: mean_or_none(values)
                                          for key, values in self.cpu_nodes.items()},
                "ram_used_mb": mean_or_none(self.ram_mb),
                "soc_temperature_c_avg": mean_or_none(self.temperature_c),
                "soc_temperature_c_max": round(max(self.temperature_c), 3)
                                         if self.temperature_c else None,
                "dropped_batches": drop_delta,
                "expected_batches": counts.get("merged", 0),
                "matched_frames": self.matched_total,
                "input_frames": self.input_total,
                "enhancement_effective_states": self.enhancement_states,
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--stack", type=int, choices=(1, 3, 10), required=True)
    parser.add_argument("--enhance", action="store_true")
    parser.add_argument("--launch-pid", type=int, required=True)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--max-temperature", type=float, default=80.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.warmup < 0 or args.duration < 10:
        parser.error("warmup must be non-negative and duration at least 10 seconds")
    rospy.init_node("rock5_benchmark_observer", anonymous=True, disable_signals=True)
    recorder = Recorder(args.launch_pid)
    psutil.cpu_percent(interval=None)
    time.sleep(args.warmup)
    with recorder.lock:
        recorder.dropped_first = recorder.latest_dropped
        recorder.dropped_last = recorder.latest_dropped
        recorder.collecting = True
    started = time.monotonic()
    invalid_reason = None
    while time.monotonic() - started < args.duration:
        temperature = recorder.sample_resources()
        if temperature is None:
            invalid_reason = "SoC temperature sensor unavailable"
            break
        if temperature >= args.max_temperature:
            invalid_reason = "SoC temperature reached %.1f C" % temperature
            break
        with recorder.lock:
            effective = recorder.latest_enhancement_state
        if effective is None or (args.enhance and not effective):
            invalid_reason = "enhancement effective status is unavailable or OFF"
            break
        time.sleep(1.0)
    elapsed = time.monotonic() - started
    recorder.collecting = False
    result = recorder.summary(args, elapsed)
    result["valid"] = invalid_reason is None
    result["invalid_reason"] = invalid_reason
    result["thermal_limited"] = bool(result["soc_temperature_c_max"] is not None
                                     and result["soc_temperature_c_max"] >= 85.0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"case": args.case, "rates_hz": result["rates_hz"],
                      "temperature_max_c": result["soc_temperature_c_max"],
                      "valid": result["valid"], "reason": invalid_reason,
                      "output": str(args.output)}, sort_keys=True), flush=True)
    if invalid_reason:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
