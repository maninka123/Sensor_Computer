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
- ROS master: `10.20.0.21:11311` on the sensor computer
- FLIR serial: `24510717`, persistent IP `10.20.0.22/24`, GigE, 35 FPS
- FLIR image: 4x4 binning (`484x366`), matching `pipeline.yaml` calibration
- Livox Avia broadcast code: `3JEDLB30015Y251`

The sensor computer must actually own `10.20.0.21` before hardware startup.
The launch-time network check prints an error when the configured address is
not assigned; the Surface PC does not need to be present at startup.

The camera itself has persistent IP enabled, so it returns to `10.20.0.22/24`
after power cycles and does not require connecting it to another PC first. To
recover this setting after a camera factory reset, temporarily put `eth0` in
the camera's link-local subnet and use FLIR's installed `GigEConfig` utility;
the desired camera-side values are recorded in `network.env`.

Verify the camera's current and stored addresses with:

```bash
/opt/spinnaker/bin/GigEConfig -s 24510717
```

Both `GevDeviceIPAddress` and `GevPersistentIPAddress` should be
`10.20.0.22`. To recover after a factory reset without using another PC:

```bash
nmcli device modify eth0 ipv4.addresses 169.254.1.1/16
/opt/spinnaker/bin/GigEConfig -s 24510717 -i 10.20.0.22 -n 255.255.255.0 -g 10.20.0.1
nmcli device modify eth0 ipv4.addresses '10.20.0.21/24,192.168.1.50/24'
```

The temporary `nmcli device modify` operation does not alter the saved
NetworkManager profile, but it briefly interrupts wired ROS traffic.

## Run

On the sensor computer, start the self-contained hardware stack. It starts its
own ROS master and does not require the Surface PC to be present:

```bash
cd ~/catkin_ws_actual
./check_hardware.sh
./run_hardware.sh
```

When the Surface PC connects later, configure its ROS terminals with
`ROS_IP=10.20.0.10` and `ROS_MASTER_URI=http://10.20.0.21:11311`.

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

Camera intrinsics, LiDAR-to-camera extrinsics, capture correction, and rosbag
clock offset live in `src/node_pc/config/pipeline.yaml`. Recalibrate the camera
and extrinsics if either sensor or its mounting moves.

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

For `ROSBAG=true`, the configured fixed timestamp offset matches the calibration
bags. For real hardware, `pipeline.launch` enables `auto_timestamp_offset`: the
node derives the changing Livox-device-to-ROS clock conversion after every
LiDAR start/restart, then independently adds the configured 32.43 ms capture
correction. No live clock offset needs to be copied into the YAML file.
