#!/usr/bin/env python3
"""Measure how many source frames and points enter each colourized cloud."""

import argparse
import csv
import statistics
import threading
import time

import rospy
from std_msgs.msg import UInt32


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=25.0)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rospy.init_node("partial_batch_benchmark", anonymous=True, disable_signals=True)
    lock = threading.Lock()
    active = [False]
    values = {"matched": [], "input": [], "points": [], "dropped": []}
    dropped_baseline = rospy.wait_for_message(
        "/merged_colored_cloud/dropped_batches", UInt32, timeout=5.0
    ).data

    def record(message, key):
        with lock:
            if active[0]:
                values[key].append(message.data)

    subscribers = [
        rospy.Subscriber("/merged_colored_cloud/matched_frames", UInt32, record,
                         callback_args="matched", queue_size=100),
        rospy.Subscriber("/merged_colored_cloud/input_frames", UInt32, record,
                         callback_args="input", queue_size=100),
        rospy.Subscriber("/merged_colored_cloud/point_count", UInt32, record,
                         callback_args="points", queue_size=100),
        rospy.Subscriber("/merged_colored_cloud/dropped_batches", UInt32, record,
                         callback_args="dropped", queue_size=100),
    ]
    del subscribers
    time.sleep(0.5)  # Exclude the initial latched status samples.
    with lock:
        for samples in values.values():
            samples.clear()
        active[0] = True
    time.sleep(args.duration)
    with lock:
        active[0] = False
        snapshot = {key: list(samples) for key, samples in values.items()}

    def mean_or_zero(samples):
        return statistics.mean(samples) if samples else 0.0

    dropped = snapshot["dropped"]
    dropped_increase = (dropped[-1] - dropped_baseline) if dropped else 0
    successful = [
        (matched, points)
        for matched, points in zip(snapshot["matched"], snapshot["points"])
        if points > 0
    ]
    matched = [item[0] for item in successful]
    points = [item[1] for item in successful]
    with open(args.output, "a", newline="") as handle:
        writer = csv.writer(handle)
        if handle.tell() == 0:
            writer.writerow([
                "mode", "published_batches", "mean_matched_frames",
                "min_matched_frames", "max_matched_frames", "mean_input_frames",
                "mean_points", "dropped_batches_increase",
            ])
        writer.writerow([
            args.mode,
            len(matched),
            f"{mean_or_zero(matched):.3f}",
            min(matched) if matched else 0,
            max(matched) if matched else 0,
            f"{mean_or_zero(snapshot['input']):.3f}",
            f"{mean_or_zero(points):.3f}",
            dropped_increase,
        ])


if __name__ == "__main__":
    main()
