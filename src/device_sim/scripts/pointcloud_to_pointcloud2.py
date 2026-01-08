#!/usr/bin/env python3
import rospy
from sensor_msgs.msg import PointCloud, PointCloud2
from sensor_msgs.msg import PointField
import sensor_msgs.point_cloud2 as pc2


def _build_fields(channels):
    fields = [
        PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
        PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
        PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
    ]
    offset = 12
    for channel in channels:
        fields.append(
            PointField(name=channel.name, offset=offset, datatype=PointField.FLOAT32, count=1)
        )
        offset += 4
    return fields


def _build_points(msg):
    channel_values = [c.values for c in msg.channels]
    for i, pt in enumerate(msg.points):
        row = [pt.x, pt.y, pt.z]
        for values in channel_values:
            row.append(values[i] if i < len(values) else 0.0)
        yield row


def callback(msg, pub):
    fields = _build_fields(msg.channels)
    points = list(_build_points(msg))
    cloud = pc2.create_cloud(msg.header, fields, points)
    pub.publish(cloud)


def main():
    rospy.init_node("pointcloud_to_pointcloud2")
    input_topic = rospy.get_param("~input_topic", "/livox/lidar_raw")
    output_topic = rospy.get_param("~output_topic", "/livox/lidar")

    pub = rospy.Publisher(output_topic, PointCloud2, queue_size=5)
    rospy.Subscriber(input_topic, PointCloud, callback, pub)

    rospy.spin()


if __name__ == "__main__":
    main()
