#!/usr/bin/env python3
"""Measure first/last LiDAR-to-image timing in colourized PointCloud2 outputs."""

import argparse
import csv
import statistics
import struct
import threading
import time

import rospy
from sensor_msgs.msg import PointCloud2


def describe(values):
    return (
        statistics.mean(values) if values else 0.0,
        min(values) if values else 0.0,
        max(values) if values else 0.0,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--samples-output", required=True)
    parser.add_argument("--summary-output", required=True)
    args = parser.parse_args()

    rospy.init_node("sync_edge_benchmark", anonymous=True, disable_signals=True)
    lock = threading.Lock()
    samples = []

    def callback(message):
        offsets = {field.name: field.offset for field in message.fields}
        required = [
            "source_frame_index", "source_frame_stamp_sec", "source_frame_stamp_nsec",
            "image_stamp_sec", "image_stamp_nsec",
        ]
        if any(name not in offsets for name in required):
            return
        byte_order = ">" if message.is_bigendian else "<"
        unpack_u32 = struct.Struct(byte_order + "I").unpack_from
        groups = []
        previous_index = None
        for point in range(message.width * message.height):
            base = point * message.point_step
            source_index = unpack_u32(message.data, base + offsets["source_frame_index"])[0]
            if source_index == previous_index:
                continue
            previous_index = source_index
            source_sec = unpack_u32(message.data, base + offsets["source_frame_stamp_sec"])[0]
            source_nsec = unpack_u32(message.data, base + offsets["source_frame_stamp_nsec"])[0]
            image_sec = unpack_u32(message.data, base + offsets["image_stamp_sec"])[0]
            image_nsec = unpack_u32(message.data, base + offsets["image_stamp_nsec"])[0]
            source_stamp = source_sec + source_nsec * 1e-9
            image_stamp = image_sec + image_nsec * 1e-9
            groups.append((source_stamp, image_stamp, (image_stamp - source_stamp) * 1000.0))
        if not groups:
            return
        groups.sort(key=lambda item: item[0])
        deltas = [item[2] for item in groups]
        event_lag = (rospy.Time.now().to_sec() - message.header.stamp.to_sec()) * 1000.0
        # A rosbag loop can reset /clock while a callback is in flight. Such a
        # value is not a processing-lag observation and is excluded below.
        valid_event_lag = event_lag if 0.0 <= event_lag <= 5000.0 else None
        with lock:
            samples.append({
                "matched_frames": len(groups),
                "first_lidar": groups[0][0],
                "first_camera": groups[0][1],
                "first_signed_ms": groups[0][2],
                "last_lidar": groups[-1][0],
                "last_camera": groups[-1][1],
                "last_signed_ms": groups[-1][2],
                "mean_signed_ms": statistics.mean(deltas),
                "mean_abs_ms": statistics.mean(abs(value) for value in deltas),
                "best_abs_ms": min(abs(value) for value in deltas),
                "worst_abs_ms": max(abs(value) for value in deltas),
                "lidar_span_ms": (groups[-1][0] - groups[0][0]) * 1000.0,
                "camera_span_ms": (groups[-1][1] - groups[0][1]) * 1000.0,
                "output_event_lag_ms": valid_event_lag,
            })

    subscriber = rospy.Subscriber(
        "/merged_colored_cloud", PointCloud2, callback, queue_size=10,
        buff_size=16 * 1024 * 1024,
    )
    del subscriber
    time.sleep(args.duration)
    with lock:
        captured = list(samples)

    sample_fields = [
        "matched_frames", "first_lidar", "first_camera", "first_signed_ms",
        "last_lidar", "last_camera", "last_signed_ms", "mean_signed_ms",
        "mean_abs_ms", "best_abs_ms", "worst_abs_ms", "lidar_span_ms",
        "camera_span_ms", "output_event_lag_ms",
    ]
    with open(args.samples_output, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["mode"] + sample_fields)
        writer.writeheader()
        for sample in captured:
            row = {"mode": args.mode}
            row.update(sample)
            writer.writerow(row)

    first_signed = [sample["first_signed_ms"] for sample in captured]
    last_signed = [sample["last_signed_ms"] for sample in captured]
    first_abs = [abs(value) for value in first_signed]
    last_abs = [abs(value) for value in last_signed]
    all_abs_means = [sample["mean_abs_ms"] for sample in captured]
    all_best = [sample["best_abs_ms"] for sample in captured]
    all_worst = [sample["worst_abs_ms"] for sample in captured]
    spans = [sample["lidar_span_ms"] for sample in captured]
    event_lags = [sample["output_event_lag_ms"] for sample in captured
                  if sample["output_event_lag_ms"] is not None]
    valid_samples = [sample for sample in captured
                     if sample["output_event_lag_ms"] is not None]
    output_from_first_lidar = [
        sample["output_event_lag_ms"] + sample["lidar_span_ms"]
        for sample in valid_samples
    ]
    output_from_first_camera = [
        sample["output_event_lag_ms"] + sample["lidar_span_ms"] - sample["first_signed_ms"]
        for sample in valid_samples
    ]
    output_from_last_camera = [
        sample["output_event_lag_ms"] - sample["last_signed_ms"]
        for sample in valid_samples
    ]
    first_mean, first_min, first_max = describe(first_signed)
    last_mean, last_min, last_max = describe(last_signed)
    lag_mean, lag_min, lag_max = describe(event_lags)
    with open(args.summary_output, "a", newline="") as handle:
        writer = csv.writer(handle)
        if handle.tell() == 0:
            writer.writerow([
                "mode", "outputs", "first_signed_mean_ms", "first_signed_min_ms",
                "first_signed_max_ms", "first_abs_mean_ms", "first_abs_best_ms",
                "first_abs_worst_ms", "last_signed_mean_ms", "last_signed_min_ms",
                "last_signed_max_ms", "last_abs_mean_ms", "last_abs_best_ms",
                "last_abs_worst_ms", "pair_mean_abs_ms", "pair_best_abs_ms",
                "pair_worst_abs_ms", "mean_lidar_span_ms", "min_lidar_span_ms",
                "max_lidar_span_ms", "output_event_lag_mean_ms",
                "output_event_lag_best_ms", "output_event_lag_worst_ms",
                "output_from_first_lidar_mean_ms", "output_from_first_lidar_best_ms",
                "output_from_first_lidar_worst_ms", "output_from_first_camera_mean_ms",
                "output_from_first_camera_best_ms", "output_from_first_camera_worst_ms",
                "output_from_last_camera_mean_ms", "output_from_last_camera_best_ms",
                "output_from_last_camera_worst_ms",
            ])
        writer.writerow([
            args.mode, len(captured), f"{first_mean:.6f}", f"{first_min:.6f}",
            f"{first_max:.6f}", f"{statistics.mean(first_abs) if first_abs else 0.0:.6f}",
            f"{min(first_abs) if first_abs else 0.0:.6f}",
            f"{max(first_abs) if first_abs else 0.0:.6f}",
            f"{last_mean:.6f}", f"{last_min:.6f}", f"{last_max:.6f}",
            f"{statistics.mean(last_abs) if last_abs else 0.0:.6f}",
            f"{min(last_abs) if last_abs else 0.0:.6f}",
            f"{max(last_abs) if last_abs else 0.0:.6f}",
            f"{statistics.mean(all_abs_means) if all_abs_means else 0.0:.6f}",
            f"{min(all_best) if all_best else 0.0:.6f}",
            f"{max(all_worst) if all_worst else 0.0:.6f}",
            f"{statistics.mean(spans) if spans else 0.0:.6f}",
            f"{min(spans) if spans else 0.0:.6f}",
            f"{max(spans) if spans else 0.0:.6f}",
            f"{lag_mean:.6f}", f"{lag_min:.6f}", f"{lag_max:.6f}",
            f"{statistics.mean(output_from_first_lidar) if output_from_first_lidar else 0.0:.6f}",
            f"{min(output_from_first_lidar) if output_from_first_lidar else 0.0:.6f}",
            f"{max(output_from_first_lidar) if output_from_first_lidar else 0.0:.6f}",
            f"{statistics.mean(output_from_first_camera) if output_from_first_camera else 0.0:.6f}",
            f"{min(output_from_first_camera) if output_from_first_camera else 0.0:.6f}",
            f"{max(output_from_first_camera) if output_from_first_camera else 0.0:.6f}",
            f"{statistics.mean(output_from_last_camera) if output_from_last_camera else 0.0:.6f}",
            f"{min(output_from_last_camera) if output_from_last_camera else 0.0:.6f}",
            f"{max(output_from_last_camera) if output_from_last_camera else 0.0:.6f}",
        ])


if __name__ == "__main__":
    main()
