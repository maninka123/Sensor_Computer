/*
 * Frame-aware LiDAR/camera fusion. Every point carries the index and timestamp
 * of its original LiDAR frame, and every frame group is colourized with its own
 * temporally synchronized camera image.
 */

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <deque>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include <ros/ros.h>
#include <sensor_msgs/Image.h>
#include <sensor_msgs/PointCloud2.h>
#include <sensor_msgs/image_encodings.h>
#include <sensor_msgs/point_cloud2_iterator.h>
#include <std_msgs/Bool.h>
#include <cv_bridge/cv_bridge.h>
#include <opencv2/core.hpp>

class PointCloudColorizer
{
public:
  PointCloudColorizer(ros::NodeHandle& nh, ros::NodeHandle& pnh)
  {
    pnh.param<std::string>("input_topic", input_topic_, "/livox/lidar_filtered");
    pnh.param<std::string>("output_topic", output_topic_, "/merged_colored_cloud");
    pnh.param<std::string>("image_topic", image_topic_, "/camera/image_raw");
    pnh.param<std::string>("enhanced_image_topic", enhanced_image_topic_, "/camera/image_enhanced");
    pnh.param<int>("image_enchantment", image_enhancement_, 0);  // Backward-compatible parameter name.
    pnh.param<std::string>("image_enchantment_topic", image_enhancement_topic_, std::string(""));
    pnh.param<double>("sync_tolerance", sync_tolerance_, 0.05);
    pnh.param<int>("queue_size", queue_size_, 10);
    pnh.param<int>("image_history_size", image_history_size_, 100);
    pnh.param<int>("max_pending_clouds", max_pending_clouds_, 2);
    pnh.param<bool>("verbose", verbose_, false);
    image_history_size_ = std::max(10, image_history_size_);
    max_pending_clouds_ = std::max(1, max_pending_clouds_);

    loadCameraParams(pnh);
    cacheProjectionParams();

    cloud_sub_ = nh.subscribe(input_topic_, queue_size_, &PointCloudColorizer::cloudCallback, this);
    raw_image_sub_ = nh.subscribe(image_topic_, queue_size_, &PointCloudColorizer::rawImageCallback, this);
    enhanced_image_sub_ = nh.subscribe(enhanced_image_topic_, queue_size_, &PointCloudColorizer::enhancedImageCallback, this);
    pub_ = nh.advertise<sensor_msgs::PointCloud2>(output_topic_, 1);
    if (!image_enhancement_topic_.empty())
    {
      enhancement_sub_ = nh.subscribe(image_enhancement_topic_, 1, &PointCloudColorizer::enhancementCallback, this);
    }

    ROS_INFO_STREAM("Frame-aware colorizer: cloud=" << input_topic_
                    << " raw=" << image_topic_ << " enhanced=" << enhanced_image_topic_
                    << " output=" << output_topic_ << " sync_tolerance=" << sync_tolerance_
                    << " s mode=" << (enhancementEnabled() ? "enhanced" : "raw"));
  }

private:
  struct IndexedPoint
  {
    float x{0.0f};
    float y{0.0f};
    float z{0.0f};

    IndexedPoint(float x_value, float y_value, float z_value)
      : x(x_value), y(y_value), z(z_value)
    {
    }
  };

  struct SourceGroup
  {
    std::uint32_t index{0};
    std::uint32_t stamp_sec{0};
    std::uint32_t stamp_nsec{0};
    std::uint32_t enhancement_mode{0};
    std::vector<IndexedPoint> points;

    ros::Time stamp() const
    {
      return ros::Time(stamp_sec, stamp_nsec);
    }
  };

  bool enhancementEnabled() const
  {
    return image_enhancement_ != 0;
  }

  void loadCameraParams(ros::NodeHandle& pnh)
  {
    std::vector<double> values;
    if (pnh.getParam("camera_matrix", values) && values.size() == 9)
    {
      camera_matrix_ = cv::Mat(3, 3, CV_64F, values.data()).clone();
    }
    else
    {
      camera_matrix_ = (cv::Mat_<double>(3, 3) <<
          224.514866, 0.0, 243.278429,
          0.0, 224.340765, 181.763517,
          0.0, 0.0, 1.0);
      ROS_WARN_STREAM("Using default camera matrix");
    }

    values.clear();
    if (pnh.getParam("dist_coeffs", values) && !values.empty())
    {
      dist_coeffs_ = cv::Mat(values).clone().reshape(1, 1);
    }
    else
    {
      dist_coeffs_ = (cv::Mat_<double>(1, 5) << -0.212691, 0.087036, 0.0, 0.0, 0.0);
      ROS_WARN_STREAM("Using default distortion coefficients");
    }

    values.clear();
    if (pnh.getParam("extrinsic_matrix", values) && values.size() == 16)
    {
      extrinsic_matrix_ = cv::Mat(4, 4, CV_64F, values.data()).clone();
    }
    else
    {
      extrinsic_matrix_ = cv::Mat::eye(4, 4, CV_64F);
      ROS_WARN_STREAM("Using identity LiDAR-to-camera extrinsic matrix");
    }
  }

  void cacheProjectionParams()
  {
    r00_ = extrinsic_matrix_.at<double>(0, 0);
    r01_ = extrinsic_matrix_.at<double>(0, 1);
    r02_ = extrinsic_matrix_.at<double>(0, 2);
    tx_ = extrinsic_matrix_.at<double>(0, 3);
    r10_ = extrinsic_matrix_.at<double>(1, 0);
    r11_ = extrinsic_matrix_.at<double>(1, 1);
    r12_ = extrinsic_matrix_.at<double>(1, 2);
    ty_ = extrinsic_matrix_.at<double>(1, 3);
    r20_ = extrinsic_matrix_.at<double>(2, 0);
    r21_ = extrinsic_matrix_.at<double>(2, 1);
    r22_ = extrinsic_matrix_.at<double>(2, 2);
    tz_ = extrinsic_matrix_.at<double>(2, 3);
    fx_ = camera_matrix_.at<double>(0, 0);
    fy_ = camera_matrix_.at<double>(1, 1);
    cx_ = camera_matrix_.at<double>(0, 2);
    cy_ = camera_matrix_.at<double>(1, 2);
    skew_ = camera_matrix_.at<double>(0, 1);
    k1_ = dist_coeffs_.total() > 0 ? dist_coeffs_.at<double>(0, 0) : 0.0;
    k2_ = dist_coeffs_.total() > 1 ? dist_coeffs_.at<double>(0, 1) : 0.0;
    p1_ = dist_coeffs_.total() > 2 ? dist_coeffs_.at<double>(0, 2) : 0.0;
    p2_ = dist_coeffs_.total() > 3 ? dist_coeffs_.at<double>(0, 3) : 0.0;
    k3_ = dist_coeffs_.total() > 4 ? dist_coeffs_.at<double>(0, 4) : 0.0;
  }

  void enhancementCallback(const std_msgs::BoolConstPtr& msg)
  {
    const bool requested = msg->data;
    if (requested == enhancementEnabled())
    {
      return;
    }
    image_enhancement_ = requested ? 1 : 0;
    pending_clouds_.clear();
    raw_images_.clear();
    enhanced_images_.clear();
    ROS_INFO_STREAM("Fusion image mode changed to " << (requested ? "enhanced" : "raw")
                    << "; cleared pending fusion data to prevent mixed-mode output");
  }

  void rawImageCallback(const sensor_msgs::ImageConstPtr& msg)
  {
    if (enhancementEnabled())
    {
      return;
    }
    pushImage(raw_images_, msg);
    processPending();
  }

  void enhancedImageCallback(const sensor_msgs::ImageConstPtr& msg)
  {
    if (!enhancementEnabled())
    {
      return;
    }
    pushImage(enhanced_images_, msg);
    processPending();
  }

  void pushImage(std::deque<sensor_msgs::ImageConstPtr>& buffer,
                 const sensor_msgs::ImageConstPtr& msg)
  {
    buffer.push_back(msg);
    while (static_cast<int>(buffer.size()) > image_history_size_)
    {
      buffer.pop_front();
    }
  }

  void cloudCallback(const sensor_msgs::PointCloud2ConstPtr& msg)
  {
    pending_clouds_.push_back(msg);
    while (static_cast<int>(pending_clouds_.size()) > max_pending_clouds_)
    {
      ROS_WARN_STREAM("Dropping oldest fused cloud because synchronized images did not arrive in time");
      pending_clouds_.pop_front();
    }
    processPending();
  }

  void processPending()
  {
    while (!pending_clouds_.empty())
    {
      const sensor_msgs::PointCloud2ConstPtr cloud = pending_clouds_.front();
      std::vector<SourceGroup> groups;
      if (!readGroups(*cloud, groups))
      {
        pending_clouds_.pop_front();
        continue;
      }

      const bool batch_enhanced = groups.front().enhancement_mode != 0;
      const bool mixed_mode = std::any_of(groups.begin(), groups.end(),
          [batch_enhanced](const SourceGroup& group) {
            return (group.enhancement_mode != 0) != batch_enhanced;
          });
      if (mixed_mode)
      {
        ROS_ERROR_STREAM("Dropping a fusion cloud containing mixed raw/enhanced source modes");
        pending_clouds_.pop_front();
        continue;
      }
      if (batch_enhanced != enhancementEnabled())
      {
        ROS_WARN_STREAM("Dropping stale " << (batch_enhanced ? "enhanced" : "raw")
                        << " batch after image mode changed");
        pending_clouds_.pop_front();
        continue;
      }

      std::unordered_map<std::uint32_t, cv_bridge::CvImageConstPtr> images;
      if (!selectSynchronizedImages(groups, images))
      {
        return;  // Keep this cloud pending until another image arrives.
      }

      sensor_msgs::PointCloud2 output;
      if (colorize(*cloud, groups, images, output))
      {
        pub_.publish(output);
      }
      pending_clouds_.pop_front();
    }
  }

  bool readGroups(const sensor_msgs::PointCloud2& cloud, std::vector<SourceGroup>& groups) const
  {
    try
    {
      sensor_msgs::PointCloud2ConstIterator<float> x(cloud, "x");
      sensor_msgs::PointCloud2ConstIterator<float> y(cloud, "y");
      sensor_msgs::PointCloud2ConstIterator<float> z(cloud, "z");
      sensor_msgs::PointCloud2ConstIterator<std::uint32_t> source(cloud, "source_frame_index");
      sensor_msgs::PointCloud2ConstIterator<std::uint32_t> sec(cloud, "source_frame_stamp_sec");
      sensor_msgs::PointCloud2ConstIterator<std::uint32_t> nsec(cloud, "source_frame_stamp_nsec");
      sensor_msgs::PointCloud2ConstIterator<std::uint32_t> mode(cloud, "image_enhancement_mode");
      std::unordered_map<std::uint32_t, std::size_t> positions;
      positions.reserve(16);
      groups.reserve(16);
      const std::size_t count = static_cast<std::size_t>(cloud.width) * cloud.height;
      for (std::size_t i = 0; i < count; ++i, ++x, ++y, ++z, ++source, ++sec, ++nsec, ++mode)
      {
        std::size_t group_position;
        if (!groups.empty() && groups.back().index == *source)
        {
          // The merger emits each frame contiguously, so the normal path has
          // no hash lookup at all.
          group_position = groups.size() - 1;
        }
        else
        {
          auto position = positions.find(*source);
          if (position == positions.end())
          {
            SourceGroup group;
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
        SourceGroup& group = groups[group_position];
        if (group.stamp_sec != *sec || group.stamp_nsec != *nsec ||
            group.enhancement_mode != *mode)
        {
          ROS_ERROR_STREAM("Source-frame index " << *source << " has inconsistent timestamps");
          return false;
        }
        group.points.push_back(IndexedPoint{*x, *y, *z});
      }
    }
    catch (const std::runtime_error& error)
    {
      ROS_ERROR_STREAM_THROTTLE(2.0, "Filtered cloud lacks source-frame metadata: " << error.what());
      return false;
    }
    std::sort(groups.begin(), groups.end(), [](const SourceGroup& lhs, const SourceGroup& rhs) {
      return lhs.index < rhs.index;
    });
    return !groups.empty();
  }

  bool selectSynchronizedImages(
      const std::vector<SourceGroup>& groups,
      std::unordered_map<std::uint32_t, cv_bridge::CvImageConstPtr>& selected) const
  {
    const bool batch_enhanced = groups.front().enhancement_mode != 0;
    for (const auto& group : groups)
    {
      if ((group.enhancement_mode != 0) != batch_enhanced)
      {
        ROS_ERROR_STREAM("Rejecting a fusion cloud containing mixed raw/enhanced source modes");
        return false;
      }
    }
    if (batch_enhanced != enhancementEnabled())
    {
      return false;
    }
    const auto& buffer = batch_enhanced ? enhanced_images_ : raw_images_;
    if (buffer.empty())
    {
      return false;
    }

    std::set<const sensor_msgs::Image*> used_images;
    for (const auto& group : groups)
    {
      sensor_msgs::ImageConstPtr best;
      double best_delta = std::numeric_limits<double>::infinity();
      for (const auto& image : buffer)
      {
        if (used_images.count(image.get()) != 0)
        {
          continue;
        }
        const double delta = std::fabs((image->header.stamp - group.stamp()).toSec());
        if (delta < best_delta)
        {
          best_delta = delta;
          best = image;
        }
      }
      if (!best || best_delta > sync_tolerance_)
      {
        if (verbose_)
        {
          ROS_WARN_STREAM_THROTTLE(2.0, "Waiting for "
              << (batch_enhanced ? "enhanced" : "raw")
              << " image for source frame " << group.index
              << " (closest delta=" << best_delta << " s)");
        }
        return false;
      }
      try
      {
        selected[group.index] = cv_bridge::toCvShare(best, sensor_msgs::image_encodings::BGR8);
        used_images.insert(best.get());
      }
      catch (const cv_bridge::Exception& error)
      {
        ROS_WARN_STREAM("Cannot decode synchronized image for frame " << group.index
                        << ": " << error.what());
        return false;
      }
    }
    return true;
  }

  static float packRgb(std::uint8_t red, std::uint8_t green, std::uint8_t blue)
  {
    const std::uint32_t packed = (static_cast<std::uint32_t>(red) << 16) |
                                 (static_cast<std::uint32_t>(green) << 8) |
                                 static_cast<std::uint32_t>(blue);
    float value;
    std::memcpy(&value, &packed, sizeof(value));
    return value;
  }

  cv::Vec3b pointColor(const IndexedPoint& point, const cv::Mat& image) const
  {
    if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z))
    {
      return cv::Vec3b(0, 0, 0);
    }

    const double x_c = r00_ * point.x + r01_ * point.y + r02_ * point.z + tx_;
    const double y_c = r10_ * point.x + r11_ * point.y + r12_ * point.z + ty_;
    const double z_c = r20_ * point.x + r21_ * point.y + r22_ * point.z + tz_;
    if (z_c <= 0.0)
    {
      return cv::Vec3b(0, 0, 0);
    }

    const double xn = x_c / z_c;
    const double yn = y_c / z_c;
    const double r2 = xn * xn + yn * yn;
    const double r4 = r2 * r2;
    const double radial = 1.0 + k1_ * r2 + k2_ * r4 + k3_ * r4 * r2;
    const double xd = xn * radial + 2.0 * p1_ * xn * yn + p2_ * (r2 + 2.0 * xn * xn);
    const double yd = yn * radial + p1_ * (r2 + 2.0 * yn * yn) + 2.0 * p2_ * xn * yn;
    const int u = static_cast<int>(std::round(fx_ * (xd + skew_ * yd) + cx_));
    const int v = static_cast<int>(std::round(fy_ * yd + cy_));
    if (u < 0 || u >= image.cols || v < 0 || v >= image.rows)
    {
      return cv::Vec3b(0, 0, 0);
    }
    return image.at<cv::Vec3b>(v, u);
  }

  bool colorize(
      const sensor_msgs::PointCloud2& input,
      const std::vector<SourceGroup>& groups,
      const std::unordered_map<std::uint32_t, cv_bridge::CvImageConstPtr>& images,
      sensor_msgs::PointCloud2& output) const
  {
    std::size_t point_count = 0;
    for (const auto& group : groups)
    {
      point_count += group.points.size();
    }

    output.header = input.header;
    sensor_msgs::PointCloud2Modifier modifier(output);
    // Keep both acquisition clocks in the final cloud. This lets consumers
    // audit which LiDAR frame and synchronized camera image coloured every
    // point instead of relying only on the newest-frame header timestamp.
    modifier.setPointCloud2Fields(
        9,
        "x", 1, sensor_msgs::PointField::FLOAT32,
        "y", 1, sensor_msgs::PointField::FLOAT32,
        "z", 1, sensor_msgs::PointField::FLOAT32,
        "rgb", 1, sensor_msgs::PointField::FLOAT32,
        "source_frame_index", 1, sensor_msgs::PointField::UINT32,
        "source_frame_stamp_sec", 1, sensor_msgs::PointField::UINT32,
        "source_frame_stamp_nsec", 1, sensor_msgs::PointField::UINT32,
        "image_stamp_sec", 1, sensor_msgs::PointField::UINT32,
        "image_stamp_nsec", 1, sensor_msgs::PointField::UINT32);
    modifier.resize(point_count);

    sensor_msgs::PointCloud2Iterator<float> x(output, "x");
    sensor_msgs::PointCloud2Iterator<float> y(output, "y");
    sensor_msgs::PointCloud2Iterator<float> z(output, "z");
    sensor_msgs::PointCloud2Iterator<float> rgb(output, "rgb");
    sensor_msgs::PointCloud2Iterator<std::uint32_t> source(output, "source_frame_index");
    sensor_msgs::PointCloud2Iterator<std::uint32_t> source_sec(output, "source_frame_stamp_sec");
    sensor_msgs::PointCloud2Iterator<std::uint32_t> source_nsec(output, "source_frame_stamp_nsec");
    sensor_msgs::PointCloud2Iterator<std::uint32_t> image_sec(output, "image_stamp_sec");
    sensor_msgs::PointCloud2Iterator<std::uint32_t> image_nsec(output, "image_stamp_nsec");

    for (const auto& group : groups)
    {
      const auto image_position = images.find(group.index);
      if (image_position == images.end())
      {
        return false;
      }
      const cv::Mat& image = image_position->second->image;
      const ros::Time image_stamp = image_position->second->header.stamp;
      for (const auto& point : group.points)
      {
        const cv::Vec3b bgr = pointColor(point, image);
        *x = point.x;
        *y = point.y;
        *z = point.z;
        *rgb = packRgb(bgr[2], bgr[1], bgr[0]);
        *source = group.index;
        *source_sec = group.stamp_sec;
        *source_nsec = group.stamp_nsec;
        *image_sec = image_stamp.sec;
        *image_nsec = image_stamp.nsec;
        ++x; ++y; ++z; ++rgb; ++source;
        ++source_sec; ++source_nsec; ++image_sec; ++image_nsec;
      }
    }
    output.is_dense = input.is_dense;

    if (verbose_)
    {
      ROS_INFO_STREAM("Published " << point_count << " colored points from " << groups.size()
                      << " synchronized source frames using exclusively "
                      << (enhancementEnabled() ? "enhanced" : "raw") << " images");
    }
    return true;
  }

  std::string input_topic_;
  std::string output_topic_;
  std::string image_topic_;
  std::string enhanced_image_topic_;
  std::string image_enhancement_topic_;
  int image_enhancement_{0};
  double sync_tolerance_{0.05};
  int queue_size_{10};
  int image_history_size_{100};
  int max_pending_clouds_{2};
  bool verbose_{false};

  cv::Mat camera_matrix_;
  cv::Mat dist_coeffs_;
  cv::Mat extrinsic_matrix_;
  double r00_{0.0}, r01_{0.0}, r02_{0.0}, tx_{0.0};
  double r10_{0.0}, r11_{0.0}, r12_{0.0}, ty_{0.0};
  double r20_{0.0}, r21_{0.0}, r22_{0.0}, tz_{0.0};
  double fx_{0.0}, fy_{0.0}, cx_{0.0}, cy_{0.0}, skew_{0.0};
  double k1_{0.0}, k2_{0.0}, p1_{0.0}, p2_{0.0}, k3_{0.0};

  std::deque<sensor_msgs::ImageConstPtr> raw_images_;
  std::deque<sensor_msgs::ImageConstPtr> enhanced_images_;
  std::deque<sensor_msgs::PointCloud2ConstPtr> pending_clouds_;

  ros::Subscriber cloud_sub_;
  ros::Subscriber raw_image_sub_;
  ros::Subscriber enhanced_image_sub_;
  ros::Subscriber enhancement_sub_;
  ros::Publisher pub_;
};

int main(int argc, char** argv)
{
  ros::init(argc, argv, "pointcloud_colorizer");
  ros::NodeHandle nh;
  ros::NodeHandle pnh("~");
  PointCloudColorizer node(nh, pnh);
  ros::spin();
  return 0;
}
