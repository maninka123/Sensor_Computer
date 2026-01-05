/*
 * Merge a configurable number of consecutive PointCloud2 messages and publish the merged cloud.
 */

#include <ros/ros.h>
#include <sensor_msgs/PointCloud2.h>
#include <pcl_conversions/pcl_conversions.h>
#include <pcl/PCLPointCloud2.h>
#include <pcl/common/io.h>
#include <deque>

class PointCloudMerger
{
public:
  PointCloudMerger(ros::NodeHandle& nh, ros::NodeHandle& pnh)
  {
    pnh.param<std::string>("input_topic", input_topic_, "/Livox/lidar_shifted");
    pnh.param<std::string>("output_topic", output_topic_, "/Livox/lidar_merged");
    pnh.param<int>("queue_size", queue_size_, 10);
    pnh.param<int>("consecutive_count", consecutive_count_, 2);
    if (consecutive_count_ < 1)
    {
      consecutive_count_ = 1;
    }

    pub_ = nh.advertise<sensor_msgs::PointCloud2>(output_topic_, 1);
    sub_ = nh.subscribe(input_topic_, queue_size_, &PointCloudMerger::callback, this);

    ROS_INFO_STREAM("Merging " << consecutive_count_ << " consecutive clouds from "
                    << input_topic_ << " -> " << output_topic_);
  }

private:
  void callback(const sensor_msgs::PointCloud2ConstPtr& msg)
  {
    buffer_.push_back(*msg);
    while (static_cast<int>(buffer_.size()) > consecutive_count_)
    {
      buffer_.pop_front();
    }

    if (static_cast<int>(buffer_.size()) < consecutive_count_)
    {
      return;
    }

    sensor_msgs::PointCloud2 merged_ros;
    if (!mergeBuffer(merged_ros))
    {
      return;
    }

    pub_.publish(merged_ros);
  }

  bool mergeBuffer(sensor_msgs::PointCloud2& out)
  {
    if (buffer_.empty())
    {
      return false;
    }

    pcl::PCLPointCloud2 accumulated;
    bool first = true;
    for (const auto& cloud : buffer_)
    {
      pcl::PCLPointCloud2 pcl_cloud;
      pcl_conversions::toPCL(cloud, pcl_cloud);
      if (first)
      {
        accumulated = pcl_cloud;
        first = false;
      }
      else
      {
        pcl::concatenatePointCloud(accumulated, pcl_cloud, accumulated);
      }
    }

    pcl_conversions::fromPCL(accumulated, out);
    const auto& newest = buffer_.back().header;
    out.header.stamp = newest.stamp;
    out.header.frame_id = newest.frame_id;
    return true;
  }

  std::string input_topic_;
  std::string output_topic_;
  int queue_size_{10};
  int consecutive_count_{2};

  ros::Subscriber sub_;
  ros::Publisher pub_;
  std::deque<sensor_msgs::PointCloud2> buffer_;
};

int main(int argc, char** argv)
{
  ros::init(argc, argv, "pointcloud_merger");
  ros::NodeHandle nh;
  ros::NodeHandle pnh("~");

  PointCloudMerger node(nh, pnh);
  ros::spin();
  return 0;
}
