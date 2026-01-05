/*
 * ROS node that shifts lidar PointCloud2 timestamps by a configurable offset.
 * Defaults: input /livox/lidar, output /livox/lidar_shifted, offset 32.43 seconds.
 */

#include <ros/ros.h>
#include <sensor_msgs/PointCloud2.h>

class LidarTimestampShift
{
public:
  LidarTimestampShift(ros::NodeHandle& nh, ros::NodeHandle& pnh)
  {
    pnh.param<std::string>("input_topic", input_topic_, "/livox/lidar");
    pnh.param<std::string>("output_topic", output_topic_, "/livox/lidar_shifted");
    // timestamp_offset: converts LiDAR device time to Unix/sim time
    pnh.param<double>("timestamp_offset", timestamp_offset_, 1739263380.384177);
    // capture_offset: compensates for sensor capture delay difference
    pnh.param<double>("capture_offset", capture_offset_, 32.43);
    pnh.param<bool>("verbose", verbose_, false);

    pub_ = nh.advertise<sensor_msgs::PointCloud2>(output_topic_, 10);
    sub_ = nh.subscribe(input_topic_, 10, &LidarTimestampShift::callback, this);

    ROS_INFO_STREAM("Shifting timestamps on " << input_topic_
                    << " | timestamp_offset=" << timestamp_offset_ << "s"
                    << " | capture_offset=" << capture_offset_ << "s"
                    << " | verbose=" << (verbose_ ? "true" : "false")
                    << " | publishing to " << output_topic_);
  }

private:
  void callback(const sensor_msgs::PointCloud2ConstPtr& msg)
  {
    sensor_msgs::PointCloud2 shifted = *msg;
    // Convert LiDAR device time to Unix/sim time using timestamp_offset,
    // then subtract capture_offset to sync environmental events with camera
    // new_stamp = header.stamp + timestamp_offset - capture_offset
    double new_time = msg->header.stamp.toSec() + timestamp_offset_ - capture_offset_;
    if (new_time < 0.0)
    {
      new_time = 0.0;
    }
    shifted.header.stamp = ros::Time(new_time);
    pub_.publish(shifted);
    
    if (verbose_)
    {
      ROS_INFO_STREAM_THROTTLE(2.0, "Shifted timestamp: " << msg->header.stamp.toSec() 
                               << " -> " << new_time);
    }
  }

  std::string input_topic_;
  std::string output_topic_;
  // timestamp_offset: converts LiDAR device-relative time to Unix/sim time (from rosbag analysis)
  double timestamp_offset_{1739263380.384177};
  // capture_offset: sensor capture delay difference to sync environmental events
  double capture_offset_{32.43};
  bool verbose_{false};
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
