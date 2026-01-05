/*
 * ROS node that shifts lidar PointCloud2 timestamps by a configurable offset.
 * Defaults: input /Livox/lidar, output /Livox/lidar_shifted, offset 32.43 seconds.
 */

#include <ros/ros.h>
#include <sensor_msgs/PointCloud2.h>

class LidarTimestampShift
{
public:
  LidarTimestampShift(ros::NodeHandle& nh, ros::NodeHandle& pnh)
  {
    pnh.param<std::string>("input_topic", input_topic_, "/Livox/lidar");
    pnh.param<std::string>("output_topic", output_topic_, "/Livox/lidar_shifted");
    pnh.param<double>("offset_seconds", offset_seconds_, 32.43);

    pub_ = nh.advertise<sensor_msgs::PointCloud2>(output_topic_, 10);
    sub_ = nh.subscribe(input_topic_, 10, &LidarTimestampShift::callback, this);

    ROS_INFO_STREAM("Shifting timestamps on " << input_topic_
                    << " by " << offset_seconds_ << " s and publishing to "
                    << output_topic_);
  }

private:
  void callback(const sensor_msgs::PointCloud2ConstPtr& msg)
  {
    sensor_msgs::PointCloud2 shifted = *msg;
    double new_time = msg->header.stamp.toSec() - offset_seconds_;
    if (new_time < 0.0)
    {
      new_time = 0.0;
    }
    shifted.header.stamp = ros::Time(new_time);
    pub_.publish(shifted);
  }

  std::string input_topic_;
  std::string output_topic_;
  double offset_seconds_{32.43};
  ros::Publisher pub_;
  ros::Subscriber sub_;
};

int main(int argc, char** argv)
{
  ros::init(argc, argv, "lidar_timestamp_shift");
  ros::NodeHandle nh;
  ros::NodeHandle pnh("~");

  LidarTimestampShift node(nh, pnh);
  ros::spin();
  return 0;
}
