#!/usr/bin/env python3
"""Publish synthetic clouds with the final timestamp-aware output layout."""

import math
import struct

import rospy
from sensor_msgs.msg import PointCloud2, PointField


POINT_STEP = 36
FIELDS = [
    PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
    PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
    PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
    PointField(name="rgb", offset=12, datatype=PointField.FLOAT32, count=1),
    PointField(name="source_frame_index", offset=16, datatype=PointField.UINT32, count=1),
    PointField(name="source_frame_stamp_sec", offset=20, datatype=PointField.UINT32, count=1),
    PointField(name="source_frame_stamp_nsec", offset=24, datatype=PointField.UINT32, count=1),
    PointField(name="image_stamp_sec", offset=28, datatype=PointField.UINT32, count=1),
    PointField(name="image_stamp_nsec", offset=32, datatype=PointField.UINT32, count=1),
]


def build_payload(point_count, source_frame_count, newest_stamp, source_period):
    payload = bytearray(point_count * POINT_STEP)
    stamps = []
    for source_index in range(source_frame_count):
        age = (source_frame_count - 1 - source_index) * source_period
        stamps.append(newest_stamp - rospy.Duration.from_sec(age))

    for index in range(point_count):
        source_index = min(source_frame_count - 1, index * source_frame_count // point_count)
        angle = 2.0 * math.pi * index / max(point_count, 1)
        ring = index % 32
        radius = 2.0 + 0.02 * ring
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        z = 1.0 + 0.02 * ring
        red = index % 256
        green = (index * 3) % 256
        blue = (255 - index) % 256
        rgb_bits = (red << 16) | (green << 8) | blue
        stamp = stamps[source_index]

        base = index * POINT_STEP
        struct.pack_into("<fffI", payload, base, x, y, z, rgb_bits)
        struct.pack_into(
            "<IIIII",
            payload,
            base + 16,
            source_index,
            stamp.secs,
            stamp.nsecs,
            stamp.secs,
            stamp.nsecs,
        )
    return bytes(payload)


def main():
    rospy.init_node("synthetic_pointcloud_publisher")
    topic = rospy.get_param("~topic", "/merged_colored_cloud")
    frame_id = rospy.get_param("~frame_id", "livox_frame")
    rate_hz = float(rospy.get_param("~rate", 10.0))
    point_count = int(rospy.get_param("~point_count", 10000))
    source_frame_count = int(rospy.get_param("~source_frame_count", 10))

    if rate_hz <= 0.0:
        raise ValueError("~rate must be greater than zero")
    if point_count < 1:
        raise ValueError("~point_count must be at least one")
    if source_frame_count < 1:
        raise ValueError("~source_frame_count must be at least one")

    message = PointCloud2()
    message.header.frame_id = frame_id
    message.height = 1
    message.width = point_count
    message.fields = FIELDS
    message.is_bigendian = False
    message.point_step = POINT_STEP
    message.row_step = POINT_STEP * point_count
    message.is_dense = True

    publisher = rospy.Publisher(topic, PointCloud2, queue_size=1)
    rate = rospy.Rate(rate_hz)
    rospy.logwarn(
        "Publishing SYNTHETIC timestamp-aware PointCloud2 on %s: %.3f Hz, "
        "%d points across %d source frames",
        topic,
        rate_hz,
        point_count,
        source_frame_count,
    )
    while not rospy.is_shutdown():
        message.header.stamp = rospy.Time.now()
        message.data = build_payload(
            point_count,
            source_frame_count,
            message.header.stamp,
            1.0 / rate_hz,
        )
        publisher.publish(message)
        rate.sleep()


if __name__ == "__main__":
    main()
