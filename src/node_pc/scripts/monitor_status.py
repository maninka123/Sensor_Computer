#!/usr/bin/env python3
"""
ROS monitor that keeps a single updating dashboard:
- Live Hz per topic (green = receiving, red = stale).
- Timestamp offset between shifted LiDAR and camera image.
- Enhancement status from topic and param.
"""

import collections
import sys
import time
import threading
from collections import deque

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


class TimestampSyncTracker:
    """Tracks timestamp differences between two topics for sync monitoring."""
    def __init__(self, max_samples=100):
        self.lidar_stamps = deque(maxlen=max_samples)
        self.camera_stamps = deque(maxlen=max_samples)
        self.offsets = deque(maxlen=max_samples)
        self.lock = threading.Lock()
        self.last_lidar_stamp = None
        self.last_camera_stamp = None
        self.last_offset = None

    def update_lidar(self, stamp):
        t = stamp.to_sec()
        with self.lock:
            self.last_lidar_stamp = t
            self.lidar_stamps.append((t, time.time()))
            self._compute_offset()

    def update_camera(self, stamp):
        t = stamp.to_sec()
        with self.lock:
            self.last_camera_stamp = t
            self.camera_stamps.append((t, time.time()))
            self._compute_offset()

    def _compute_offset(self):
        """Find closest matching timestamps and compute offset."""
        if not self.lidar_stamps or not self.camera_stamps:
            return
        
        # Get most recent stamps
        lidar_t = self.lidar_stamps[-1][0]
        camera_t = self.camera_stamps[-1][0]
        
        # Only compute if both were received recently (within 1 sec wall time)
        lidar_wall = self.lidar_stamps[-1][1]
        camera_wall = self.camera_stamps[-1][1]
        
        if abs(lidar_wall - camera_wall) < 1.0:
            offset = lidar_t - camera_t
            self.last_offset = offset
            self.offsets.append(offset)

    def get_stats(self):
        with self.lock:
            if not self.offsets:
                return None, None, None, None
            
            offsets_list = list(self.offsets)
            mean_offset = sum(offsets_list) / len(offsets_list)
            min_offset = min(offsets_list)
            max_offset = max(offsets_list)
            
            return self.last_offset, mean_offset, min_offset, max_offset

    def get_last_stamps(self):
        with self.lock:
            return self.last_lidar_stamp, self.last_camera_stamp


class TopicMonitor:
    def __init__(self):
        rospy.init_node("node_pc_status_monitor", anonymous=True)
        self.isatty = sys.stdout.isatty()

        self.tracks = {}
        self.enhancement_flag = None
        self.temperature = None
        self.voxel_enabled = None
        self.voxel_leaf_size = None
        self.matched_frames = None
        self.input_frames = None
        self.point_count = None
        self.dropped_batches = None
        self.rosbridge_running = None
        self.last_node_check = 0.0
        self.enhancement_topic = rospy.get_param(
            "~image_enchantment_topic", "/image_enhancement/status"
        )
        self.enhancement_param = rospy.get_param("/pointcloud_colorizer/image_enchantment", None)
        
        # Sync tolerance from config (default 0.1 sec)
        self.sync_tolerance = rospy.get_param("/monitor_status/sync_tolerance", 0.1)

        # Sync tracker for shifted LiDAR vs camera
        self.sync_tracker = TimestampSyncTracker()

        # Sections and topics (ordered)
        self.sections = [
            ("LiDAR", [
                ("/livox/lidar", PointCloud2, "Raw"),
                ("/livox/lidar_shifted", PointCloud2, "Shifted"),
                ("/livox/lidar_merged", PointCloud2, "Merged"),
                ("/livox/lidar_filtered", PointCloud2, "Per-frame filtered"),
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
        ]

        for _, items in self.sections:
            for topic, msg_type, _ in items:
                if topic not in self.tracks:
                    self.tracks[topic] = RateTracker()
                    # Only these two streams need decoded headers for sync.
                    # AnyMsg avoids deserialising every point/image payload for
                    # rate-only rows, keeping the monitor lightweight.
                    subscription_type = (
                        msg_type
                        if topic in ("/livox/lidar_shifted", "/camera/image_raw")
                        else rospy.AnyMsg
                    )
                    rospy.Subscriber(
                        topic,
                        subscription_type,
                        self._cb,
                        callback_args=topic,
                        queue_size=1,
                        buff_size=16 * 1024 * 1024,
                    )

        rospy.Subscriber(self.enhancement_topic, Bool, self._enh_cb, queue_size=5)
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
        
        # Track sync between shifted lidar and camera
        if topic == "/livox/lidar_shifted":
            self.sync_tracker.update_lidar(stamp)
        elif topic == "/camera/image_raw":
            self.sync_tracker.update_camera(stamp)

    def _enh_cb(self, msg):
        self.enhancement_flag = bool(msg.data)

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

        # Sync status between shifted LiDAR and camera
        lines.append(f"\n== Timestamp Sync (LiDAR_shifted vs Camera) ==")
        last_offset, mean_offset, min_offset, max_offset = self.sync_tracker.get_stats()
        lidar_stamp, camera_stamp = self.sync_tracker.get_last_stamps()
        
        if lidar_stamp is not None and camera_stamp is not None:
            lines.append(f"  LiDAR shifted stamp:  {lidar_stamp:.3f}")
            lines.append(f"  Camera stamp:         {camera_stamp:.3f}")
            
            if last_offset is not None:
                # Good sync if offset is within sync_tolerance from config
                sync_ok = abs(last_offset) < self.sync_tolerance
                offset_str = self._color(f"{last_offset:+.4f} sec", sync_ok)
                lines.append(f"  Current offset:       {offset_str}")
                lines.append(f"  Mean offset:          {mean_offset:+.4f} sec")
                lines.append(f"  Range:                [{min_offset:+.4f}, {max_offset:+.4f}] sec")
                lines.append(f"  Sync tolerance:       {self.sync_tolerance:.4f} sec")
                
                if sync_ok:
                    lines.append(f"  Status:               {self._color('SYNCED', True)}")
                else:
                    lines.append(f"  Status:               {self._color('OUT OF SYNC', False)}")
            else:
                lines.append(f"  Offset:               {self._yellow('calculating...')}")
        else:
            lines.append(f"  Status:               {self._yellow('Waiting for data...')}")

        # Enhancement status
        lines.append(f"\n== Image Enhancement ==")
        enh_bits = []
        if self.enhancement_flag is not None:
            enh_bits.append(f"topic={self.enhancement_flag}")
        if self.enhancement_param is not None:
            enh_bits.append(f"param={bool(self.enhancement_param)}")
        enh_status = " / ".join(enh_bits) if enh_bits else "unknown"
        lines.append(f"  Status: {enh_status}")

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
