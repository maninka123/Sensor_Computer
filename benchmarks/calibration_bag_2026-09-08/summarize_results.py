#!/usr/bin/env python3
"""Summarize pidstat and topic measurements into compact CSV tables."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
COMMAND_NAMES = {
    "lidar_timestamp": "LiDAR timestamp shift",
    "pointcloud_merg": "Point-cloud merger",
    "pointcloud_voxe": "Voxel/radial filter",
    "image_enhancer.": "Low-light enhancer",
    "pointcloud_colo": "Point-cloud colouriser",
    "complementary_f": "IMU complementary filter",
}
INPUT_TOPICS = {
    "lidar_timestamp": "/livox/lidar",
    "pointcloud_merg": "/livox/lidar_shifted",
    "pointcloud_voxe": "/livox/lidar_merged",
    "image_enhancer.": "/camera/image_raw",
    "pointcloud_colo": "/livox/lidar_filtered",
    "complementary_f": "/livox/imu",
}
OUTPUT_TOPICS = {
    "lidar_timestamp": "/livox/lidar_shifted",
    "pointcloud_merg": "/livox/lidar_merged",
    "pointcloud_voxe": "/livox/lidar_filtered",
    "image_enhancer.": "/camera/image_enhanced",
    "pointcloud_colo": "/merged_colored_cloud",
    # The complementary filter publishes once per accepted IMU input. Its output
    # was not included in the original topic capture, so input rate is used.
    "complementary_f": "/livox/imu",
}


def parse_pidstat(path):
    values = {command: [] for command in COMMAND_NAMES}
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) < 15 or fields[0].startswith("#"):
            continue
        command = fields[14]
        if command not in values:
            continue
        try:
            values[command].append((float(fields[7]), float(fields[12]) / 1024.0))
        except ValueError:
            continue
    return values


def topic_rates(path):
    with path.open() as handle:
        return {row["topic"]: float(row["mean_hz"]) for row in csv.DictReader(handle)}


with (RAW / "process_summary.csv").open("w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["mode", "process", "mean_cpu_percent", "mean_rss_mib", "input_hz", "estimated_cpu_ms_per_input"])
    for mode in ("off", "on"):
        stats = parse_pidstat(RAW / f"{mode}_pidstat_controlled.txt")
        rates = topic_rates(RAW / f"{mode}_topics_wall.csv")
        for command, label in COMMAND_NAMES.items():
            samples = stats[command]
            cpu = sum(x[0] for x in samples) / len(samples)
            rss = sum(x[1] for x in samples) / len(samples)
            input_hz = rates[INPUT_TOPICS[command]]
            per_input = cpu * 10.0 / input_hz if input_hz else 0.0
            writer.writerow([mode, label, f"{cpu:.3f}", f"{rss:.3f}", f"{input_hz:.3f}", f"{per_input:.3f}"])


with (RAW / "system_summary.csv").open("w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["mode", "total_cpu_used_percent_of_8_cores", "equivalent_cores_used"])
    for mode in ("off", "on"):
        average_all = None
        for line in (RAW / f"{mode}_mpstat_controlled.txt").read_text().splitlines():
            fields = line.split()
            if len(fields) == 12 and fields[0] == "Average:" and fields[1] == "all":
                average_all = fields
        used = 100.0 - float(average_all[-1])
        writer.writerow([mode, f"{used:.3f}", f"{used * 8.0 / 100.0:.3f}"])

print(RAW / "process_summary.csv")
print(RAW / "system_summary.csv")


with (RAW / "process_event_times.csv").open("w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow([
        "mode", "process", "input_hz", "output_hz", "mean_cpu_percent",
        "estimated_cpu_ms_per_input", "estimated_cpu_ms_per_output",
        "successful_output_available",
    ])
    for mode in ("off", "on"):
        stats = parse_pidstat(RAW / f"{mode}_pidstat_controlled.txt")
        rates = topic_rates(RAW / f"{mode}_topics_wall.csv")
        for command, label in COMMAND_NAMES.items():
            samples = stats[command]
            cpu = sum(x[0] for x in samples) / len(samples)
            input_hz = rates[INPUT_TOPICS[command]]
            output_hz = rates[OUTPUT_TOPICS[command]]
            per_input = cpu * 10.0 / input_hz if input_hz else 0.0
            per_output = cpu * 10.0 / output_hz if output_hz else 0.0
            writer.writerow([
                mode, label, f"{input_hz:.3f}", f"{output_hz:.3f}",
                f"{cpu:.3f}", f"{per_input:.3f}",
                f"{per_output:.3f}" if output_hz else "N/A",
                "yes" if output_hz else "no",
            ])

print(RAW / "process_event_times.csv")
