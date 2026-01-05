/*
 * Subscribe to a merged PointCloud2 and camera images, find the closest image,
 * colorize the cloud using camera intrinsics and distortion, and publish.
 */

#include <ros/ros.h>
#include <sensor_msgs/PointCloud2.h>
#include <sensor_msgs/Image.h>
#include <sensor_msgs/image_encodings.h>
#include <pcl_conversions/pcl_conversions.h>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <cv_bridge/cv_bridge.h>
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <std_msgs/Bool.h>
#include <limits>
#include <vector>

class PointCloudColorizer
{
public:
  PointCloudColorizer(ros::NodeHandle& nh, ros::NodeHandle& pnh)
  {
    pnh.param<std::string>("input_topic", input_topic_, "/livox/lidar_merged");
    pnh.param<std::string>("output_topic", output_topic_, "/merged_colored_cloud");
    pnh.param<std::string>("image_topic", image_topic_, "/camera/image_raw");
    pnh.param<std::string>("enhanced_image_topic", enhanced_image_topic_, "/camera/image_enhanced");
    pnh.param<int>("image_enchantment", image_enchantment_, 0);
    pnh.param<std::string>("image_enchantment_topic", image_enchantment_topic_, std::string(""));
    pnh.param<double>("sync_tolerance", sync_tolerance_, 0.05);
    pnh.param<int>("queue_size", queue_size_, 10);
    pnh.param<bool>("verbose", verbose_, false);

    loadCameraParams(pnh);

    cloud_sub_ = nh.subscribe(input_topic_, queue_size_, &PointCloudColorizer::cloudCallback, this);

    const std::string& chosen_image_topic = (image_enchantment_ != 0) ? enhanced_image_topic_ : image_topic_;
    image_sub_ = nh.subscribe(chosen_image_topic, queue_size_, &PointCloudColorizer::imageCallback, this);
    pub_ = nh.advertise<sensor_msgs::PointCloud2>(output_topic_, 1);

    if (!image_enchantment_topic_.empty())
    {
      enchant_sub_ = nh.subscribe(image_enchantment_topic_, 1, &PointCloudColorizer::enchantCallback, this);
    }

    ROS_INFO_STREAM("Colorizer: cloud=" << input_topic_
                    << " image=" << chosen_image_topic
                    << " output=" << output_topic_
                    << " sync_tol=" << sync_tolerance_
                    << " enhancement_param=" << image_enchantment_);

    ROS_INFO_STREAM("Colorizing " << input_topic_ << " -> " << output_topic_
                    << " using images " << chosen_image_topic
                    << " (sync tolerance " << sync_tolerance_ << " s)"
                    << " enhancement=" << (image_enchantment_ != 0));
  }

private:
  void loadCameraParams(ros::NodeHandle& pnh)
  {
    std::vector<double> Kvec;
    if (pnh.getParam("camera_matrix", Kvec) && Kvec.size() == 9)
    {
      camera_matrix_ = cv::Mat(3, 3, CV_64F, Kvec.data()).clone();
      ROS_INFO_STREAM("Loaded camera_matrix from param.");
    }
    else
    {
      camera_matrix_ = (cv::Mat_<double>(3, 3) <<
                        224.514866, 0.0, 243.278429,
                        0.0, 224.340765, 181.763517,
                        0.0, 0.0, 1.0);
      ROS_WARN_STREAM("Using default camera_matrix (param not provided).");
    }

    std::vector<double> Dvec;
    if (pnh.getParam("dist_coeffs", Dvec) && !Dvec.empty())
    {
      dist_coeffs_ = cv::Mat(Dvec).clone();
      ROS_INFO_STREAM("Loaded dist_coeffs from param.");
    }
    else
    {
      dist_coeffs_ = (cv::Mat_<double>(1, 5) << -0.212691, 0.087036, 0.0, 0.0, 0.0);
      ROS_WARN_STREAM("Using default dist_coeffs (param not provided).");
    }

    ROS_INFO_STREAM("Camera intrinsics: fx=" << camera_matrix_.at<double>(0,0)
                    << " fy=" << camera_matrix_.at<double>(1,1)
                    << " cx=" << camera_matrix_.at<double>(0,2)
                    << " cy=" << camera_matrix_.at<double>(1,2)
                    << " k1=" << dist_coeffs_.at<double>(0,0)
                    << " k2=" << (dist_coeffs_.cols > 1 ? dist_coeffs_.at<double>(0,1) : 0.0));
  }

  void enchantCallback(const std_msgs::BoolConstPtr& msg)
  {
    image_enchantment_ = msg->data ? 1 : 0;
    ROS_INFO_STREAM("Image enhancement toggle received: " << (image_enchantment_ ? "ON" : "OFF"));
  }

  void cloudCallback(const sensor_msgs::PointCloud2ConstPtr& msg)
  {
    if (!last_image_)
    {
      return;
    }
    double dt = fabs((msg->header.stamp - last_image_->header.stamp).toSec());
    if (dt > sync_tolerance_)
    {
      if (verbose_)
      {
        ROS_WARN_STREAM_THROTTLE(2.0, "Skipping cloud: no image within sync tolerance (dt=" << dt << "s)");
      }
      return;
    }

    sensor_msgs::PointCloud2 colored;
    if (colorize(*msg, last_image_, colored))
    {
      pub_.publish(colored);
      if (verbose_)
      {
        ROS_INFO_STREAM_THROTTLE(2.0, "Published colorized cloud from cloud stamp "
                                  << msg->header.stamp << " and image stamp "
                                  << last_image_->header.stamp);
      }
    }
  }

  void imageCallback(const sensor_msgs::ImageConstPtr& msg)
  {
    last_image_ = msg;
  }

  bool colorize(const sensor_msgs::PointCloud2& cloud,
                const sensor_msgs::ImageConstPtr& image_msg,
                sensor_msgs::PointCloud2& out)
  {
    cv_bridge::CvImageConstPtr cv_ptr;
    try
    {
      cv_ptr = cv_bridge::toCvShare(image_msg, sensor_msgs::image_encodings::BGR8);
    }
    catch (cv_bridge::Exception& e)
    {
      ROS_WARN_STREAM_THROTTLE(2.0, "cv_bridge error: " << e.what());
      return false;
    }
    const cv::Mat& img = cv_ptr->image;

    pcl::PointCloud<pcl::PointXYZ>::Ptr xyz(new pcl::PointCloud<pcl::PointXYZ>());
    pcl::fromROSMsg(cloud, *xyz);
    if (xyz->empty())
    {
      return false;
    }

    pcl::PointCloud<pcl::PointXYZRGB> colored;
    colored.header = xyz->header;
    colored.reserve(xyz->points.size());
    size_t colored_points = 0;

    const double fx = camera_matrix_.at<double>(0, 0);
    const double fy = camera_matrix_.at<double>(1, 1);
    const double cx = camera_matrix_.at<double>(0, 2);
    const double cy = camera_matrix_.at<double>(1, 2);
    const double skew = camera_matrix_.at<double>(0, 1);

    const double k1 = dist_coeffs_.cols >= 1 ? dist_coeffs_.at<double>(0, 0) : 0.0;
    const double k2 = dist_coeffs_.cols >= 2 ? dist_coeffs_.at<double>(0, 1) : 0.0;
    const double p1 = dist_coeffs_.cols >= 3 ? dist_coeffs_.at<double>(0, 2) : 0.0;
    const double p2 = dist_coeffs_.cols >= 4 ? dist_coeffs_.at<double>(0, 3) : 0.0;
    const double k3 = dist_coeffs_.cols >= 5 ? dist_coeffs_.at<double>(0, 4) : 0.0;

    for (const auto& pt : xyz->points)
    {
      pcl::PointXYZRGB cpt;
      cpt.x = pt.x;
      cpt.y = pt.y;
      cpt.z = pt.z;

      if (std::isfinite(pt.x) && std::isfinite(pt.y) && std::isfinite(pt.z) && pt.z > 0.0f)
      {
        double xn = pt.x / pt.z;
        double yn = pt.y / pt.z;

        double r2 = xn * xn + yn * yn;
        double radial = 1.0 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2;
        double x_tangential = 2.0 * p1 * xn * yn + p2 * (r2 + 2.0 * xn * xn);
        double y_tangential = p1 * (r2 + 2.0 * yn * yn) + 2.0 * p2 * xn * yn;

        double x_distorted = xn * radial + x_tangential;
        double y_distorted = yn * radial + y_tangential;

        double u = fx * (x_distorted + skew * y_distorted) + cx;
        double v = fy * y_distorted + cy;

        int u_px = static_cast<int>(std::round(u));
        int v_px = static_cast<int>(std::round(v));

        if (u_px >= 0 && u_px < img.cols && v_px >= 0 && v_px < img.rows)
        {
          const cv::Vec3b& color = img.at<cv::Vec3b>(v_px, u_px);
          cpt.r = color[2];
          cpt.g = color[1];
          cpt.b = color[0];
          ++colored_points;
        }
        else
        {
          cpt.r = cpt.g = cpt.b = 0;
        }
      }
      else
      {
        cpt.r = cpt.g = cpt.b = 0;
      }

      colored.push_back(cpt);
    }

    pcl::toROSMsg(colored, out);
    out.header = cloud.header;

    const size_t total_pts = xyz->points.size();
    const double ratio = total_pts > 0 ? static_cast<double>(colored_points) / total_pts : 0.0;
    ROS_INFO_STREAM_THROTTLE(2.0, "Projection: colored " << colored_points << "/" << total_pts
                                 << " (" << ratio * 100.0 << "%) with current intrinsics.");

    return true;
  }

  std::string input_topic_;
  std::string output_topic_;
  std::string image_topic_;
  std::string enhanced_image_topic_;
  std::string image_enchantment_topic_;
  int image_enchantment_{0};
  double sync_tolerance_{0.05};
  int queue_size_{10};
  bool verbose_{false};

  cv::Mat camera_matrix_;
  cv::Mat dist_coeffs_;

  sensor_msgs::ImageConstPtr last_image_;

  ros::Subscriber cloud_sub_;
  ros::Subscriber image_sub_;
  ros::Subscriber enchant_sub_;
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
