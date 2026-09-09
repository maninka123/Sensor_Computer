#!/usr/bin/env python3
"""Low-latency ROS image enhancement using the SBC deployment graph."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SBC_DIR = SCRIPT_DIR / "SBC inference"
if not SBC_DIR.is_dir():
    import rospkg

    SBC_DIR = Path(rospkg.RosPack().get_path("node_pc")) / "scripts" / "SBC inference"

# catkin's devel-space wrapper has a fixed system-Python shebang. Re-execute
# with the board's prepared inference environment when it exists, while that
# environment inherits ROS Python packages via --system-site-packages.
configured_python = os.environ.get("NODE_PC_INFERENCE_PYTHON", "")
inference_python = Path(configured_python) if configured_python else SBC_DIR / ".venv/bin/python"
if configured_python and not inference_python.is_file():
    raise RuntimeError("NODE_PC_INFERENCE_PYTHON does not exist: %s" % inference_python)
if (
    inference_python.is_file()
    and os.access(str(inference_python), os.X_OK)
    and os.environ.get("_NODE_PC_INFERENCE_REEXEC") != "1"
    and Path(sys.executable).resolve() != inference_python.resolve()
):
    os.environ["_NODE_PC_INFERENCE_REEXEC"] = "1"
    os.execv(str(inference_python), [str(inference_python), str(Path(__file__).resolve())] + sys.argv[1:])

if str(SBC_DIR) not in sys.path:
    sys.path.insert(0, str(SBC_DIR))

import rospy
# On Ubuntu 20.04 ARM64, importing cv_bridge before cv2 can leave the Boost
# extension without NumPy/OpenCV's symbols and raise an unreported exception.
import cv2  # noqa: F401  (load OpenCV before cv_bridge)
import torch
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32, UInt64

try:
    from runtime import (
        bgr_array_to_tensor,
        configure_cpu,
        default_threads,
        load_model,
        load_onnx_model,
        run_model,
        tensor_to_bgr_array,
    )
except Exception as exc:
    rospy.logerr("Failed to import the SBC inference runtime from %s: %s", SBC_DIR, exc)
    raise


class ImageEnhancerNode:
    def __init__(self):
        self.bridge = CvBridge()
        self.condition = threading.Condition()
        self.generation = 0
        self.pending = None
        self.shutdown_requested = False
        self.received = 0
        self.processed = 0
        self.dropped = 0
        self.warmed_up = False
        self.last_scheduled_time = 0.0
        self.shutdown_event = threading.Event()

        p = rospy.get_param
        self.user_enabled = bool(p("~enabled", False))
        self.enabled = self.user_enabled
        self.thermal_blocked = False
        self.input_topic = p("~input_topic", "/camera/image_raw")
        self.output_topic = p("~output_topic", "/camera/image_enhanced")
        self.enhancement_topic = p("~enhancement_topic", "/image_enhancement")
        self.status_topic = p("~status_topic", self.enhancement_topic + "/status")
        self.temperature_topic = p("~temperature_topic", "/temperature")
        self.temperature_path = Path(str(p(
            "~temperature_path", "/sys/class/thermal/thermal_zone0/temp"
        ))).expanduser()
        self.temperature_poll_interval = max(
            1.0, float(p("~temperature_poll_interval", 30.0))
        )
        self.thermal_protection = bool(p("~thermal_protection", True))
        self.thermal_shutdown_temperature = float(p(
            "~thermal_shutdown_temperature", 85.0
        ))
        self.thermal_resume_temperature = float(p(
            "~thermal_resume_temperature", 70.0
        ))
        self.max_fps = max(0.0, float(p("~max_fps", 5.0)))
        self.backend = str(p("~backend", "torchscript")).lower()
        self.threads = int(p("~threads", default_threads()))
        self.affinity = str(p("~affinity", "auto"))
        self.warmup_runs = max(0, int(p("~warmup_runs", 2)))
        self.queue_size = max(1, int(p("~queue_size", 1)))
        self.buffer_size = int(p("~buffer_size", 16 * 1024 * 1024))

        if self.backend not in ("torchscript", "onnx"):
            raise ValueError("~backend must be 'torchscript' or 'onnx'")
        if self.thermal_resume_temperature >= self.thermal_shutdown_temperature:
            raise ValueError(
                "~thermal_resume_temperature must be lower than "
                "~thermal_shutdown_temperature"
            )

        default_model = SBC_DIR / ("model_cpu.onnx" if self.backend == "onnx" else "model_cpu.pt")
        self.model_path = Path(str(p("~model_path", str(default_model)))).expanduser()
        selected_cpus = configure_cpu(self.threads, self.affinity)
        if self.backend == "onnx":
            self.model = load_onnx_model(self.model_path, self.threads)
        else:
            self.model = load_model(self.model_path)

        self.pub = rospy.Publisher(self.output_topic, Image, queue_size=1)
        self.status_pub = rospy.Publisher(self.status_topic, Bool, queue_size=1, latch=True)
        self.temperature_pub = rospy.Publisher(
            self.temperature_topic, Float32, queue_size=1, latch=True
        )
        self.processed_pub = rospy.Publisher("~processed_frames", UInt64, queue_size=1, latch=True)
        self.dropped_pub = rospy.Publisher("~dropped_frames", UInt64, queue_size=1, latch=True)
        self.sub = rospy.Subscriber(
            self.input_topic,
            Image,
            self.image_cb,
            queue_size=self.queue_size,
            buff_size=self.buffer_size,
        )
        self.toggle_sub = rospy.Subscriber(
            self.enhancement_topic, Bool, self.toggle_cb, queue_size=1
        )
        self._sample_temperature()
        self.status_pub.publish(Bool(data=self.enabled))
        self._publish_counters()

        self.worker = threading.Thread(target=self._worker, name="image-inference", daemon=True)
        self.worker.start()
        self.temperature_worker = threading.Thread(
            target=self._temperature_loop, name="temperature-monitor", daemon=True
        )
        self.temperature_worker.start()
        rospy.on_shutdown(self.shutdown)

        rospy.loginfo(
            "SBC image enhancer ready: enabled=%s backend=%s model=%s threads=%d "
            "affinity=%s input=%s output=%s max_fps=%.2f thermal=%s "
            "shutdown=%.1fC resume=%.1fC temperature_topic=%s",
            self.enabled,
            self.backend,
            self.model_path,
            self.threads,
            selected_cpus or "OS-managed",
            self.input_topic,
            self.output_topic,
            self.max_fps,
            self.thermal_protection,
            self.thermal_shutdown_temperature,
            self.thermal_resume_temperature,
            self.temperature_topic,
        )

    def _publish_counters(self):
        self.processed_pub.publish(UInt64(data=self.processed))
        self.dropped_pub.publish(UInt64(data=self.dropped))

    def toggle_cb(self, msg):
        with self.condition:
            requested = bool(msg.data)
            self.user_enabled = requested
            changed = self._update_effective_state_locked()
            if changed:
                self.generation += 1
                self.last_scheduled_time = 0.0
                if self.pending is not None:
                    self.pending = None
                    self.dropped += 1
            self.condition.notify_all()
            enabled = self.enabled
        self.status_pub.publish(Bool(data=enabled))
        self._publish_counters()
        rospy.loginfo(
            "Image enhancement request=%s effective=%s%s",
            "ON" if requested else "OFF",
            "ON" if enabled else "OFF",
            " (thermal protection active)" if requested and not enabled else "",
        )

    def _update_effective_state_locked(self):
        effective = self.user_enabled and not self.thermal_blocked
        changed = effective != self.enabled
        self.enabled = effective
        return changed

    def _read_temperature(self):
        value = float(self.temperature_path.read_text(encoding="ascii").strip())
        if abs(value) >= 1000.0:
            value /= 1000.0
        if not -40.0 <= value <= 200.0:
            raise ValueError("temperature is outside the valid range: %.3f" % value)
        return value

    def _sample_temperature(self):
        try:
            temperature = self._read_temperature()
            sensor_error = None
        except (OSError, ValueError) as exc:
            temperature = float("nan")
            sensor_error = exc

        with self.condition:
            was_blocked = self.thermal_blocked
            if self.thermal_protection:
                if sensor_error is not None:
                    self.thermal_blocked = True
                elif not self.thermal_blocked and temperature >= self.thermal_shutdown_temperature:
                    self.thermal_blocked = True
                elif self.thermal_blocked and temperature <= self.thermal_resume_temperature:
                    self.thermal_blocked = False
            else:
                self.thermal_blocked = False

            changed = self._update_effective_state_locked()
            if changed:
                self.generation += 1
                self.last_scheduled_time = 0.0
                if self.pending is not None:
                    self.pending = None
                    self.dropped += 1
            enabled = self.enabled
            blocked = self.thermal_blocked
            self.condition.notify_all()

        self.temperature_pub.publish(Float32(data=temperature))
        self.status_pub.publish(Bool(data=enabled))
        if sensor_error is not None:
            rospy.logerr_throttle(
                60.0,
                "Cannot read CPU temperature from %s; enhancement safely disabled: %s",
                self.temperature_path,
                sensor_error,
            )
        elif blocked != was_blocked:
            if blocked:
                rospy.logwarn(
                    "CPU temperature %.1fC reached %.1fC; enhancement disabled until %.1fC",
                    temperature,
                    self.thermal_shutdown_temperature,
                    self.thermal_resume_temperature,
                )
            else:
                rospy.loginfo(
                    "CPU temperature %.1fC is at or below %.1fC; enhancement request restored",
                    temperature,
                    self.thermal_resume_temperature,
                )

    def _temperature_loop(self):
        while not rospy.is_shutdown() and not self.shutdown_event.wait(
            self.temperature_poll_interval
        ):
            self._sample_temperature()

    def image_cb(self, msg):
        with self.condition:
            if not self.enabled:
                return
            self.received += 1
            now = time.monotonic()
            if self.max_fps > 0.0 and (
                now - self.last_scheduled_time
            ) < (1.0 / self.max_fps):
                self.dropped += 1
                return
            self.last_scheduled_time = now
            if self.pending is not None:
                self.dropped += 1
            self.pending = (msg, self.generation)
            self.condition.notify()

    def _worker(self):
        while not rospy.is_shutdown():
            with self.condition:
                while self.pending is None and not self.shutdown_requested and not rospy.is_shutdown():
                    self.condition.wait(timeout=0.5)
                if self.shutdown_requested or rospy.is_shutdown():
                    return
                msg, generation = self.pending
                self.pending = None

            started = time.monotonic()
            try:
                bgr = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
                tensor = bgr_array_to_tensor(bgr)
                with torch.inference_mode():
                    if not self.warmed_up:
                        for _ in range(self.warmup_runs):
                            run_model(self.model, tensor, self.backend)
                        self.warmed_up = True
                    output = run_model(self.model, tensor, self.backend)
                enhanced = tensor_to_bgr_array(output)
                out_msg = self.bridge.cv2_to_imgmsg(enhanced, encoding="bgr8")
                out_msg.header = msg.header
            except Exception as exc:
                with self.condition:
                    self.dropped += 1
                self._publish_counters()
                rospy.logerr_throttle(2.0, "Image enhancement failed; frame dropped: %s", exc)
                continue

            with self.condition:
                if not self.enabled or generation != self.generation:
                    self.dropped += 1
                    publish = False
                else:
                    self.processed += 1
                    publish = True
            self._publish_counters()
            if publish:
                self.pub.publish(out_msg)
                rospy.logdebug(
                    "Enhanced image stamp=%s in %.2f ms",
                    msg.header.stamp,
                    (time.monotonic() - started) * 1000.0,
                )

    def shutdown(self):
        self.shutdown_event.set()
        with self.condition:
            self.shutdown_requested = True
            self.pending = None
            self.condition.notify_all()
        if hasattr(self, "worker") and self.worker.is_alive():
            self.worker.join(timeout=2.0)
        if hasattr(self, "temperature_worker") and self.temperature_worker.is_alive():
            self.temperature_worker.join(timeout=2.0)


def main():
    rospy.init_node("image_enhancer")
    ImageEnhancerNode()
    rospy.spin()


if __name__ == "__main__":
    main()
