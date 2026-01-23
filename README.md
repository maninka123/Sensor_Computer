# Sensor Computer Software

> Prerequisite SDKs: Install the [Spinnaker SDK](https://www.teledynevisionsolutions.com/en-au/products/spinnaker-sdk/?model=Spinnaker%20SDK&vertical=machine%20vision&segment=iis) (camera) and the [Livox SDK](https://github.com/Livox-SDK/Livox-SDK) (LiDAR) following their official install guides before building this workspace.

## Overview

This repository contains the software stack for a fixed monitoring device designed for use in underground mining environments. The system is developed to operate robustly in challenging subterranean conditions, providing critical monitoring capabilities.

This project is a collaboration between **The University of New South Wales (UNSW)** and **Azure Mining Technology Pty Ltd (AMT)**, a subsidiary of China Coal Technology and Engineering Group (CCTEG).

## System Description

The software runs on a dedicated sensor computer and integrates various hardware components to perform real-time data acquisition and processing.

### Key Features
- **LiDAR Integration**: Drivers and processing modules for Livox LiDAR sensors (`ws_livox`) for precise 3D mapping and monitoring.
- **Camera Systems**: Integration with FLIR cameras (`flir_camera_driver`) for high-quality visual monitoring.
- **Image Enhancement**: Custom image enhancement algorithms (`node_pc`) to improve visibility in low-light mine environments.
- **Data Processing**: Real-time point cloud processing and merging.
- **Web Visualization**: Support for web-based visualization of transforms and sensor data (`tf2_web_republisher`).

## Repository Structure

- `node_pc`: Main processing node containing scripts for image enhancement, timestamp shifting, and point cloud operations.
- `flir_camera_driver`: Drivers and configuration for FLIR Blackfly S cameras.
- `ws_livox`: ROS drivers for Livox LiDAR sensors.
- `camera_control_msgs`: Custom ROS messages and service definitions for camera control.
- `tf2_web_republisher`: Utilities for republishing TF2 data for web interfaces.

## Monitoring and Diagnostics

### Status Monitor
The status monitor provides a live terminal dashboard for node health and sensor sync:
- Per-topic rates (Hz) with stale detection.
- Timestamp offset between `/livox/lidar_shifted` and `/camera/image_raw`.
- Image enhancement status (topic + param).

Run it with ROS running and topics available:

```bash
rosrun node_pc monitor_status.py
```

Optional parameters:
- `~image_enchantment_topic` (default `/image_enhancement`)
- `/pointcloud_colorizer/image_enchantment` (used if set)
- `/monitor_status/sync_tolerance` (default `0.1` seconds)

### Timestamp Checker
The timestamp checker scans rosbag files and computes timestamp offsets between:
- rosbag time (sim time)
- LiDAR `header.stamp`
- Camera `header.stamp`

It summarizes offsets per bag and recommends `lidar_timestamp_shift` config values.

Run it from the repo root:

```bash
python3 src/node_pc/scripts/timestamp_checker.py
```

By default it looks for `.bag` files in `Rosbag files/` at the workspace root.

## License

This software is proprietary and confidential.

**Copyright (c) 2026 The University of New South Wales (UNSW). All rights reserved.**

See the [LICENSE](LICENSE) file for full details.
