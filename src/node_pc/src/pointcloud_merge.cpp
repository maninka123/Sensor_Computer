/*
 * Accumulate PointCloud2 frames and attach exact per-point acquisition
 * provenance. The output remains sensor_msgs/PointCloud2 and preserves all
 * original fields while adding source_frame_index and the source timestamp.
 */

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <deque>
#include <limits>
#include <string>
#include <vector>

#include <ros/ros.h>
#include <sensor_msgs/PointCloud2.h>
#include <sensor_msgs/PointField.h>
#include <std_msgs/Bool.h>

class PointCloudMerger
{
public:
  PointCloudMerger(ros::NodeHandle& nh, ros::NodeHandle& pnh)
  {
    pnh.param<std::string>("input_topic", input_topic_, "/livox/lidar_shifted");
    pnh.param<std::string>("output_topic", output_topic_, "");
    if (output_topic_.empty())
    {
      pnh.param<std::string>("merged_topic", output_topic_, "/livox/lidar_merged");
    }
    pnh.param<std::string>("reset_topic", reset_topic_, "/image_enhancement");
    pnh.param<int>("queue_size", queue_size_, 10);
    pnh.param<int>("consecutive_count", consecutive_count_, 10);
    pnh.param<bool>("overlapping_merge", overlapping_merge_, false);
    pnh.param<bool>("image_enhancement", enhancement_mode_, false);
    pnh.param<bool>("verbose", verbose_, false);
    consecutive_count_ = std::max(1, consecutive_count_);

    pub_ = nh.advertise<sensor_msgs::PointCloud2>(output_topic_, 1);
    sub_ = nh.subscribe(input_topic_, queue_size_, &PointCloudMerger::cloudCallback, this);
    if (!reset_topic_.empty())
    {
      reset_sub_ = nh.subscribe(reset_topic_, 1, &PointCloudMerger::modeCallback, this);
    }

    ROS_INFO_STREAM("Frame-indexing merger: " << consecutive_count_ << " clouds "
                    << input_topic_ << " -> " << output_topic_
                    << " overlapping=" << (overlapping_merge_ ? "true" : "false")
                    << " reset_topic=" << reset_topic_);
  }

private:
  static bool hasReservedField(const sensor_msgs::PointCloud2& cloud)
  {
    for (const auto& field : cloud.fields)
    {
      if (field.name == "source_frame_index" ||
          field.name == "source_frame_stamp_sec" ||
          field.name == "source_frame_stamp_nsec" ||
          field.name == "image_enhancement_mode")
      {
        return true;
      }
    }
    return false;
  }

  static std::size_t pointCount(const sensor_msgs::PointCloud2& cloud)
  {
    return static_cast<std::size_t>(cloud.width) * cloud.height;
  }

  static bool compatibleLayout(const sensor_msgs::PointCloud2& lhs,
                               const sensor_msgs::PointCloud2& rhs)
  {
    if (lhs.point_step != rhs.point_step || lhs.is_bigendian != rhs.is_bigendian ||
        lhs.fields.size() != rhs.fields.size())
    {
      return false;
    }
    for (std::size_t i = 0; i < lhs.fields.size(); ++i)
    {
      const auto& a = lhs.fields[i];
      const auto& b = rhs.fields[i];
      if (a.name != b.name || a.offset != b.offset ||
          a.datatype != b.datatype || a.count != b.count)
      {
        return false;
      }
    }
    return true;
  }

  template <typename T>
  static void writeValue(std::uint8_t* destination, const T& value)
  {
    std::memcpy(destination, &value, sizeof(T));
  }

  void modeCallback(const std_msgs::BoolConstPtr& msg)
  {
    if (msg->data == enhancement_mode_)
    {
      return;
    }
    enhancement_mode_ = msg->data;
    const std::size_t discarded = buffer_.size();
    buffer_.clear();
    ROS_INFO_STREAM("Image mode changed to " << (enhancement_mode_ ? "enhanced" : "raw")
                    << "; reset LiDAR accumulation (discarded " << discarded << " frames)");
  }

  void cloudCallback(const sensor_msgs::PointCloud2ConstPtr& msg)
  {
    if (hasReservedField(*msg))
    {
      ROS_ERROR_STREAM_THROTTLE(2.0, "Input cloud already contains reserved source-frame fields; dropping it");
      return;
    }
    if (!buffer_.empty() && !compatibleLayout(*buffer_.front(), *msg))
    {
      ROS_ERROR_STREAM("PointCloud2 layout changed while accumulating; resetting the current batch");
      buffer_.clear();
    }

    // Retain ROS's immutable shared message instead of deep-copying every
    // incoming cloud. A ten-frame Livox batch can otherwise briefly consume
    // roughly twice its final payload size on memory-constrained SBCs.
    buffer_.push_back(msg);
    while (static_cast<int>(buffer_.size()) > consecutive_count_)
    {
      buffer_.pop_front();
    }
    if (static_cast<int>(buffer_.size()) < consecutive_count_)
    {
      return;
    }

    sensor_msgs::PointCloud2 output;
    if (buildIndexedCloud(output))
    {
      pub_.publish(output);
    }

    if (overlapping_merge_)
    {
      buffer_.pop_front();
    }
    else
    {
      buffer_.clear();
    }
  }

  bool buildIndexedCloud(sensor_msgs::PointCloud2& output) const
  {
    if (buffer_.empty())
    {
      return false;
    }

    const sensor_msgs::PointCloud2& first = *buffer_.front();
    const std::uint32_t original_step = first.point_step;
    const std::uint32_t index_offset = original_step;
    const std::uint32_t sec_offset = index_offset + sizeof(std::uint32_t);
    const std::uint32_t nsec_offset = sec_offset + sizeof(std::uint32_t);
    const std::uint32_t mode_offset = nsec_offset + sizeof(std::uint32_t);
    const std::uint32_t indexed_step = mode_offset + sizeof(std::uint32_t);

    std::size_t total_points = 0;
    for (const auto& cloud : buffer_)
    {
      total_points += pointCount(*cloud);
    }
    if (total_points > std::numeric_limits<std::uint32_t>::max())
    {
      ROS_ERROR_STREAM("Accumulated cloud is too large for PointCloud2 width");
      return false;
    }

    output.header = buffer_.back()->header;
    output.height = 1;
    output.width = static_cast<std::uint32_t>(total_points);
    output.fields = first.fields;
    output.fields.push_back(makeField("source_frame_index", index_offset));
    output.fields.push_back(makeField("source_frame_stamp_sec", sec_offset));
    output.fields.push_back(makeField("source_frame_stamp_nsec", nsec_offset));
    output.fields.push_back(makeField("image_enhancement_mode", mode_offset));
    output.is_bigendian = first.is_bigendian;
    output.point_step = indexed_step;
    output.row_step = indexed_step * output.width;
    output.is_dense = true;
    output.data.resize(output.row_step);

    std::size_t destination_index = 0;
    for (std::size_t frame_index = 0; frame_index < buffer_.size(); ++frame_index)
    {
      const sensor_msgs::PointCloud2& cloud = *buffer_[frame_index];
      output.is_dense = output.is_dense && cloud.is_dense;
      for (std::uint32_t row = 0; row < cloud.height; ++row)
      {
        for (std::uint32_t column = 0; column < cloud.width; ++column)
        {
          const std::size_t source_offset = static_cast<std::size_t>(row) * cloud.row_step +
                                            static_cast<std::size_t>(column) * cloud.point_step;
          std::uint8_t* destination = output.data.data() + destination_index * indexed_step;
          std::memcpy(destination, cloud.data.data() + source_offset, original_step);
          writeValue(destination + index_offset, static_cast<std::uint32_t>(frame_index));
          writeValue(destination + sec_offset, cloud.header.stamp.sec);
          writeValue(destination + nsec_offset, cloud.header.stamp.nsec);
          writeValue(destination + mode_offset, static_cast<std::uint32_t>(enhancement_mode_ ? 1 : 0));
          ++destination_index;
        }
      }
    }

    if (verbose_)
    {
      ROS_INFO_STREAM("Published " << total_points << " indexed points from "
                      << buffer_.size() << " source frames");
    }
    return true;
  }

  static sensor_msgs::PointField makeField(const std::string& name, std::uint32_t offset)
  {
    sensor_msgs::PointField field;
    field.name = name;
    field.offset = offset;
    field.datatype = sensor_msgs::PointField::UINT32;
    field.count = 1;
    return field;
  }

  std::string input_topic_;
  std::string output_topic_;
  std::string reset_topic_;
  int queue_size_{10};
  int consecutive_count_{10};
  bool overlapping_merge_{false};
  bool enhancement_mode_{false};
  bool verbose_{false};

  ros::Subscriber sub_;
  ros::Subscriber reset_sub_;
  ros::Publisher pub_;
  std::deque<sensor_msgs::PointCloud2ConstPtr> buffer_;
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
