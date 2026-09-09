# Multiple sensor computers connected to one Surface PC

Each sensor computer runs a complete independent pipeline, ROS master, and
ROSBridge server. The Surface PC may connect later and keeps one fixed address:
`10.20.0.10/24`. It does not need one local IP per sensor computer.

## Why the addresses must differ

An IPv4 address identifies one network interface on the shared switch. Every
sensor computer, FLIR camera, and Livox unit therefore needs a unique address.
TCP ports may be reused because the complete socket identity includes the IP:
all sensor computers can listen on ROS port `11311` and ROSBridge port `9090`.

Use this repeatable allocation pattern:

| Unit | Sensor computer / ROS master | FLIR camera | Livox host alias | Livox LiDAR | ROSBridge |
| --- | --- | --- | --- | --- | --- |
| 1 | `10.20.0.21` | `10.20.0.22` | `192.168.1.50` | `192.168.1.125` | `ws://10.20.0.21:9090` |
| 2 | `10.20.0.31` | `10.20.0.32` | `192.168.1.51` | `192.168.1.126` | `ws://10.20.0.31:9090` |
| 3 | `10.20.0.41` | `10.20.0.42` | `192.168.1.52` | `192.168.1.127` | `ws://10.20.0.41:9090` |

The two addresses on each sensor-computer Ethernet interface are intentional:
`10.20.0.x/24` reaches its camera and the Surface PC, while
`192.168.1.x/24` reaches its Livox. Wi-Fi can remain the default internet route.
Do not duplicate the example addresses, FLIR serial, Livox address, or Livox
broadcast code on another unit.

## Install another sensor computer

These instructions target Ubuntu 20.04 with ROS Noetic already installed.

```bash
cd ~
git clone https://github.com/maninka123/Sensor_Computer.git catkin_ws_actual
cd ~/catkin_ws_actual

sudo rosdep init  # omit this line if rosdep was initialized previously
rosdep update
rosdep install --from-paths src --ignore-src -r -y
```

Install the Spinnaker SDK matching the computer architecture before building.
Never install an AMD64 package on an ARM64 computer.

For AMD64 Ubuntu 20.04:

```bash
cd ~/catkin_ws_actual/Camera_SDK/spinnaker-4.2.0.88-amd64
sudo ./install_spinnaker.sh
```

For ARM64 Ubuntu 20.04:

```bash
cd /tmp
tar -xzf ~/catkin_ws_actual/Camera_SDK/spinnaker-4.2.0.88-arm64-20.04-pkg.tar.gz
cd spinnaker-4.2.0.88-arm64
sudo ./install_spinnaker_arm.sh
```

Build the pinned Livox SDK and complete catkin workspace:

```bash
cd ~/catkin_ws_actual
./setup_workspace.sh
```

The enhancement model and requirements are under
`src/node_pc/scripts/SBC inference`. On a ROCK 5A:

```bash
cd ~/catkin_ws_actual/src/node_pc/scripts/'SBC inference'
./install_rock5a.sh
```

On another architecture, create an environment that can see system ROS Python
packages and install the same requirements:

```bash
cd ~/catkin_ws_actual/src/node_pc/scripts/'SBC inference'
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

## Configure each sensor computer

Commission one complete unit at a time before attaching all units to the shared
switch. This prevents an unconfigured camera or LiDAR from colliding with a
device already in service.

Find the Ethernet connection and interface names:

```bash
nmcli -f NAME,DEVICE,TYPE connection show
ip -brief link
```

Preview unit 2 without changing anything:

```bash
cd ~/catkin_ws_actual
./scripts/configure_sensor_unit.sh --dry-run \
  'ROS Sensor Unit 2' eth0 \
  10.20.0.31 10.20.0.32 \
  192.168.1.51 192.168.1.126 \
  24519999 3JEDLB30000X261
```

Replace the serial and 15-character Livox broadcast code, remove `--dry-run`,
and run the command locally. It creates a persistent NetworkManager profile and
updates `src/node_pc/config/network.env`. Activating the profile briefly
interrupts wired networking.

The resulting unit 2 settings include:

```bash
ROS_IP=10.20.0.31
ROS_MASTER_URI=http://10.20.0.31:11311
FLIR_CAMERA_IP=10.20.0.32
LIVOX_HOST_IP=192.168.1.51
LIVOX_DEVICE_IP=192.168.1.126
```

The master URI always points back to that sensor computer's own `ROS_IP`; it
must not point to the Surface PC or another sensor unit.

### Configure the FLIR address permanently

After the host profile is active and the camera is reachable, write its
persistent address using its actual serial:

```bash
/opt/spinnaker/bin/GigEConfig -s REPLACE_FLIR_SERIAL \
  -i 10.20.0.32 -n 255.255.255.0 -g 10.20.0.1
/opt/spinnaker/bin/GigEConfig -s REPLACE_FLIR_SERIAL
```

Both `GevDeviceIPAddress` and `GevPersistentIPAddress` must show
`10.20.0.32`. If the camera is link-local (`169.254.x.x`), follow the recovery
procedure in `LOCAL_SETUP.md`. Only connect the camera being commissioned while
performing an automatic Force-IP operation.

### Configure the Livox address and identity

Every Livox has a unique 15-character broadcast code; copy it from the unit's
label and set `LIVOX_BROADCAST_CODE` in `network.env`. Configure a unique static
address such as `192.168.1.126/24` using Livox Viewer or an SDK utility that
calls `SetStaticDynamicIP`. Restart the LiDAR after changing its address.

References: [official Livox ROS driver and broadcast-code documentation](https://github.com/Livox-SDK/livox_ros_driver)
and [official Livox static/dynamic IP API](https://github.com/Livox-SDK/Livox-SDK/blob/master/sdk_core/include/livox_sdk.h).

The launch passes the broadcast code as a whitelist, ensuring each sensor
computer connects only to its assigned LiDAR even though broadcasts from every
Livox are visible on the shared switch.

### Calibration is per physical rig

Do not blindly share `pipeline.yaml` when camera intrinsics, sensor mounting, or
capture timing differ. Store the correct camera intrinsics and LiDAR-to-camera
extrinsic matrix for each physical unit. Live clock-domain conversion is
automatic, but the physical `capture_offset` and calibration remain rig data.

## Start and verify a unit

```bash
cd ~/catkin_ws_actual
./check_hardware.sh
./run_hardware.sh
```

The command starts the local ROS master automatically. Verify:

```bash
export ROS_IP=10.20.0.31
export ROS_MASTER_URI=http://10.20.0.31:11311
source /opt/ros/noetic/setup.bash
rostopic hz /camera/image_raw
rostopic hz /livox/lidar
rostopic hz /merged_colored_cloud
```

The bundled Noetic FLIR driver includes automatic recovery from a transient
GigE frame timeout: it closes the active acquisition correctly, reconnects the
camera, reapplies its configuration, and resumes `/camera/image_raw`.

For unattended startup, install `deploy/node-pc.service` as described in the
main README. Each clone's `network.env` supplies that unit's addresses.

## Connect one Surface PC to several units

Configure the Surface Ethernet interface once:

```bash
sudo nmcli connection modify '<surface-wired-profile>' \
  ipv4.method manual ipv4.addresses 10.20.0.10/24 \
  ipv4.gateway '' ipv4.never-default yes
sudo nmcli connection up '<surface-wired-profile>'
```

The Surface PC can then ping every unit from its single address:

```bash
ping 10.20.0.21
ping 10.20.0.31
ping 10.20.0.41
```

### Recommended: one ROSBridge connection per unit

A Surface application can open all of these concurrently:

```text
ws://10.20.0.21:9090
ws://10.20.0.31:9090
ws://10.20.0.41:9090
```

The topic names may be identical because each WebSocket is a separate
connection. Tag data in the Surface application by unit/IP.

### Native ROS 1/TCPROS

One ROS 1 process has one `ROS_MASTER_URI`; it cannot register with three
independent masters at once. Use a separate process or terminal per unit:

```bash
# Terminal/process for unit 1
export ROS_IP=10.20.0.10
export ROS_MASTER_URI=http://10.20.0.21:11311
rostopic hz /merged_colored_cloud

# Terminal/process for unit 2
export ROS_IP=10.20.0.10
export ROS_MASTER_URI=http://10.20.0.31:11311
rostopic hz /merged_colored_cloud
```

Both processes advertise the same Surface address, which is correct. They use
different masters because their `ROS_MASTER_URI` values differ.

If one unified native ROS graph is required, deploy an explicit ROS 1
multi-master bridge or change the design to one central master and give every
unit a unique ROS namespace. A central master removes independent startup and
is not the repository default.

## Collision checklist

Before connecting all units simultaneously, confirm:

- every sensor-computer `ROS_IP` is unique;
- every FLIR persistent IP and serial is unique;
- every Livox static IP and broadcast code is unique;
- each sensor computer's `ROS_MASTER_URI` points to itself;
- the Surface remains `10.20.0.10/24` and runs no competing `roscore`;
- the switch has no port isolation/VLAN separation between these ports;
- the firewall permits `10.20.0.10` to reach device ports `11311`, `9090`, and
  the native ROS dynamic TCP range.
