/*
 * Frame-aware radial-outlier removal followed by voxel-grid sampling.
 * Source frames are filtered independently so a voxel can never mix points
 * acquired at different times or corrupt their provenance identifier.
 */

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include <ros/ros.h>
#include <sensor_msgs/PointCloud2.h>
#include <sensor_msgs/point_cloud2_iterator.h>
#include <std_msgs/Bool.h>
#include <std_msgs/Float64.h>
#include <pcl/filters/radius_outlier_removal.h>
#include <pcl/filters/voxel_grid.h>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>

class PointCloudVoxelFilter
{
public:
  PointCloudVoxelFilter(ros::NodeHandle& nh, ros::NodeHandle& pnh)
  {
    pnh.param<std::string>("input_topic", input_topic_, "/livox/lidar_merged");
    pnh.param<std::string>("output_topic", output_topic_, "/livox/lidar_filtered");
    pnh.param<std::string>("enabled_topic", enabled_topic_, "/voxel_downsampling");
    pnh.param<std::string>("leaf_size_topic", leaf_size_topic_, "/voxel_leaf_size");
    pnh.param<std::string>("enabled_status_topic", enabled_status_topic_, enabled_topic_ + "/status");
    pnh.param<std::string>("leaf_size_status_topic", leaf_size_status_topic_, leaf_size_topic_ + "/status");
    pnh.param<bool>("enabled", enabled_, true);
    pnh.param<double>("leaf_size", leaf_size_, kDefaultLeafSize);
    pnh.param<bool>("radial_filter_enabled", radial_filter_enabled_, true);
    pnh.param<bool>("voxel_before_radial", voxel_before_radial_, true);
    pnh.param<double>("radius_search", radius_search_, 0.05);
    pnh.param<int>("min_neighbors", min_neighbors_, 2);
    pnh.param<int>("queue_size", queue_size_, 2);
    pnh.param<bool>("verbose", verbose_, false);

    validateConfiguration(pnh);

    cloud_pub_ = nh.advertise<sensor_msgs::PointCloud2>(output_topic_, 1);
    enabled_status_pub_ = nh.advertise<std_msgs::Bool>(enabled_status_topic_, 1, true);
    leaf_size_status_pub_ = nh.advertise<std_msgs::Float64>(leaf_size_status_topic_, 1, true);
    cloud_sub_ = nh.subscribe(input_topic_, queue_size_, &PointCloudVoxelFilter::cloudCallback, this);
    enabled_sub_ = nh.subscribe(enabled_topic_, 1, &PointCloudVoxelFilter::enabledCallback, this);
    leaf_size_sub_ = nh.subscribe(leaf_size_topic_, 1, &PointCloudVoxelFilter::leafSizeCallback, this);

    publishStatus();
    ROS_INFO_STREAM("Frame-aware filters: " << input_topic_ << " -> " << output_topic_
                    << " radial=" << (radial_filter_enabled_ ? "on" : "off")
                    << " voxel_first=" << (voxel_before_radial_ ? "true" : "false")
                    << " radius=" << radius_search_ << " m min_neighbors=" << min_neighbors_
                    << " voxel=" << (enabled_ ? "on" : "off")
                    << " leaf_size=" << leaf_size_ << " m");
  }

private:
  struct FrameGroup
  {
    std::uint32_t index{0};
    std::uint32_t stamp_sec{0};
    std::uint32_t stamp_nsec{0};
    std::uint32_t enhancement_mode{0};
    pcl::PointCloud<pcl::PointXYZ>::Ptr points{new pcl::PointCloud<pcl::PointXYZ>};
  };

  static constexpr double kDefaultLeafSize = 0.02;

  static bool validPositive(double value)
  {
    return std::isfinite(value) && value > 0.0;
  }

  void validateConfiguration(ros::NodeHandle& pnh)
  {
    if (!validPositive(leaf_size_))
    {
      ROS_WARN_STREAM("Invalid configured voxel leaf_size=" << leaf_size_
                      << "; using default " << kDefaultLeafSize << " m");
      leaf_size_ = kDefaultLeafSize;
      pnh.setParam("leaf_size", leaf_size_);
    }
    if (!validPositive(radius_search_))
    {
      ROS_WARN_STREAM("Invalid radius_search=" << radius_search_ << "; using 0.05 m");
      radius_search_ = 0.05;
      pnh.setParam("radius_search", radius_search_);
    }
    if (min_neighbors_ < 1)
    {
      ROS_WARN_STREAM("Invalid min_neighbors=" << min_neighbors_ << "; using 1");
      min_neighbors_ = 1;
      pnh.setParam("min_neighbors", min_neighbors_);
    }
  }

  void enabledCallback(const std_msgs::BoolConstPtr& msg)
  {
    enabled_ = msg->data;
    private_nh_.setParam("enabled", enabled_);
    publishStatus();
    ROS_INFO_STREAM("Voxel downsampling toggle received: " << (enabled_ ? "ON" : "OFF"));
  }

  void leafSizeCallback(const std_msgs::Float64ConstPtr& msg)
  {
    if (!validPositive(msg->data))
    {
      ROS_WARN_STREAM("Ignoring invalid voxel leaf size " << msg->data
                      << " m; current value remains " << leaf_size_ << " m");
      publishStatus();
      return;
    }
    leaf_size_ = msg->data;
    private_nh_.setParam("leaf_size", leaf_size_);
    publishStatus();
    ROS_INFO_STREAM("Voxel leaf size updated to " << leaf_size_ << " m");
  }

  void publishStatus()
  {
    std_msgs::Bool enabled_msg;
    enabled_msg.data = enabled_;
    enabled_status_pub_.publish(enabled_msg);
    std_msgs::Float64 leaf_size_msg;
    leaf_size_msg.data = leaf_size_;
    leaf_size_status_pub_.publish(leaf_size_msg);
  }

  bool readGroups(const sensor_msgs::PointCloud2& msg, std::vector<FrameGroup>& groups) const
  {
    try
    {
      sensor_msgs::PointCloud2ConstIterator<float> x(msg, "x");
      sensor_msgs::PointCloud2ConstIterator<float> y(msg, "y");
      sensor_msgs::PointCloud2ConstIterator<float> z(msg, "z");
      sensor_msgs::PointCloud2ConstIterator<std::uint32_t> source(msg, "source_frame_index");
      sensor_msgs::PointCloud2ConstIterator<std::uint32_t> sec(msg, "source_frame_stamp_sec");
      sensor_msgs::PointCloud2ConstIterator<std::uint32_t> nsec(msg, "source_frame_stamp_nsec");
      sensor_msgs::PointCloud2ConstIterator<std::uint32_t> mode(msg, "image_enhancement_mode");

      std::unordered_map<std::uint32_t, std::size_t> positions;
      positions.reserve(16);
      groups.reserve(16);
      const std::size_t count = static_cast<std::size_t>(msg.width) * msg.height;
      for (std::size_t i = 0; i < count; ++i, ++x, ++y, ++z, ++source, ++sec, ++nsec, ++mode)
      {
        std::size_t group_position;
        if (!groups.empty() && groups.back().index == *source)
        {
          group_position = groups.size() - 1;
        }
        else
        {
          auto position = positions.find(*source);
          if (position == positions.end())
          {
            FrameGroup group;
            group.index = *source;
            group.stamp_sec = *sec;
            group.stamp_nsec = *nsec;
            group.enhancement_mode = *mode;
            groups.push_back(group);
            group_position = groups.size() - 1;
            positions.emplace(*source, group_position);
          }
          else
          {
            group_position = position->second;
          }
        }
        FrameGroup& group = groups[group_position];
        if (group.stamp_sec != *sec || group.stamp_nsec != *nsec ||
            group.enhancement_mode != *mode)
        {
          ROS_ERROR_STREAM("Source-frame index " << *source << " has inconsistent timestamps");
          return false;
        }
        if (std::isfinite(*x) && std::isfinite(*y) && std::isfinite(*z))
        {
          group.points->push_back(pcl::PointXYZ(*x, *y, *z));
        }
      }
    }
    catch (const std::runtime_error& error)
    {
      ROS_ERROR_STREAM_THROTTLE(2.0, "Indexed PointCloud2 is missing a required field: " << error.what());
      return false;
    }
    std::sort(groups.begin(), groups.end(), [](const FrameGroup& lhs, const FrameGroup& rhs) {
      return lhs.index < rhs.index;
    });
    return !groups.empty();
  }

  pcl::PointCloud<pcl::PointXYZ>::Ptr voxelFilter(
      const pcl::PointCloud<pcl::PointXYZ>::Ptr& input) const
  {
    pcl::PointCloud<pcl::PointXYZ>::Ptr output(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::VoxelGrid<pcl::PointXYZ> filter;
    const float leaf = static_cast<float>(leaf_size_);
    filter.setInputCloud(input);
    filter.setLeafSize(leaf, leaf, leaf);
    filter.filter(*output);
    return output;
  }

  pcl::PointCloud<pcl::PointXYZ>::Ptr radialFilter(
      const pcl::PointCloud<pcl::PointXYZ>::Ptr& input) const
  {
    pcl::PointCloud<pcl::PointXYZ>::Ptr output(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::RadiusOutlierRemoval<pcl::PointXYZ> filter;
    filter.setInputCloud(input);
    filter.setRadiusSearch(radius_search_);
    filter.setMinNeighborsInRadius(min_neighbors_);
    filter.filter(*output);
    return output;
  }

  pcl::PointCloud<pcl::PointXYZ>::Ptr filterGroup(const FrameGroup& group) const
  {
    pcl::PointCloud<pcl::PointXYZ>::Ptr current = group.points;
    // Voxel reduction first gives the much more expensive radius search a
    // smaller spatial index. The legacy order remains selectable for exact
    // comparison with older captures.
    if (enabled_ && voxel_before_radial_ && !current->empty())
    {
      current = voxelFilter(current);
    }
    if (radial_filter_enabled_ && !current->empty())
    {
      current = radialFilter(current);
    }
    if (enabled_ && !voxel_before_radial_ && !current->empty())
    {
      current = voxelFilter(current);
    }
    return current;
  }

  void cloudCallback(const sensor_msgs::PointCloud2ConstPtr& msg)
  {
    std::vector<FrameGroup> groups;
    if (!readGroups(*msg, groups))
    {
      return;
    }

    std::vector<pcl::PointCloud<pcl::PointXYZ>::Ptr> filtered;
    filtered.reserve(groups.size());
    std::size_t output_count = 0;
    for (const auto& group : groups)
    {
      filtered.push_back(filterGroup(group));
      output_count += filtered.back()->size();
    }

    sensor_msgs::PointCloud2 output;
    output.header = msg->header;
    sensor_msgs::PointCloud2Modifier modifier(output);
    modifier.setPointCloud2Fields(
        7,
        "x", 1, sensor_msgs::PointField::FLOAT32,
        "y", 1, sensor_msgs::PointField::FLOAT32,
        "z", 1, sensor_msgs::PointField::FLOAT32,
        "source_frame_index", 1, sensor_msgs::PointField::UINT32,
        "source_frame_stamp_sec", 1, sensor_msgs::PointField::UINT32,
        "source_frame_stamp_nsec", 1, sensor_msgs::PointField::UINT32,
        "image_enhancement_mode", 1, sensor_msgs::PointField::UINT32);
    modifier.resize(output_count);

    sensor_msgs::PointCloud2Iterator<float> x(output, "x");
    sensor_msgs::PointCloud2Iterator<float> y(output, "y");
    sensor_msgs::PointCloud2Iterator<float> z(output, "z");
    sensor_msgs::PointCloud2Iterator<std::uint32_t> source(output, "source_frame_index");
    sensor_msgs::PointCloud2Iterator<std::uint32_t> sec(output, "source_frame_stamp_sec");
    sensor_msgs::PointCloud2Iterator<std::uint32_t> nsec(output, "source_frame_stamp_nsec");
    sensor_msgs::PointCloud2Iterator<std::uint32_t> mode(output, "image_enhancement_mode");

    for (std::size_t group_index = 0; group_index < groups.size(); ++group_index)
    {
      const FrameGroup& group = groups[group_index];
      for (const auto& point : filtered[group_index]->points)
      {
        *x = point.x;
        *y = point.y;
        *z = point.z;
        *source = group.index;
        *sec = group.stamp_sec;
        *nsec = group.stamp_nsec;
        *mode = group.enhancement_mode;
        ++x; ++y; ++z; ++source; ++sec; ++nsec; ++mode;
      }
    }
    output.is_dense = true;
    cloud_pub_.publish(output);

    if (verbose_)
    {
      const std::size_t input_count = static_cast<std::size_t>(msg->width) * msg->height;
      ROS_INFO_STREAM("Frame-aware radial/voxel filtering " << input_count << " -> "
                      << output_count << " points across " << groups.size() << " source frames");
    }
  }

  ros::NodeHandle private_nh_{"~"};
  std::string input_topic_;
  std::string output_topic_;
  std::string enabled_topic_;
  std::string leaf_size_topic_;
  std::string enabled_status_topic_;
  std::string leaf_size_status_topic_;
  bool enabled_{true};
  double leaf_size_{kDefaultLeafSize};
  bool radial_filter_enabled_{true};
  bool voxel_before_radial_{true};
  double radius_search_{0.05};
  int min_neighbors_{2};
  int queue_size_{2};
  bool verbose_{false};

  ros::Subscriber cloud_sub_;
  ros::Subscriber enabled_sub_;
  ros::Subscriber leaf_size_sub_;
  ros::Publisher cloud_pub_;
  ros::Publisher enabled_status_pub_;
  ros::Publisher leaf_size_status_pub_;
};

int main(int argc, char** argv)
{
  ros::init(argc, argv, "pointcloud_voxel_filter");
  ros::NodeHandle nh;
  ros::NodeHandle pnh("~");
  PointCloudVoxelFilter node(nh, pnh);
  ros::spin();
  return 0;
}
