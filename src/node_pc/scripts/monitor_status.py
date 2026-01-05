#!/usr/bin/env python3
"""
ROS monitor that keeps a single updating dashboard:
- Live Hz per topic (green = receiving, red = stale).
- Enhancement status from topic and param.
"""

import collections
import sys
import time

import rospy
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Image, Imu, PointCloud2
from std_msgs.msg import Bool


class RateTracker:
    def __init__(self, window_sec=5.0):
        self.window = collections.deque()
        self.window_sec = window_sec
        self.last_wall = None

    def tick(self, stamp):
        t = stamp.to_sec()
        self.window.append(t)
        self.last_wall = time.time()
        cutoff = t - self.window_sec
        while self.window and self.window[0] < cutoff:
            self.window.popleft()

    def hz(self):
        if len(self.window) < 2:
            return 0.0
        dt = self.window[-1] - self.window[0]
        return (len(self.window) - 1) / dt if dt > 0 else 0.0

    def is_stale(self, max_gap=2.0):
        if self.last_wall is None:
            return True
        return (time.time() - self.last_wall) > max_gap


class TopicMonitor:
    def __init__(self):
        rospy.init_node("node_pc_status_monitor", anonymous=True)
        self.isatty = sys.stdout.isatty()

        self.tracks = {}
        self.enhancement_flag = None
        self.enhancement_topic = rospy.get_param("~image_enchantment_topic", "/image_enhancement")
        self.enhancement_param = rospy.get_param("/pointcloud_colorizer/image_enchantment", None)

        # Sections and topics (ordered)
        self.sections = [
            ("LiDAR", [
                ("/livox/lidar", PointCloud2, "Raw"),
                ("/livox/lidar_shifted", PointCloud2, "Shifted"),
                ("/livox/lidar_merged", PointCloud2, "Merged"),
            ]),
            ("Camera", [
                ("/camera/image_raw", Image, "Raw"),
                ("/camera/image_enhanced", Image, "Enhanced"),
            ]),
            ("Combined", [
                ("/merged_colored_cloud", PointCloud2, "Colorized cloud"),
            ]),
            ("IMU", [
                ("/livox/imu", Imu, "Raw"),
                ("/imu/data", Imu, "Filtered"),
            ]),
            ("System", [
                ("/clock", Clock, "Clock"),
            ]),
        ]

        for _, items in self.sections:
            for topic, msg_type, _ in items:
                if topic not in self.tracks:
                    self.tracks[topic] = RateTracker()
                    rospy.Subscriber(topic, msg_type, self._cb, callback_args=topic, queue_size=5)

        rospy.Subscriber(self.enhancement_topic, Bool, self._enh_cb, queue_size=5)

        self.report_interval = 1.0
        self.timer = rospy.Timer(rospy.Duration(self.report_interval), self._on_timer)

    def _cb(self, msg, topic):
        stamp = getattr(msg, "header", None) and msg.header.stamp
        if stamp is None or stamp.to_sec() == 0.0:
            stamp = rospy.Time.now()
        self.tracks[topic].tick(stamp)

    def _enh_cb(self, msg):
        self.enhancement_flag = bool(msg.data)

    def _color(self, text, ok):
        if not self.isatty:
            return text
        return f"\033[92m{text}\033[0m" if ok else f"\033[91m{text}\033[0m"

    def _on_timer(self, _event):
        lines = []
        for title, items in self.sections:
            lines.append(f"== {title} ==")
            for topic, _, label in items:
                tracker = self.tracks.get(topic)
                hz = tracker.hz() if tracker else 0.0
                stale = tracker.is_stale() if tracker else True
                status = self._color(f"{hz:6.2f} Hz", not stale and hz > 0.01)
                lines.append(f"{label:15s} {status}  ({topic})")
            lines.append("")

        enh_bits = []
        if self.enhancement_flag is not None:
            enh_bits.append(f"topic={self.enhancement_flag}")
        if self.enhancement_param is not None:
            enh_bits.append(f"param={bool(self.enhancement_param)}")
        enh_status = " / ".join(enh_bits) if enh_bits else "unknown"
        lines.append(f"Image enhancement: {enh_status}")

        sys.stdout.write("\033[H\033[J") if self.isatty else None
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    try:
        TopicMonitor()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
