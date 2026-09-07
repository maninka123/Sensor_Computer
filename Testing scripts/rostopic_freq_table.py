#!/usr/bin/env python3
import argparse
import collections
import signal
import sys
import threading
import time

import rospy
from rostopic import ROSTopicException
from sensor_msgs.msg import Image, PointCloud2


RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"


class TopicMonitor:
    def __init__(self, window_sec: float):
        self.window_sec = window_sec
        self.lock = threading.Lock()
        self.samples = {}  # topic -> deque[timestamp]
        self.msg_types = {}  # topic -> type string
        self.meta = {}  # topic -> dict(width,height,points)
        self.subscribers = {}  # topic -> rospy.Subscriber

    def update_topics(self):
        try:
            published = rospy.get_published_topics(namespace="/")
        except ROSTopicException:
            return
        except Exception:
            return

        with self.lock:
            for topic, msg_type in published:
                if topic not in self.subscribers:
                    self.samples[topic] = collections.deque()
                    self.msg_types[topic] = msg_type
                    self.meta[topic] = {"width": "-", "height": "-", "points": "-"}
                    if msg_type == "sensor_msgs/Image":
                        self.subscribers[topic] = rospy.Subscriber(
                            topic,
                            Image,
                            callback=self._make_image_callback(topic),
                            queue_size=100,
                        )
                    elif msg_type == "sensor_msgs/PointCloud2":
                        self.subscribers[topic] = rospy.Subscriber(
                            topic,
                            PointCloud2,
                            callback=self._make_cloud_callback(topic),
                            queue_size=100,
                        )
                    else:
                        self.subscribers[topic] = rospy.Subscriber(
                            topic,
                            rospy.AnyMsg,
                            callback=self._make_callback(topic),
                            queue_size=100,
                        )
                else:
                    self.msg_types[topic] = msg_type

            removed = [t for t in self.subscribers if t not in {p[0] for p in published}]
            for topic in removed:
                try:
                    self.subscribers[topic].unregister()
                except Exception:
                    pass
                self.subscribers.pop(topic, None)
                self.samples.pop(topic, None)
                self.msg_types.pop(topic, None)
                self.meta.pop(topic, None)

    def _make_callback(self, topic):
        def _cb(_msg):
            now = time.monotonic()
            with self.lock:
                dq = self.samples.get(topic)
                if dq is None:
                    return
                dq.append(now)
                cutoff = now - self.window_sec
                while dq and dq[0] < cutoff:
                    dq.popleft()

        return _cb

    def _make_image_callback(self, topic):
        def _cb(msg):
            now = time.monotonic()
            with self.lock:
                dq = self.samples.get(topic)
                if dq is None:
                    return
                dq.append(now)
                cutoff = now - self.window_sec
                while dq and dq[0] < cutoff:
                    dq.popleft()
                self.meta[topic] = {
                    "width": int(msg.width),
                    "height": int(msg.height),
                    "points": "-",
                }

        return _cb

    def _make_cloud_callback(self, topic):
        def _cb(msg):
            now = time.monotonic()
            with self.lock:
                dq = self.samples.get(topic)
                if dq is None:
                    return
                dq.append(now)
                cutoff = now - self.window_sec
                while dq and dq[0] < cutoff:
                    dq.popleft()
                points = int(msg.width) * int(msg.height)
                self.meta[topic] = {
                    "width": int(msg.width),
                    "height": int(msg.height),
                    "points": points,
                }

        return _cb

    def snapshot_rows(self):
        with self.lock:
            rows = []
            now = time.monotonic()
            for topic in sorted(self.samples.keys()):
                dq = self.samples[topic]
                cutoff = now - self.window_sec
                while dq and dq[0] < cutoff:
                    dq.popleft()

                hz = 0.0
                if len(dq) >= 2:
                    dt = dq[-1] - dq[0]
                    if dt > 0:
                        hz = (len(dq) - 1) / dt

                md = self.meta.get(topic, {"width": "-", "height": "-", "points": "-"})
                rows.append(
                    (
                        topic,
                        self.msg_types.get(topic, "unknown"),
                        hz,
                        md.get("width", "-"),
                        md.get("height", "-"),
                        md.get("points", "-"),
                    )
                )
            return rows


def color_for_hz(hz: float) -> str:
    if hz <= 0.01:
        return RED
    if hz < 5.0:
        return YELLOW
    return GREEN


def render_table(rows, window_sec, refresh_sec):
    name_header = "Topic"
    type_header = "Msg Type"
    width_header = "Width"
    height_header = "Height"
    points_header = "Points"
    hz_header = "Hz"

    name_w = max(len(name_header), *(len(r[0]) for r in rows)) if rows else len(name_header)
    type_w = max(len(type_header), *(len(r[1]) for r in rows)) if rows else len(type_header)
    width_w = max(len(width_header), *(len(str(r[3])) for r in rows)) if rows else len(width_header)
    height_w = max(len(height_header), *(len(str(r[4])) for r in rows)) if rows else len(height_header)
    points_w = max(len(points_header), *(len(str(r[5])) for r in rows)) if rows else len(points_header)
    hz_w = max(len(hz_header), 8)

    top = (
        f"+{'-' * (name_w + 2)}+{'-' * (type_w + 2)}+{'-' * (width_w + 2)}"
        f"+{'-' * (height_w + 2)}+{'-' * (points_w + 2)}+{'-' * (hz_w + 2)}+"
    )
    mid = top

    title = f"ROS Topic Frequency Monitor  window={window_sec:.1f}s  refresh={refresh_sec:.1f}s"
    lines = []
    lines.append(f"{BOLD}{CYAN}{title}{RESET}")
    lines.append(f"{DIM}Press Ctrl+C to exit{RESET}")
    lines.append(f"{BLUE}{top}{RESET}")
    lines.append(
        f"{BLUE}|{RESET} {BOLD}{name_header.ljust(name_w)}{RESET} "
        f"{BLUE}|{RESET} {BOLD}{type_header.ljust(type_w)}{RESET} "
        f"{BLUE}|{RESET} {BOLD}{width_header.rjust(width_w)}{RESET} "
        f"{BLUE}|{RESET} {BOLD}{height_header.rjust(height_w)}{RESET} "
        f"{BLUE}|{RESET} {BOLD}{points_header.rjust(points_w)}{RESET} "
        f"{BLUE}|{RESET} {BOLD}{hz_header.rjust(hz_w)}{RESET} {BLUE}|{RESET}"
    )
    lines.append(f"{BLUE}{mid}{RESET}")

    if not rows:
        msg = "No topics available"
        lines.append(
            f"{BLUE}|{RESET} {msg.ljust(name_w)} {BLUE}|{RESET} {'-'.ljust(type_w)} "
            f"{BLUE}|{RESET} {'-'.rjust(width_w)} {BLUE}|{RESET} {'-'.rjust(height_w)} "
            f"{BLUE}|{RESET} {'-'.rjust(points_w)} {BLUE}|{RESET} {'-'.rjust(hz_w)} {BLUE}|{RESET}"
        )
    else:
        for topic, msg_type, hz, width, height, points in rows:
            hz_text = f"{hz:8.2f}"
            hz_col = color_for_hz(hz)
            lines.append(
                f"{BLUE}|{RESET} {topic.ljust(name_w)} {BLUE}|{RESET} {msg_type.ljust(type_w)} "
                f"{BLUE}|{RESET} {str(width).rjust(width_w)} {BLUE}|{RESET} {str(height).rjust(height_w)} "
                f"{BLUE}|{RESET} {str(points).rjust(points_w)} "
                f"{BLUE}|{RESET} {hz_col}{hz_text}{RESET} {BLUE}|{RESET}"
            )

    lines.append(f"{BLUE}{top}{RESET}")
    return "\n".join(lines), len(lines)


def main():
    parser = argparse.ArgumentParser(description="Show ROS topic frequencies in a colored table")
    parser.add_argument("--window", type=float, default=5.0, help="frequency window in seconds (default: 5.0)")
    parser.add_argument("--refresh", type=float, default=1.0, help="display refresh in seconds (default: 1.0)")
    args = parser.parse_args()

    rospy.init_node("rostopic_freq_table", anonymous=True, disable_signals=True)

    stop = False

    def _handle_signal(_sig, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    monitor = TopicMonitor(window_sec=max(0.5, args.window))

    last_lines = 0
    while not stop and not rospy.is_shutdown():
        monitor.update_topics()
        rows = monitor.snapshot_rows()
        table_text, line_count = render_table(
            rows, window_sec=max(0.5, args.window), refresh_sec=max(0.2, args.refresh)
        )
        if last_lines == 0:
            sys.stdout.write("\033[2J\033[H")
        else:
            sys.stdout.write(f"\033[{last_lines}F\033[J")
        sys.stdout.write(table_text + "\n")
        sys.stdout.flush()
        last_lines = line_count
        time.sleep(max(0.2, args.refresh))


if __name__ == "__main__":
    main()
