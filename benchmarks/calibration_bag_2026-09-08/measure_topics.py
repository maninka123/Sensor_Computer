#!/usr/bin/env python3
"""Measure ROS topic throughput using wall time, independent of /use_sim_time."""

import argparse
import csv
import statistics
import threading
import time

import rospy
from rospy.msg import AnyMsg
from sensor_msgs.msg import PointCloud2


TOPICS = [
    "/camera/image_raw",
    "/camera/image_enhanced",
    "/livox/imu",
    "/livox/lidar",
    "/livox/lidar_shifted",
    "/livox/lidar_merged",
    "/livox/lidar_filtered",
    "/merged_colored_cloud",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rospy.init_node("pipeline_topic_benchmark", anonymous=True, disable_signals=True)
    lock = threading.Lock()
    samples = {topic: {"times": [], "bytes": 0} for topic in TOPICS}
    point_counts = {topic: [] for topic in TOPICS}

    def callback(message, topic):
        with lock:
            samples[topic]["times"].append(time.monotonic())
            samples[topic]["bytes"] += len(message._buff)

    def cloud_callback(message, topic):
        with lock:
            samples[topic]["times"].append(time.monotonic())
            samples[topic]["bytes"] += len(message.data)
            point_counts[topic].append(message.width * message.height)

    cloud_topics = {
        "/livox/lidar", "/livox/lidar_shifted", "/livox/lidar_merged",
        "/livox/lidar_filtered", "/merged_colored_cloud",
    }
    subscribers = []
    for topic in TOPICS:
        message_type = PointCloud2 if topic in cloud_topics else AnyMsg
        selected_callback = cloud_callback if topic in cloud_topics else callback
        subscribers.append(rospy.Subscriber(
            topic, message_type, selected_callback, callback_args=topic, queue_size=100
        ))
    del subscribers
    start = time.monotonic()
    time.sleep(args.duration)
    elapsed = time.monotonic() - start

    with open(args.output, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "topic", "messages", "wall_seconds", "mean_hz", "mean_period_ms",
            "p95_period_ms", "payload_mib_per_s", "mean_points",
            "mean_payload_kib_per_message",
        ])
        for topic in TOPICS:
            times = samples[topic]["times"]
            periods = [(b - a) * 1000.0 for a, b in zip(times, times[1:])]
            p95 = 0.0
            if periods:
                ordered = sorted(periods)
                p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
            writer.writerow([
                topic,
                len(times),
                f"{elapsed:.6f}",
                f"{len(times) / elapsed:.6f}",
                f"{statistics.mean(periods) if periods else 0.0:.6f}",
                f"{p95:.6f}",
                f"{samples[topic]['bytes'] / elapsed / 1024.0 / 1024.0:.6f}",
                f"{statistics.mean(point_counts[topic]) if point_counts[topic] else 0.0:.3f}",
                f"{samples[topic]['bytes'] / max(1, len(times)) / 1024.0:.6f}",
            ])


if __name__ == "__main__":
    main()
