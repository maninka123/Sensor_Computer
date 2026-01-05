#!/usr/bin/env python3
import os
import sys
import rospy
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError

# Ensure we can import the lidar_image_model bundled under scripts/Image_enchancemet
script_dir = os.path.dirname(os.path.realpath(__file__))
enh_dir = os.path.join(script_dir, "Image_enchancemet")
if enh_dir not in sys.path:
    sys.path.append(enh_dir)

try:
    import lidar_image_model  # noqa: E402
except Exception as exc:
    rospy.logerr("Failed to import lidar_image_model from Image_enchancemet: %s", exc)
    raise


class ImageEnhancerNode:
    def __init__(self):
        self.bridge = CvBridge()

        p = rospy.get_param
        self.enabled = bool(p("~enabled", False))
        self.input_topic = p("~input_topic", "/camera/image_raw")
        self.output_topic = p("~output_topic", "/camera/image_enhanced")
        self.queue_size = int(p("~queue_size", 5))

        self.sub = rospy.Subscriber(self.input_topic, Image, self.callback, queue_size=self.queue_size)
        self.pub = rospy.Publisher(self.output_topic, Image, queue_size=1)

        rospy.loginfo(
            "Image enhancer started. enabled=%s, input=%s, output=%s",
            self.enabled,
            self.input_topic,
            self.output_topic,
        )

    def callback(self, msg: Image):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except CvBridgeError as exc:
            rospy.logwarn_throttle(2.0, "cv_bridge error: %s", exc)
            return

        if self.enabled:
            try:
                enhanced = lidar_image_model.process_image(cv_image)
            except Exception as exc:
                rospy.logwarn_throttle(2.0, "Enhancement failed, forwarding raw image. Error: %s", exc)
                enhanced = cv_image
        else:
            enhanced = cv_image

        try:
            out_msg = self.bridge.cv2_to_imgmsg(enhanced, encoding="bgr8")
        except CvBridgeError as exc:
            rospy.logwarn_throttle(2.0, "cv_bridge encode error: %s", exc)
            return

        out_msg.header = msg.header
        self.pub.publish(out_msg)


def main():
    rospy.init_node("image_enhancer")
    ImageEnhancerNode()
    rospy.spin()


if __name__ == "__main__":
    main()
