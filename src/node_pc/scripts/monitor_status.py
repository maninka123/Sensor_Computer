#!/usr/bin/env python3
"""Low-overhead live dashboard for the sensor pipeline.

Only the raw sensor streams are sampled.  Large intermediate clouds are not
subscribed here because doing so copies/deserialises them purely for display.
Fusion synchronization is reported from the colourizer's actual matching
result, not by comparing whichever camera and LiDAR messages arrived last.
"""

import collections
import json
from pathlib import Path
import sys
import time
import threading

import rospy
import rosnode
from sensor_msgs.msg import Image, Imu, PointCloud2
from std_msgs.msg import Bool, Float32, Float64, UInt32


class RateTracker:
    def __init__(self, window_sec=5.0):
        self.window = collections.deque()
        self.window_sec = window_sec
        self.last_wall = None
        self.last_stamp = None
        self.lock = threading.Lock()

    def tick(self, stamp):
        t = stamp.to_sec()
        now = time.time()
        with self.lock:
            self.window.append((t, now))
            self.last_wall = now
            self.last_stamp = t
            # Remove old entries based on wall clock time
            cutoff = now - self.window_sec
            while self.window and self.window[0][1] < cutoff:
                self.window.popleft()

    def hz(self):
        with self.lock:
            if len(self.window) < 2:
                return 0.0
            # Use wall clock time for Hz calculation (more stable)
            dt = self.window[-1][1] - self.window[0][1]
            return (len(self.window) - 1) / dt if dt > 0 else 0.0

    def is_stale(self, max_gap=2.0):
        with self.lock:
            if self.last_wall is None:
                return True
            return (time.time() - self.last_wall) > max_gap

    def get_last_stamp(self):
        with self.lock:
            return self.last_stamp


class TopicMonitor:
    def __init__(self):
        rospy.init_node("node_pc_status_monitor", anonymous=True)
        self.isatty = sys.stdout.isatty()

        self.tracks = {}
        self.enhancement_flag = None
        self.enclosure_correction_flag = None
        self.temperature = None
        self.voxel_enabled = None
        self.voxel_leaf_size = None
        self.matched_frames = None
        self.input_frames = None
        self.point_count = None
        self.dropped_batches = None
        self.rosbridge_running = None
        self.transport_status = None
        self.transport_status_file = Path(
            rospy.get_param(
                "~transport_status_file",
                "/run/node-pc-transport-status.json",
            )
        )
        self.last_node_check = 0.0
        self.enhancement_topic = rospy.get_param(
            "~image_enchantment_topic", "/image_enhancement/status"
        )
        self.enhancement_param = rospy.get_param("/pointcloud_colorizer/image_enchantment", None)
        
        self.min_synchronized_frames = rospy.get_param(
            "/pointcloud_colorizer/min_synchronized_frames", 3
        )

        # Sections and topics (ordered)
        self.sections = [
            ("LiDAR", [
                ("/livox/lidar", PointCloud2, "Raw"),
            ]),
            ("Camera", [
                ("/camera/image_raw", Image, "Raw"),
            ]),
            ("Combined", [
                ("/merged_colored_cloud", PointCloud2, "Colorized cloud"),
            ]),
            ("IMU", [
                ("/livox/imu", Imu, "Raw"),
                ("/imu/data", Imu, "Filtered"),
            ]),
        ]

        for _, items in self.sections:
            for topic, msg_type, _ in items:
                if topic not in self.tracks:
                    self.tracks[topic] = RateTracker()
                    # Decode only the small header-bearing raw sensor messages.
                    # The colourized row is ticked by its tiny status topic.
                    if topic == "/merged_colored_cloud":
                        continue
                    rospy.Subscriber(
                        topic,
                        msg_type if topic == "/camera/image_raw" else rospy.AnyMsg,
                        self._cb,
                        callback_args=topic,
                        queue_size=1,
                        buff_size=16 * 1024 * 1024,
                    )

        rospy.Subscriber(self.enhancement_topic, Bool, self._enh_cb, queue_size=5)
        rospy.Subscriber(
            "/enclosure_correction/status", Bool, self._enclosure_cb, queue_size=1
        )
        rospy.Subscriber("/temperature", Float32, self._temperature_cb, queue_size=1)
        rospy.Subscriber("/voxel_downsampling/status", Bool, self._voxel_cb, queue_size=1)
        rospy.Subscriber("/voxel_leaf_size/status", Float64, self._leaf_size_cb, queue_size=1)
        rospy.Subscriber(
            "/merged_colored_cloud/matched_frames", UInt32, self._matched_cb, queue_size=1
        )
        rospy.Subscriber(
            "/merged_colored_cloud/input_frames", UInt32, self._input_frames_cb, queue_size=1
        )
        rospy.Subscriber(
            "/merged_colored_cloud/point_count", UInt32, self._point_count_cb, queue_size=1
        )
        rospy.Subscriber(
            "/merged_colored_cloud/dropped_batches", UInt32, self._dropped_cb, queue_size=1
        )

        self.report_interval = 1.0
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _cb(self, msg, topic):
        stamp = getattr(msg, "header", None) and msg.header.stamp
        if stamp is None or stamp.to_sec() == 0.0:
            stamp = rospy.Time.now()
        
        self.tracks[topic].tick(stamp)
        
    def _enh_cb(self, msg):
        self.enhancement_flag = bool(msg.data)

    def _enclosure_cb(self, msg):
        self.enclosure_correction_flag = bool(msg.data)

    def _temperature_cb(self, msg):
        self.temperature = float(msg.data)

    def _voxel_cb(self, msg):
        self.voxel_enabled = bool(msg.data)

    def _leaf_size_cb(self, msg):
        self.voxel_leaf_size = float(msg.data)

    def _matched_cb(self, msg):
        self.matched_frames = int(msg.data)

    def _input_frames_cb(self, msg):
        self.input_frames = int(msg.data)
        # A status message is emitted for every completed or dropped fusion
        # batch, so it is an exact lightweight output-processing heartbeat.
        self.tracks["/merged_colored_cloud"].tick(rospy.Time.now())

    def _point_count_cb(self, msg):
        self.point_count = int(msg.data)

    def _dropped_cb(self, msg):
        self.dropped_batches = int(msg.data)

    def _color(self, text, ok):
        if not self.isatty:
            return text
        return f"\033[92m{text}\033[0m" if ok else f"\033[91m{text}\033[0m"

    def _yellow(self, text):
        if not self.isatty:
            return text
        return f"\033[93m{text}\033[0m"

    def _cyan(self, text):
        if not self.isatty:
            return text
        return f"\033[96m{text}\033[0m"

    def _check_rosbridge(self):
        now = time.time()
        if now - self.last_node_check < 5.0:
            return
        self.last_node_check = now
        try:
            self.rosbridge_running = "/rosbridge_websocket" in rosnode.get_node_names()
        except Exception:
            self.rosbridge_running = False
        try:
            with self.transport_status_file.open("r", encoding="utf-8") as stream:
                self.transport_status = json.load(stream)
        except (OSError, ValueError):
            self.transport_status = None

    def _transport_label(self):
        if not self.transport_status:
            return self._yellow("SUPERVISOR STATUS UNAVAILABLE")
        updated = float(self.transport_status.get("updated_unix", 0.0))
        if updated <= 0.0 or time.time() - updated > 10.0:
            return self._yellow("SUPERVISOR STATUS STALE")
        active = self.transport_status.get("active_transport")
        labels = {
            "rosbridge": ("ROSBRIDGE (WEBSOCKET FALLBACK)", True),
            "tcpros": ("TCPROS (DIRECT NATIVE)", True),
            "handoff": ("HANDOFF: TCPROS + ROSBRIDGE", True),
            "fallback_wait": ("NO CLIENT - FALLBACK PENDING", False),
        }
        text, ok = labels.get(active, ("UNKNOWN", False))
        return self._color(text, ok) if ok else self._yellow(text)

    def _on_timer(self, _event):
        self._check_rosbridge()
        lines = []
        lines.append("=" * 60)
        lines.append(self._cyan("  NODE_PC LIVE STATUS"))
        lines.append("=" * 60)

        camera_ok = not self.tracks["/camera/image_raw"].is_stale()
        lidar_ok = not self.tracks["/livox/lidar"].is_stale()
        output_ok = not self.tracks["/merged_colored_cloud"].is_stale()
        pipeline_ok = camera_ok and lidar_ok and output_ok
        lines.append("\n== Overall ==")
        lines.append(
            f"  Pipeline:   {self._color('RUNNING', True) if pipeline_ok else self._color('WAITING / FAULT', False)}"
        )
        lines.append(
            f"  Camera:     {self._color('RUNNING', True) if camera_ok else self._color('NO DATA', False)}"
        )
        lines.append(
            f"  LiDAR:      {self._color('RUNNING', True) if lidar_ok else self._color('NO DATA', False)}"
        )
        lines.append(
            f"  ROSBridge:  {self._color('RUNNING', True) if self.rosbridge_running else self._color('NOT FOUND', False)}"
        )

        lines.append("\n== Client Transport ==")
        lines.append(f"  Active:               {self._transport_label()}")
        if self.transport_status:
            updated = float(self.transport_status.get("updated_unix", 0.0))
            age = max(0.0, time.time() - updated) if updated > 0.0 else float("inf")
            if age <= 10.0:
                heartbeat = self._color("HEALTHY", True)
            elif age == float("inf"):
                heartbeat = self._yellow("UNKNOWN")
            else:
                heartbeat = self._yellow(f"STALE ({age:.1f} s)")
            lines.append(f"  Supervisor heartbeat: {heartbeat}")
            clients = self.transport_status.get("native_clients") or []
            if clients:
                for client in clients:
                    topics = ", ".join(client.get("topics") or [])
                    lines.append(
                        "  Native client:        %s @ %s"
                        % (client.get("node", "unknown"), client.get("host", "unknown"))
                    )
                    lines.append(f"  Direct topics:        {topics or 'unknown'}")
            else:
                lines.append("  Direct payload client: none detected")
            for node in self.transport_status.get("remote_ros_nodes") or []:
                name = node.get("node", "unknown")
                host = node.get("host", "unknown")
                path = node.get("path")
                lines.append(f"  Remote ROS node:      {name} @ {host}")
                if path == "rosbridge_relay":
                    topics = ", ".join(node.get("bridge_relay_topics") or [])
                    lines.append(
                        f"  Data path:            ROSBridge relay ({topics or 'unknown'})"
                    )
                elif path == "tcpros_direct":
                    topics = ", ".join(node.get("direct_topics") or [])
                    lines.append(f"  Data path:            direct TCPROS ({topics or 'unknown'})")
                elif path == "mixed":
                    lines.append("  Data path:            mixed TCPROS + ROSBridge relay")
                else:
                    lines.append("  Data path:            registered; no TCPROS payload yet")
            error = self.transport_status.get("error")
            if error:
                lines.append(f"  Supervisor warning:   {self._yellow(error)}")
        
        for title, items in self.sections:
            lines.append(f"\n== {title} ==")
            for topic, _, label in items:
                tracker = self.tracks.get(topic)
                hz = tracker.hz() if tracker else 0.0
                stale = tracker.is_stale() if tracker else True
                last_stamp = tracker.get_last_stamp() if tracker else None
                
                status = self._color(f"{hz:6.2f} Hz", not stale and hz > 0.01)
                stamp_str = f"[stamp: {last_stamp:.2f}]" if last_stamp else "[no data]"
                lines.append(f"  {label:15s} {status}  {stamp_str}")

        # This is the colourizer's real nearest-image matching result.  A
        # latest-vs-latest timestamp comparison is invalid for 10 Hz LiDAR and
        # 35 Hz camera streams and used to make the dashboard flicker red.
        lines.append("\n== Fusion Synchronization (actual batch result) ==")
        if self.matched_frames is None or self.input_frames is None:
            lines.append(f"  Status:               {self._yellow('Waiting for data...')}")
        else:
            valid = self.matched_frames >= self.min_synchronized_frames
            complete = self.matched_frames == self.input_frames
            if complete:
                label = "SYNCED"
            elif valid:
                label = "SYNCED (PARTIAL)"
            else:
                label = "DROPPED / INSUFFICIENT MATCHES"
            lines.append(
                f"  Matched frames:       {self.matched_frames}/{self.input_frames}"
            )
            lines.append(
                f"  Required minimum:     {self.min_synchronized_frames}"
            )
            lines.append(f"  Status:               {self._color(label, valid)}")

        # Enhancement status
        lines.append(f"\n== Image Enhancement ==")
        enh_bits = []
        if self.enhancement_flag is not None:
            enh_bits.append(f"topic={self.enhancement_flag}")
        if self.enhancement_param is not None:
            enh_bits.append(f"param={bool(self.enhancement_param)}")
        enh_status = " / ".join(enh_bits) if enh_bits else "unknown"
        lines.append(f"  Status: {enh_status}")
        enclosure_status = (
            "unknown"
            if self.enclosure_correction_flag is None
            else ("ON" if self.enclosure_correction_flag else "OFF")
        )
        lines.append(f"  Enclosure correction: {enclosure_status}")

        # Temperature and processing configuration/status.
        lines.append("\n== System and Output ==")
        if self.temperature is None:
            temp_text = self._yellow("waiting...")
        elif self.temperature >= 85.0:
            temp_text = self._color(f"{self.temperature:.1f} C  THERMAL PROTECTION", False)
        elif self.temperature >= 80.0:
            temp_text = self._yellow(f"{self.temperature:.1f} C  HOT")
        else:
            temp_text = self._color(f"{self.temperature:.1f} C", True)
        lines.append(f"  CPU temperature:      {temp_text}")
        voxel_text = "unknown" if self.voxel_enabled is None else ("ON" if self.voxel_enabled else "OFF")
        leaf_text = "unknown" if self.voxel_leaf_size is None else f"{self.voxel_leaf_size:.3f} m"
        lines.append(f"  Voxel downsampling:   {voxel_text}")
        lines.append(f"  Voxel leaf size:      {leaf_text}")
        matched_text = (
            "unknown"
            if self.matched_frames is None
            else f"{self.matched_frames}/{self.input_frames if self.input_frames is not None else '?'}"
        )
        point_text = "unknown" if self.point_count is None else f"{self.point_count:,}"
        dropped_text = "unknown" if self.dropped_batches is None else f"{self.dropped_batches:,}"
        lines.append(f"  Matched frames:       {matched_text}")
        lines.append(f"  Output points:        {point_text}")
        lines.append(f"  Dropped batches:      {dropped_text}")

        lines.append("\n" + "=" * 60)
        lines.append(f"  Updated: {time.strftime('%H:%M:%S')}")
        lines.append("=" * 60)

        # Clear screen and print
        if self.isatty:
            sys.stdout.write("\033[H\033[J")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()

    def _loop(self):
        while not rospy.is_shutdown() and not self._stop:
            self._on_timer(None)
            time.sleep(self.report_interval)


if __name__ == "__main__":
    try:
        TopicMonitor()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
