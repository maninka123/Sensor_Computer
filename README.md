# Sensor Computer Software

ROS Noetic software for one FLIR Blackfly S camera and one Livox Avia LiDAR.
It produces a timestamp-synchronised, filtered, colourised point cloud for a
remote Surface/server PC.

## Install

Use [LOCAL_SETUP.md](LOCAL_SETUP.md) for a new Ubuntu 20.04 / ROS Noetic
computer. It covers Spinnaker, Livox, workspace build, and inference runtime.

## Run

Run the preflight check first. It checks the configured network, FLIR camera,
and Livox reachability without starting the pipeline.

```bash
cd ~/catkin_ws_actual
./check_hardware.sh
```

Start the complete live-sensor pipeline:

```bash
./run_hardware.sh
```

This is the default (`ROSBAG=false`): it starts FLIR, Livox LiDAR/IMU,
timestamp alignment, merging, filtering, colourisation, temperature monitoring,
the ROS master, and ROSBridge. Stop it with `Ctrl+C`.

For rosbag testing, start the same downstream pipeline without the physical
drivers, then play a bag that provides the raw camera/LiDAR topics:

```bash
ROSBAG=true ./run_pipeline.sh
rosbag play --clock <bag-file>
```

See [Testing without sensor hardware](docs/TESTING.md) for bag details.

## Output and remote connection

The final output is `sensor_msgs/PointCloud2` on:

```text
/merged_colored_cloud
```

The remote PC connects to this unit through ROSBridge:

```text
ws://10.20.0.21:9090
```

For native ROS 1 TCPROS, configure the remote PC (example address
`10.20.0.10/24`) as follows:

```bash
source /opt/ros/noetic/setup.bash
export ROS_IP=10.20.0.10
export ROS_MASTER_URI=http://10.20.0.21:11311
rostopic hz /merged_colored_cloud
```

## Persistent network values

These values persist after restart. The sensor-PC addresses are stored in its
NetworkManager Ethernet profile; the FLIR persistent address is stored in the
camera; and the Livox uses its configured address and broadcast code.

| Component | Value on this unit |
| --- | --- |
| Sensor PC `eth0` | `10.20.0.21/24` (ROS/server), `192.168.1.50/24` (Livox) |
| FLIR Blackfly S, serial `24510717` | `10.20.0.22/24` |
| Livox Avia, code `3JEDLB30015Y251` | `192.168.1.125/24` |
| ROS master | `http://10.20.0.21:11311` |
| ROSBridge | `ws://10.20.0.21:9090` |

`src/node_pc/config/network.env` records these values for the pipeline. Do not
edit it alone to change an IP: the computer or sensor device must be configured
to use the same address.

### Second sensor unit

If two units connect to the same server/switch, all addresses must be unique.

| Component | Unit 1 | Unit 2 |
| --- | --- | --- |
| Sensor PC / ROSBridge | `10.20.0.21:9090` | `10.20.0.31:9090` |
| FLIR | `10.20.0.22` | `10.20.0.32` |
| Livox host address | `192.168.1.50` | `192.168.1.51` |
| Livox LiDAR | `192.168.1.125` | `192.168.1.126` |

On the second PC, use its own FLIR serial and Livox broadcast code:

```bash
./scripts/configure_sensor_unit.sh "ROS Sensor Unit 2" eth0 \
  10.20.0.31 10.20.0.32 192.168.1.51 192.168.1.126 \
  NEW_FLIR_SERIAL NEW_LIVOX_BROADCAST_CODE
```

Then set the FLIR and Livox devices to their listed persistent addresses. The
server reads each final output separately through the two ROSBridge URLs.
For complete installation and multi-device details, see
[MULTI_DEVICE_DEPLOYMENT.md](docs/MULTI_DEVICE_DEPLOYMENT.md).

## Live controls and diagnostics

| Function | Control topic | Type |
| --- | --- | --- |
| Enable/disable voxel filtering | `/voxel_downsampling` | `std_msgs/Bool` |
| Set voxel leaf size in metres | `/voxel_leaf_size` | `std_msgs/Float64` |
| Request image enhancement | `/image_enhancement` | `std_msgs/Bool` |
| Read effective enhancement state | `/image_enhancement/status` | `std_msgs/Bool` |
| Read CPU temperature (every 30 s) | `/temperature` | `std_msgs/Float32` |

The default voxel size is `0.02 m`. Live control changes do not require a
restart, but `pipeline.yaml` supplies the default after the next restart.
Thermal protection disables enhancement at `85°C` and restores it at `70°C`;
the raw pipeline continues throughout.

Useful checks while the pipeline is running:

```bash
rosrun node_pc monitor_status.py
rostopic hz /camera/image_raw /livox/lidar /merged_colored_cloud
rostopic echo /temperature
```

## Main packages

- `src/node_pc` — processing, fusion, filtering, colourisation, and enhancement
- `src/flir_camera_driver` — FLIR Spinnaker driver
- `src/ws_livox` — Livox ROS driver

## License

Proprietary and confidential. Copyright (c) 2026 UNSW. See [LICENSE](LICENSE).
