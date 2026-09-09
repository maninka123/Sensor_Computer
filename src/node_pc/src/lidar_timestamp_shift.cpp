/*
 * ROS node that shifts lidar PointCloud2 timestamps by a configurable offset.
 * Defaults: input /livox/lidar, output /livox/lidar_shifted, capture offset 32.43 ms.
 */

#include <ros/ros.h>
#include <sensor_msgs/PointCloud2.h>

#include <cmath>

class LidarTimestampShift
{
public:
  LidarTimestampShift(ros::NodeHandle& nh, ros::NodeHandle& pnh)
  {
    pnh.param<std::string>("input_topic", input_topic_, "/livox/lidar");
    pnh.param<std::string>("output_topic", output_topic_, "/livox/lidar_shifted");
    // timestamp_offset: converts LiDAR device time to Unix/sim time
    pnh.param<double>("timestamp_offset", timestamp_offset_, 1739510486.944657);
    // Live Livox timestamps restart with the sensor. Estimate that changing
    // clock-domain conversion from message arrival and the known scan span.
    pnh.param<bool>("auto_timestamp_offset", auto_timestamp_offset_, false);
    pnh.param<double>("scan_duration", scan_duration_, 0.1);
    pnh.param<double>("auto_offset_alpha", auto_offset_alpha_, 0.01);
    // capture_offset: compensates for sensor capture delay difference
    pnh.param<double>("capture_offset", capture_offset_, 0.03243);
    pnh.param<bool>("verbose", verbose_, false);

    pub_ = nh.advertise<sensor_msgs::PointCloud2>(output_topic_, 10);
    sub_ = nh.subscribe(input_topic_, 10, &LidarTimestampShift::callback, this);

    ROS_INFO_STREAM("Shifting timestamps on " << input_topic_
                    << " | timestamp_offset=" << timestamp_offset_ << "s"
                    << " | auto_timestamp_offset=" << (auto_timestamp_offset_ ? "true" : "false")
                    << " | scan_duration=" << scan_duration_ << "s"
                    << " | capture_offset=" << capture_offset_ << "s"
                    << " | verbose=" << (verbose_ ? "true" : "false")
                    << " | publishing to " << output_topic_);
  }

private:
  void callback(const sensor_msgs::PointCloud2ConstPtr& msg)
  {
    sensor_msgs::PointCloud2 shifted = *msg;
    double effective_offset = timestamp_offset_;
    const double lidar_time = msg->header.stamp.toSec();
    if (auto_timestamp_offset_)
    {
      const double measured_offset = ros::Time::now().toSec() - lidar_time - scan_duration_;
      const bool lidar_clock_restarted = auto_offset_initialized_ && lidar_time + 0.5 < last_lidar_time_;
      const bool clock_domain_changed = auto_offset_initialized_ &&
        std::abs(measured_offset - auto_offset_) > 1.0;
      if (!auto_offset_initialized_ || lidar_clock_restarted || clock_domain_changed)
      {
        auto_offset_ = measured_offset;
        auto_offset_initialized_ = true;
        ROS_INFO_STREAM("Initialized live LiDAR clock conversion offset=" << auto_offset_ << "s");
      }
      else
      {
        auto_offset_ += auto_offset_alpha_ * (measured_offset - auto_offset_);
      }
      last_lidar_time_ = lidar_time;
      effective_offset = auto_offset_;
    }
    // Convert LiDAR device time to Unix/sim time using timestamp_offset,
    // then add capture_offset because the header refers to the first point and
    // the represented environmental event occurs later.
    // new_stamp = header.stamp + timestamp_offset + capture_offset
    double new_time = lidar_time + effective_offset + capture_offset_;
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
  double timestamp_offset_{1739510486.944657};
  bool auto_timestamp_offset_{false};
  double scan_duration_{0.1};
  double auto_offset_alpha_{0.01};
  bool auto_offset_initialized_{false};
  double auto_offset_{0.0};
  double last_lidar_time_{0.0};
  // capture_offset: sensor capture delay difference to sync environmental events
  double capture_offset_{0.03243};
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
