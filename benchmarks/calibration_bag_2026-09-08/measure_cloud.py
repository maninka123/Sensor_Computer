#!/usr/bin/env python3
"""Measure one PointCloud2 topic over a fixed wall-time interval."""

import argparse
import csv
import statistics
import threading
import time

import rospy
from sensor_msgs.msg import PointCloud2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/livox/lidar_filtered")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--voxel-size", type=float, required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rospy.init_node("cloud_size_benchmark", anonymous=True, disable_signals=True)
    lock = threading.Lock()
    times, points, sizes = [], [], []

    def callback(message):
        with lock:
            times.append(time.monotonic())
            points.append(message.width * message.height)
            sizes.append(len(message.data))

    subscriber = rospy.Subscriber(args.topic, PointCloud2, callback, queue_size=20)
    del subscriber
    start = time.monotonic()
    time.sleep(args.duration)
    elapsed = time.monotonic() - start

    exists = __import__("os").path.exists(args.output)
    with open(args.output, "a", newline="") as handle:
        writer = csv.writer(handle)
        if not exists:
            writer.writerow([
                "voxel_size_m", "messages", "wall_seconds", "mean_hz",
                "mean_points", "median_points", "mean_payload_kib",
                "payload_mib_per_s",
            ])
        writer.writerow([
            args.voxel_size,
            len(times),
            f"{elapsed:.6f}",
            f"{len(times) / elapsed:.6f}",
            f"{statistics.mean(points) if points else 0.0:.3f}",
            f"{statistics.median(points) if points else 0.0:.3f}",
            f"{statistics.mean(sizes) / 1024.0 if sizes else 0.0:.6f}",
            f"{sum(sizes) / elapsed / 1024.0 / 1024.0:.6f}",
        ])


if __name__ == "__main__":
    main()
