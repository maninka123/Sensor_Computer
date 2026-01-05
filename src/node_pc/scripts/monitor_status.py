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
from sensor_msgs.msg import Image, Imu, PointCloud2
from std_msgs.msg import Bool


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
        self.enhancement_topic = rospy.get_param("~image_enchantment_topic", "/image_enhancement")
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
                    rospy.Subscriber(topic, msg_type, self._cb, callback_args=topic, queue_size=5)

        rospy.Subscriber(self.enhancement_topic, Bool, self._enh_cb, queue_size=5)

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

    def _color(self, text, ok):
        if not self.isatty:
            return text
        return f"\033[92m{text}\033[0m" if ok else f"\033[91m{text}\033[0m"

    def _yellow(self, text):
        if not self.isatty:
            return text
        return f"\033[93m{text}\033[0m"

    def _on_timer(self, _event):
        lines = []
        lines.append("=" * 60)
        lines.append("  NODE_PC STATUS MONITOR")
        lines.append("=" * 60)
        
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
