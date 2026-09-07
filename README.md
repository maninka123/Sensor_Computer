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
- **Data Processing**: Timestamp-aware per-frame filtering, image fusion, and point-cloud stacking.
- **Surface Connectivity**: Native ROS 1 TCPROS publishing, with optional ROSBridge and web transform support.

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

## Networking and transports

The colourised output remains `sensor_msgs/PointCloud2` on
`/merged_colored_cloud`. There are two independent ways to consume it:

| Consumer path | Device requirement | Network requirement |
| --- | --- | --- |
| Native TCPROS | The normal publisher; ROSBridge is not involved | Bidirectional reachability. TCP 11311 and the device's effective kernel ephemeral TCP range must be reachable. The subscriber must advertise a callback address the device can reach. |
| ROSBridge WebSocket | ROSBridge and `tf2_web_republisher`; enabled by default and disabled with `ROSBRIDGE=false` | One fixed WebSocket endpoint on TCP 9090. |

Set `ROSBRIDGE=false` when measuring TCPROS without the extra web subscriber.
Enabling it preserves the existing WebSocket and web-TF path.

The fixed endpoints are:

- ROS Master/TCPROS discovery: `http://10.20.0.10:11311`
- Direct device ROSBridge: `ws://10.20.0.21:9090`
- Docker-forwarded ROSBridge: `ws://10.20.0.10:9090`

### Address configuration

The single `network.env` file contains the device's literal static address and
the surface ROS Master address; neither is derived from the runtime host:

| File | Device address | Master |
| --- | --- | --- |
| `src/node_pc/config/network.env` | `10.20.0.21` | `http://10.20.0.10:11311` |

These private static addresses mirror the real deployment requirement: native
ROS peers must be able to dial the literal address a node advertised. They are
not merely a convenience for Docker. Use statically configured addresses or
DHCP reservations on real links.

| Variable | Meaning | Repository default | Set it in |
| --- | --- | --- | --- |
| `ROS_IP` | Address advertised by every node for XML-RPC and TCPROS callbacks | `10.20.0.21` | `network.env`; it **must be a literal IPv4 address**, never a name |
| `ROS_MASTER_URI` | Surface ROS Master | `http://10.20.0.10:11311` | `network.env` |
| `ROSBRIDGE_ADDRESS` | Local ROSBridge bind address | `0.0.0.0` | `network.env` |
| `ROSBRIDGE_PORT` | Fixed ROSBridge WebSocket port | `9090` | `network.env` |
| `NODE_PC_NETWORK_CONFIG` | Optional location of the canonical network file | `<workspace>/src/node_pc/config/network.env` | `deploy/node-pc.service` only when the workspace/config path differs |
| `ROSBAG` | Whether hardware drivers are omitted for bag playback | `true` interactively; `false` in the service | Shell for a one-off run, or `deploy/node-pc.service` for deployment |
| `ROSBRIDGE` | Whether ROSBridge and the web TF republisher start | `true` | Shell for a one-off run, or `deploy/node-pc.service` for deployment |

`run_pipeline.sh` loads the selected file before `roslaunch`. The systemd unit
uses `EnvironmentFile=` because systemd does not read `~/.bashrc`, and also gives
the wrapper the same file through `NODE_PC_NETWORK_CONFIG`. The launch
passes both values explicitly to every child and logs the resolved advertised
address. A loopback address, unassigned address, or name produces a prominent
startup error.

The current design runs one Master at `10.20.0.10` on the surface. The sensing
device cannot register or be discovered while the surface Master is unavailable. Already-running publishers
can continue producing locally, but messages cannot be discovered or delivered
through ROS until registration succeeds. ROS client libraries retry Master
registration; the Docker launcher additionally uses `roslaunch --wait`, so a
device container stays alive and starts its test publisher when the Master
returns. The systemd service restarts a failed launch after five seconds.

Use static addressing or a DHCP reservation for both the sensing unit and the
surface subscriber. If an address changes after reboot, advertised callbacks or
the Master URL become stale: registration can appear to work while the direct
TCPROS socket fails.

## Docker test environment

The Compose rig creates one bridge named `minenet` on `10.20.0.0/24`, with one
surface container and one sensing-device container.

Run the commands below from the repository root with Docker Desktop running and
its WSL integration enabled for this distribution.

| Container | Role | Static IP | Ports published to the Windows host |
| --- | --- | --- | --- |
| `surface` | ROS Master and ROSBridge TCP forwarder | `10.20.0.10` | 11311, 9090, TCP 45200-45300 |
| `device` | Synthetic sensing unit | `10.20.0.21` | Internal 9090 and 45200-45300 |

The surface container runs the only ROS process on that host (`roscore`). Its
small `socat` forwarder exposes the device-local ROSBridge listener without
moving ROSBridge off the device.

Bring up the complete test rig:

```bash
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml logs -f surface device
docker compose -f docker/docker-compose.yml ps
```

Stop the rig without deleting its images:

```bash
docker compose -f docker/docker-compose.yml down
```

The device automatically runs the synthetic point-cloud pipeline documented
below. To open an interactive shell or inspect a single device:

```bash
docker compose -f docker/docker-compose.yml exec device bash
docker compose -f docker/docker-compose.yml exec device rosnode info /rosbridge_websocket
docker compose -f docker/docker-compose.yml exec surface rostopic info /merged_colored_cloud
```

No device namespace is used. ROSBridge is enabled by `ROSBRIDGE=true` and is
available directly at `ws://10.20.0.21:9090` or through the Docker surface
forwarder at `ws://10.20.0.10:9090`. Its status is confirmed by the standard `get_loggers` and
`set_logger_level` services; this repository has no separate custom ROSBridge
enable/status service API. `docker compose up device` and `docker compose ps`
control and report the container service itself.

### Docker TCPROS port range

Both containers set `net.ipv4.ip_local_port_range` to `45200 45300`, and
Compose publishes the same bounded TCP range. This is strictly a **test-rig
measure** that makes Docker port publication finite and inspectable. A real
sensing unit must keep its normal kernel ephemeral range and allow the complete
effective range inbound from the surface subnet; do not copy the narrowed sysctl
to production hardware.

Native ROS embeds each publisher's `10.20.0.x` address in Master responses.
Docker port publication does not rewrite those XML-RPC payloads, so a native
Windows TCPROS client also needs a route to `10.20.0.0/24` through the Docker/WSL
network. The published Master and WebSocket ports work through normal host port
forwarding. Verify the Windows route before interpreting a missing TCPROS stream
as a ROS fault.

### Link shaping

The device container starts with 5 ms delay, 25 Mb/s rate, and 0.1% loss. Replace
those defaults or clear shaping entirely with:

```bash
docker/shape_link.sh
docker/shape_link.sh --delay 12ms --rate 10mbit --loss 0.5%
docker/shape_link.sh clear
```

`NET_ADMIN` is granted only so `tc netem` and firewall provisioning can be
tested. A Docker bridge does not reproduce real fibre latency, switch queuing,
or cross-traffic contention. Results characterise transport, addressing, retry,
and decoder behaviour—not production network performance.

When moving from Docker to real hardware, retain the launch files and topic
configuration. Only replace the literal addresses in `network.env` with the
reserved production addresses.

### systemd startup

Review the user, paths, addresses, and `ROSBAG` setting in
`deploy/node-pc.service`, then install it:

```bash
sudo install -m 0644 deploy/node-pc.service /etc/systemd/system/node-pc.service
sudo systemctl daemon-reload
sudo systemctl enable --now node-pc.service
systemctl status node-pc.service
```

The unit has both `Wants=network-online.target` and
`After=network-online.target`, so its static device address is available before
ROS starts. This waits for the local network configuration, not for the surface
machine.

### Firewall

Provision UFW with the actual surface subnet. The script reads
`/proc/sys/net/ipv4/ip_local_port_range` on the device at runtime; it never
hard-codes or guesses the dynamic range.

```bash
sudo scripts/provision_firewall.sh 10.20.0.0/24
# Add the fixed WebSocket port when ROSBridge is enabled:
sudo scripts/provision_firewall.sh 10.20.0.0/24 --rosbridge
```

The surface subnet is a required parameter. The script reads the effective range
from `/proc/sys/net/ipv4/ip_local_port_range`, so it automatically sees
45200-45300 inside the containers and the normal, wider range on hardware. ROS
node XML-RPC and TCPROS servers receive dynamic ports from that range, so a real
device's rule cannot safely be narrowed to one observed port. The script neither
disables nor enables UFW.

To confirm the narrowed range is used by container firewall provisioning:

```bash
docker compose -f docker/docker-compose.yml exec device \
  scripts/provision_firewall.sh 10.20.0.0/24 --rosbridge
```

### Publisher diagnostics

Run this on the sensing unit while the publisher and surface subscriber are
running:

```bash
scripts/publisher_diagnostics.sh
# Optional node and topic overrides:
scripts/publisher_diagnostics.sh /pointcloud_colorizer /merged_colored_cloud
```

It reports the node's advertised XML-RPC address, its process ID, established
connections and remote endpoints from `ss -tnp`, and the published type's
message-definition MD5. Use `sudo` if `ss` cannot show process ownership.

### Troubleshooting

| Symptom | Likely cause | Confirm with |
| --- | --- | --- |
| Subscriber registers but receives no messages | The device advertised loopback/a name, the dynamic inbound range is blocked, or the subscriber callback is unreachable from the device | `rosnode info /pointcloud_colorizer` and `sudo scripts/publisher_diagnostics.sh`; on the device also run `sudo ufw status numbered` |
| TCP connects and immediately closes, often reported as a header error | The Windows client's vendored message definition has a different MD5 | `rosmsg md5 sensor_msgs/PointCloud2` on the device and compare it with the client's compiled/vendored MD5; `scripts/publisher_diagnostics.sh` prints the device value |
| Pipeline works after SSH login but not after reboot | The service has stale/missing environment values, a wrong path/user, or started before usable networking | `systemctl show node-pc.service -p Environment` and `journalctl -u node-pc.service -b` |
| ROSBridge works but native TCPROS does not | TCP 9090 is open, but the bidirectional native ROS ports or advertised addresses are not | `sudo scripts/publisher_diagnostics.sh` and `sudo ufw status numbered` |

### Synthetic test publisher

For surface-side development without a live sensor, source the workspace and
start:

```bash
set -a
source src/node_pc/config/network.env
set +a
source devel/setup.bash
roslaunch node_pc synthetic_pointcloud.launch rate:=10 point_count:=10000
```

`rate`, `point_count`, `source_frame_count`, `topic`, and `frame_id` are
configurable launch arguments. The default topic is the real
`/merged_colored_cloud` output. Its synthetic payload matches the production
36-byte timestamp-aware layout: `x/y/z`, packed `rgb`, source-frame index,
source LiDAR timestamp, and synchronized image timestamp. **The points,
colours, and timestamps are synthetic** and are intended only for client
development and throughput/decode benchmarking.

## Timestamp-aware enhancement and fusion pipeline

The production path is:

```text
LiDAR -> timestamp correction -> 10-frame indexed stack
      -> voxel/radius filtering per source frame
Camera -> SBC-optimized Model V3 enhancement per image
      -> one-to-one timestamp matching for every LiDAR source frame
      -> colourization -> final timestamp-aware stacked PointCloud2
```

`image_enhancer.py` uses the frozen, BatchNorm-fused TorchScript graph in
`scripts/SBC inference/model_cpu.pt`. The ROS adapter converts BGR arrays
directly to tensors without PIL or torchvision, runs one bounded inference
worker, preserves the camera header, and publishes only genuine enhanced
frames. `/image_enhancement` changes raw/enhanced mode at runtime. A mode
change flushes incomplete LiDAR and image batches so one output can never mix
the two modes.

Each point in `/merged_colored_cloud` carries:

- `source_frame_index`
- `source_frame_stamp_sec` and `source_frame_stamp_nsec`
- `image_stamp_sec` and `image_stamp_nsec`

The cloud header is the newest source-frame timestamp. Every source-frame
group is filtered independently and must match a distinct camera image within
`sync_tolerance` before the final cloud is published.

On a ROCK 5A, prepare the runtime with:

```bash
cd "src/node_pc/scripts/SBC inference"
./install_rock5a.sh
export NODE_PC_INFERENCE_PYTHON="$PWD/.venv/bin/python"
```

Benchmark TorchScript and ONNX on the actual board before changing the default
backend or thread count; host/x86 timing is not representative of RK3588S
performance.

The native nodes are compiled with `-O3`. When compiling directly on the ROCK
5, `NODE_PC_NATIVE_OPTIMIZATION=ON` (the default) also enables CPU-specific
instructions. Disable that option for a portable binary or when cross-compiling:

```bash
catkin_make -DNODE_PC_NATIVE_OPTIMIZATION=OFF
```

For the default filter, voxel reduction runs before the more expensive radius
neighbour search to reduce its working set. Set
`pointcloud_voxel_filter/voxel_before_radial: false` only when reproducing the
old radius-then-voxel ordering is more important than SBC throughput.

### Raw vs Enhanced Example

![Raw vs Enhanced](Images/Raw_vs_Enchanced.jpeg)

## License

This software is proprietary and confidential.

**Copyright (c) 2026 The University of New South Wales (UNSW). All rights reserved.**

See the [LICENSE](LICENSE) file for full details.
