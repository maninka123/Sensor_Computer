# Sensor Computer Software

> Prerequisites: install the [Spinnaker SDK](https://www.teledynevisionsolutions.com/en-au/products/spinnaker-sdk/?model=Spinnaker%20SDK&vertical=machine%20vision&segment=iis)
> for the FLIR camera and the [Livox SDK](https://github.com/Livox-SDK/Livox-SDK)
> for the LiDAR before building the workspace. See [LOCAL_SETUP.md](LOCAL_SETUP.md).

## System description

ROS Noetic software for one FLIR Blackfly S camera and one Livox Avia LiDAR.
It produces a timestamp-synchronised, filtered, colourised point cloud for a
remote server PC.

### Key features

- Livox LiDAR and IMU acquisition
- FLIR Blackfly S camera acquisition
- Low-light image enhancement with thermal protection
- Timestamp alignment, filtering, merging, and point-cloud colourisation
- Native ROS 1 TCPROS and ROSBridge output

### Repository structure

- `src/node_pc` — processing, fusion, filtering, colourisation, enhancement
- `src/flir_camera_driver` — FLIR Spinnaker driver
- `src/ws_livox` — Livox ROS driver

## Install

Use [LOCAL_SETUP.md](LOCAL_SETUP.md) for a new Ubuntu 20.04 / ROS Noetic
computer. It covers Spinnaker, Livox, workspace build, and inference runtime.

## Run

- Preflight: network, FLIR camera, and Livox reachability.
- It does not start the pipeline.

```bash
cd ~/catkin_ws_actual
./check_hardware.sh
```

Start the complete live-sensor pipeline:

```bash
./run_hardware.sh
```

- Default: `ROSBAG=false`.
- Starts FLIR, Livox LiDAR/IMU, processing, temperature monitoring, ROS master,
  and ROSBridge.
- Stop with `Ctrl+C`.

For rosbag testing:

- Sensor drivers stay off.
- The same downstream pipeline stays on.
- The bag supplies raw camera/LiDAR topics.

```bash
ROSBAG=true ./run_pipeline.sh
rosbag play --clock <bag-file>
```

See [Testing without sensor hardware](docs/TESTING.md) for bag details.

### Start automatically at boot

- Waits only for this PC's fixed `eth0` addresses.
- Does not wait for the remote server.
- Starts the live-sensor pipeline and an independent ROSBridge fallback.
- Automatically prefers a stable remote native TCPROS subscriber, stops the
  WebSocket bridge to save CPU, and restores it after sustained client loss.
- Requires live camera, LiDAR, and colourised-cloud messages before systemd
  declares startup successful.
- Restarts indefinitely after a failed health check or essential process exit.

Install and enable it for the next boot:

```bash
cd ~/catkin_ws_actual
./scripts/install_boot_service.sh
```

After reboot:

```bash
systemctl status node-pc.service node-pc-rosbridge.service \
  node-pc-transport-supervisor.service
./monitor_pipeline.sh
```

- The monitor uses the colourizer's actual matched-frame result for sync status.
- It avoids subscribing to large intermediate clouds, keeping diagnostic load low.

If startup fails or the output is missing, collect the service, network routes,
ROS nodes, topic rates, and recent logs in one command:

```bash
./scripts/pipeline_diagnostics.sh
```

After pulling service-file changes from GitHub, rerun
`./scripts/install_boot_service.sh` so the repository copy is installed into
`/etc/systemd/system`.

ROS logs are retained for 90 days. Cleanup runs safely at pipeline startup and,
after installing the boot service, once per day. Preview or run it manually:

```bash
./scripts/cleanup_ros_logs.sh --days 90
./scripts/cleanup_ros_logs.sh --days 90 --apply
```

Stop now but keep boot startup enabled:

```bash
sudo systemctl stop node-pc.service
```

Stop and disable boot startup:

```bash
sudo systemctl disable --now node-pc.service
```

Do not run `./run_hardware.sh` while the service is active.

## Output and remote connection

The final output is `sensor_msgs/PointCloud2` on:

```text
/merged_colored_cloud
```

ROSBridge is available initially at:

```text
ws://10.20.0.21:9090
```

- This is the current unit's direct/shared-link address and fallback transport.
- For separate private rigs that send output to one server, use the
  `10.30.0.x` server/output addresses in the second-unit table below.

When a remote native ROS node directly subscribes to `/merged_colored_cloud`
or `/camera/image_raw` for 15 seconds, the device automatically stops
ROSBridge and reports `TCPROS (DIRECT NATIVE)` in `./monitor_pipeline.sh`.
If all qualifying native clients disappear for 45 seconds, ROSBridge returns.
No user-side transport selector is required.

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

The FLIR transport defaults to 1400-byte packets, paced delivery, packet resend,
and 64 host buffers so it remains stable on a standard MTU-1500 shared switch.

### Second sensor unit

This repository supports two network layouts. The current unit uses one shared
sensor/server Ethernet network, where every address must be unique. If each rig
has its own private sensor LAN and only sends final output to the server, the
internal FLIR/Livox addresses may be reused; only each PC's server-facing ROS
address must be unique.

For the private-rig layout, use a server/output subnet different from the
internal `10.20.0.0/24` sensor subnet. Do not put the same `10.20.0.x/24`
subnet on both Ethernet interfaces of one PC.

| Network / component | Unit 1 | Unit 2 |
| --- | --- | --- |
| Server/output PC address and ROSBridge | `10.30.0.21:9090` | `10.30.0.31:9090` |
| Private sensor-PC addresses | `10.20.0.21`, `192.168.1.50` | same values may be reused |
| Private FLIR / Livox addresses | `10.20.0.22`, `192.168.1.125` | same values may be reused |

Set `ROS_IP` and `ROS_MASTER_URI` in each unit's `network.env` to its unique
server/output address. The FLIR serial and Livox broadcast code still identify
the physical devices and must match that rig. The server reads final outputs at
`ws://10.30.0.21:9090` and `ws://10.30.0.31:9090`.

Use `configure_sensor_unit.sh` only for the shared-switch layout, where every
sensor address is unique. The private-rig layout requires separate NetworkManager
profiles (or VLANs) for the sensor LAN and the server/output LAN.
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
cd ~/catkin_ws_actual
./monitor_pipeline.sh
```

The colour terminal dashboard shows:

- Overall pipeline, camera, LiDAR, and ROSBridge state
- Rates for all main sensor and processing topics
- CPU temperature and enhancement state
- LiDAR/camera timestamp synchronization
- Voxel state and leaf size
- Matched frames, output point count, and dropped batches

The boot service stays in the background; it does not open a desktop terminal.
Open a terminal and run the monitor only when needed. Stop only the monitor with
`Ctrl+C`; the pipeline continues running. The monitor uses queue size 1 and
avoids decoding large payloads where possible, so its CPU overhead is small.

## Raw vs enhanced image

![Raw vs Enhanced](Images/Raw_vs_Enchanced.jpeg)

## License

Proprietary and confidential. Copyright (c) 2026 UNSW. See [LICENSE](LICENSE).
