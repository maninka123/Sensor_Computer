#!/usr/bin/env python3
"""
Standalone debug viewer for raw vs enhanced camera streams.
Shows both images side-by-side with useful image metrics.

When enhancement toggle is OFF, the enhanced pane is replaced with a notice.
"""

import threading

import cv2
import numpy as np
import rospy
from cv_bridge import CvBridge, CvBridgeError
from sensor_msgs.msg import Image
from std_msgs.msg import Bool


class CompareImageStreamsNode:
    def __init__(self):
        p = rospy.get_param
        self.raw_topic = p("~raw_topic", "/camera/image_raw")
        self.enhanced_topic = p("~enhanced_topic", "/camera/image_enhanced")
        self.toggle_topic = p("~toggle_topic", "/image_enhancement")
        self.toggle_default = bool(p("~toggle_default", False))
        self.window_name = p("~window_name", "Raw vs Enhanced")
        self.target_height = int(p("~target_height", 480))
        self.show_fps = bool(p("~show_fps", True))

        self.bridge = CvBridge()
        self.lock = threading.Lock()

        self.raw_img = None
        self.enhanced_img = None
        self.enhancement_on = self.toggle_default
        self.last_toggle_topic = "startup_default"
        self.last_toggle_time = None

        self.frame_count = 0
        self.last_fps_stamp = rospy.Time.now()
        self.fps = 0.0
        self.raw_msg_count = 0
        self.enh_msg_count = 0
        self.last_rate_stamp = rospy.Time.now()
        self.raw_rate_hz = 0.0
        self.enh_rate_hz = 0.0

        self.raw_sub = rospy.Subscriber(self.raw_topic, Image, self.raw_cb, queue_size=1)
        self.enh_sub = rospy.Subscriber(self.enhanced_topic, Image, self.enhanced_cb, queue_size=1)
        self.toggle_subs = []
        self.toggle_subs.append(
            rospy.Subscriber(self.toggle_topic, Bool, self.toggle_cb, callback_args=self.toggle_topic, queue_size=1)
        )

        inferred_toggle = self.infer_namespaced_toggle_topic(self.raw_topic)
        if inferred_toggle and inferred_toggle != self.toggle_topic:
            self.toggle_subs.append(
                rospy.Subscriber(inferred_toggle, Bool, self.toggle_cb, callback_args=inferred_toggle, queue_size=1)
            )
            rospy.loginfo("Also listening to inferred toggle topic: %s", inferred_toggle)

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        rospy.loginfo(
            "compare_image_streams started. raw=%s enhanced=%s toggle=%s default_toggle=%s",
            self.raw_topic,
            self.enhanced_topic,
            self.toggle_topic,
            self.enhancement_on,
        )

    def raw_cb(self, msg):
        try:
            img = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except CvBridgeError as exc:
            rospy.logwarn_throttle(2.0, "raw cv_bridge error: %s", exc)
            return
        with self.lock:
            self.raw_img = img
            self.raw_msg_count += 1

    def enhanced_cb(self, msg):
        try:
            img = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except CvBridgeError as exc:
            rospy.logwarn_throttle(2.0, "enhanced cv_bridge error: %s", exc)
            return
        with self.lock:
            self.enhanced_img = img
            self.enh_msg_count += 1

    @staticmethod
    def infer_namespaced_toggle_topic(raw_topic):
        parts = [p for p in raw_topic.split("/") if p]
        if len(parts) >= 3 and parts[1] == "camera":
            return "/" + parts[0] + "/image_enhancement"
        return None

    def toggle_cb(self, msg, topic_name):
        with self.lock:
            self.enhancement_on = bool(msg.data)
            self.last_toggle_topic = topic_name
            self.last_toggle_time = rospy.Time.now()

    @staticmethod
    def metrics(img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        contrast = float(np.std(gray))
        min_px = int(np.min(gray))
        max_px = int(np.max(gray))
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        return {
            "brightness": brightness,
            "contrast": contrast,
            "min": min_px,
            "max": max_px,
            "sharpness": sharpness,
        }

    @staticmethod
    def draw_overlay(img, title, m=None, extra_lines=None):
        out = img.copy()
        h, w = out.shape[:2]
        metric_lines = 2 if m is not None else 0
        extra_count = len(extra_lines) if extra_lines else 0
        panel_h = 40 + metric_lines * 24 + extra_count * 22 + 12
        panel_x2 = min(w - 8, 680)
        panel_y2 = min(h - 8, 8 + panel_h)
        cv2.rectangle(out, (8, 8), (panel_x2, panel_y2), (20, 20, 20), -1)
        cv2.rectangle(out, (8, 8), (panel_x2, panel_y2), (90, 90, 90), 1)

        y = 30
        cv2.putText(out, title, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 255, 255), 2, cv2.LINE_AA)
        y += 28

        if m is not None:
            line1 = "Brightness: %.1f  Contrast: %.1f" % (m["brightness"], m["contrast"])
            line2 = "Min/Max: %d/%d  Sharpness: %.1f" % (m["min"], m["max"], m["sharpness"])
            cv2.putText(out, line1, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1, cv2.LINE_AA)
            y += 24
            cv2.putText(out, line2, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1, cv2.LINE_AA)
            y += 24

        if extra_lines:
            for line in extra_lines:
                cv2.putText(out, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (160, 255, 160), 1, cv2.LINE_AA)
                y += 22

        return out

    def letterbox_notice(self, shape_ref, lines):
        h, w = shape_ref[:2]
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        y = h // 2 - 12 * len(lines)
        for line in lines:
            size = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
            x = max(10, (w - size[0]) // 2)
            cv2.putText(canvas, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2, cv2.LINE_AA)
            y += 34
        return canvas

    def resize_to_height(self, img, target_h):
        h, w = img.shape[:2]
        if h == target_h:
            return img
        scale = float(target_h) / float(h)
        target_w = max(1, int(round(w * scale)))
        return cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

    def spin(self):
        rate = rospy.Rate(30)
        while not rospy.is_shutdown():
            with self.lock:
                raw = None if self.raw_img is None else self.raw_img.copy()
                enh = None if self.enhanced_img is None else self.enhanced_img.copy()
                enhancement_on = self.enhancement_on

            if raw is None:
                raw = self.letterbox_notice(
                    (self.target_height, int(self.target_height * 4 / 3), 3),
                    ["Waiting for raw image..."],
                )

            if enhancement_on:
                if enh is None:
                    enh = self.letterbox_notice(raw.shape, ["Enhancement ON", "Waiting for enhanced image..."])
            else:
                enh = self.letterbox_notice(raw.shape, ["Enhancement OFF", "No image to compare"])

            raw = self.resize_to_height(raw, self.target_height)
            enh = self.resize_to_height(enh, self.target_height)

            raw_metrics = self.metrics(raw)
            enh_metrics = None if not enhancement_on else self.metrics(enh)

            self.frame_count += 1
            now = rospy.Time.now()
            elapsed = (now - self.last_fps_stamp).to_sec()
            if elapsed >= 1.0:
                self.fps = self.frame_count / elapsed
                self.frame_count = 0
                self.last_fps_stamp = now
            with self.lock:
                rate_elapsed = (now - self.last_rate_stamp).to_sec()
                if rate_elapsed >= 1.0:
                    self.raw_rate_hz = self.raw_msg_count / rate_elapsed
                    self.enh_rate_hz = self.enh_msg_count / rate_elapsed
                    self.raw_msg_count = 0
                    self.enh_msg_count = 0
                    self.last_rate_stamp = now

            status = "Enhancement: ON" if enhancement_on else "Enhancement: OFF"
            fps_line = "FPS: %.1f" % self.fps if self.show_fps else None
            with self.lock:
                toggle_src = self.last_toggle_topic
                toggle_time = self.last_toggle_time
                raw_rate_hz = self.raw_rate_hz
                enh_rate_hz = self.enh_rate_hz
            if toggle_time is None:
                toggle_line = "Toggle src: %s (no msg yet)" % toggle_src
            else:
                age = (rospy.Time.now() - toggle_time).to_sec()
                toggle_line = "Toggle src: %s (%.1fs ago)" % (toggle_src, age)
            raw_rate_line = "Raw rate: %.1f Hz" % raw_rate_hz
            enh_rate_line = "Enhanced rate: %.1f Hz" % enh_rate_hz

            raw_extra = [status]
            if fps_line:
                raw_extra.append(fps_line)
            raw_extra.append(raw_rate_line)
            raw_extra.append(enh_rate_line)
            raw_extra.append(toggle_line)

            left = self.draw_overlay(raw, "RAW", raw_metrics, raw_extra)

            if enhancement_on:
                delta_b = enh_metrics["brightness"] - raw_metrics["brightness"]
                delta_c = enh_metrics["contrast"] - raw_metrics["contrast"]
                extra = [
                    "Delta Brightness: %+0.1f" % delta_b,
                    "Delta Contrast: %+0.1f" % delta_c,
                    raw_rate_line,
                    enh_rate_line,
                ]
                right = self.draw_overlay(enh, "ENHANCED", enh_metrics, extra)
            else:
                right = self.draw_overlay(enh, "ENHANCED", None, ["Turned OFF", raw_rate_line, enh_rate_line])

            combined = np.hstack([left, right])
            cv2.imshow(self.window_name, combined)

            key = cv2.waitKey(1) & 0xFF
            if key == 27 or key == ord("q"):
                rospy.signal_shutdown("User exit")
                break

            rate.sleep()

        cv2.destroyAllWindows()


def main():
    rospy.init_node("compare_image_streams")
    node = CompareImageStreamsNode()
    node.spin()


if __name__ == "__main__":
    main()
