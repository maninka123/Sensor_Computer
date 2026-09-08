# ROCK 5A / ROS Noetic setup

This workspace is configured for Ubuntu 20.04 ARM64, ROS Noetic, one FLIR
GigE camera, and one Livox Avia. The Spinnaker ARM64 SDK is already installed
in `/opt/spinnaker`; do not install the AMD64 archive under `Camera_SDK`.

## Build

```bash
cd ~/catkin_ws_actual
./setup_workspace.sh
source devel/setup.bash
```

`setup_workspace.sh` builds the original Livox-SDK at the pinned compatible
revision into `.deps/`, then builds the complete catkin workspace. It does not
write into `/usr/local` and does not need sudo.

## Hardware and network values

Edit `src/node_pc/config/network.env` if the reserved addresses or hardware
change. Current values are:

- Sensor computer: `10.20.0.21`
- Surface ROS master: `10.20.0.10:11311`
- FLIR serial: `24510717`, GigE, 35 FPS
- Livox Avia broadcast code: `3JEDLB30015Y251`

The sensor computer must actually own `10.20.0.21` before hardware startup,
and it must be able to reach the surface master. The launch-time network check
prints an error when the configured address is not assigned.

## Run

On the surface computer, start its ROS master. On this sensor computer:

```bash
cd ~/catkin_ws_actual
./check_hardware.sh
./run_hardware.sh
```

To test against rosbags without hardware, use two terminals. The pipeline still
runs timestamp correction, merging, filtering, image enhancement, colourisation,
IMU filtering, TF, and the optional bridge; only the FLIR and Livox drivers are
omitted.

Terminal 1:

```bash
cd ~/catkin_ws_actual
ROSBAG=true ./run_pipeline.sh
```

Terminal 2:

```bash
cd ~/catkin_ws_actual
./run_rosbags.sh
```

Normal startup defaults to real sensors (`ROSBAG=false`), so it remains simply:

```bash
./run_pipeline.sh
```

Disable the optional WebSocket bridge with `ROSBRIDGE=false` before either
command. Extra roslaunch overrides can be appended, for example:

```bash
ROSBRIDGE=false ./run_hardware.sh camera_frame_rate:=20
```

## Automatic startup

After confirming the network and live sensor streams, install the prepared
service (these commands require the local sudo password):

```bash
cd ~/catkin_ws_actual
sudo install -m 0644 deploy/node-pc.service /etc/systemd/system/node-pc.service
sudo systemctl daemon-reload
sudo systemctl enable --now node-pc.service
systemctl status node-pc.service
journalctl -u node-pc.service -f
```

Useful checks after startup:

```bash
rostopic hz /camera/image_raw
rostopic hz /livox/lidar
rostopic hz /merged_colored_cloud
rosrun node_pc monitor_status.py
```

Camera intrinsics, LiDAR-to-camera extrinsics, and timestamp offsets live in
`src/node_pc/config/pipeline.yaml`. Recalibrate these if either sensor or its
mounting moves; they cannot be verified without connected hardware and a known
calibration target.

The colourizer also uses partial synchronized batches by default. It collects
ten LiDAR scans per approximately one-second window, performs one-to-one image
matching within 50 ms, and publishes the matched subset when at least three
source frames are available. Configure this under `pointcloud_colorizer` in
`pipeline.yaml`:

```yaml
allow_partial_batches: true
min_synchronized_frames: 3
sync_tolerance: 0.05
partial_batch_timeout: 0.30
```

Inspect the contribution to the latest output with:

```bash
rostopic echo /merged_colored_cloud/matched_frames
rostopic echo /merged_colored_cloud/input_frames
rostopic echo /merged_colored_cloud/point_count
rostopic echo /merged_colored_cloud/dropped_batches
```

## Enhancement and CPU temperature

Request enhancement through `/image_enhancement`. Read the effective state from
`/image_enhancement/status`; this is the value followed by the merger and
colourizer and is the correct value for a user-interface indicator.

```bash
rostopic pub -1 /image_enhancement std_msgs/Bool "data: true"
rostopic echo /image_enhancement/status
rostopic echo /temperature
```

`/temperature` is a latched `std_msgs/Float32` value in degrees Celsius. It is
published at startup and every 30 seconds. Enhancement is capped at 5 FPS for
continuous use. At 85 C it is automatically disabled and the pipeline continues
using raw images; at 70 C it is restored if the user's most recent request is
still ON. A temperature-read failure also safely selects raw mode. All values
are adjustable under `image_enhancer` in `src/node_pc/config/pipeline.yaml`.

The configured large timestamp offset matches the current calibration bags.
Recalculate it for live hardware after a LiDAR clock reset or restart.
