# Multiple independent sensor units connected to one server

Each sensor computer runs its own pipeline, ROS master, and ROSBridge server.
The server receives only each unit's final output. It keeps one server address;
each unit needs a unique address only on that server/output network.

## Recommended layout: private sensor LAN per rig

This is the intended layout when the FLIR and Livox are not shared with the
server or another rig. Each rig has a private sensor-facing Ethernet interface
(or isolated VLAN), plus a separate server/output interface. The private FLIR
and Livox IPs may be identical on every rig because those networks never meet.

Use a server/output subnet that differs from the private camera subnet. For
example, the server can be `10.30.0.10/24`:

| Network / component | Unit 1 | Unit 2 | Unit 3 |
| --- | --- | --- | --- |
| Server-facing PC / ROS master | `10.30.0.21` | `10.30.0.31` | `10.30.0.41` |
| ROSBridge endpoint | `ws://10.30.0.21:9090` | `ws://10.30.0.31:9090` | `ws://10.30.0.41:9090` |
| Private sensor-PC camera address | `10.20.0.21` | `10.20.0.21` | `10.20.0.21` |
| Private FLIR camera | `10.20.0.22` | `10.20.0.22` | `10.20.0.22` |
| Private sensor-PC Livox address | `192.168.1.50` | `192.168.1.50` | `192.168.1.50` |
| Private Livox LiDAR | `192.168.1.125` | `192.168.1.125` | `192.168.1.125` |

The FLIR serial and Livox broadcast code are hardware identifiers. They are
different for each physical device, even though the private IP addresses may
be reused. Configure every unit's `ROS_IP` and `ROS_MASTER_URI` with its
unique **server-facing** address.

Do not put `10.20.0.x/24` on both the private sensor interface and the
server-facing interface of the same PC. Use separate interfaces/VLANs and
different subnets, as in the table above.

## Alternative: one shared switch

If all PCs, cameras, LiDARs, and the server share one Ethernet switch/VLAN,
every address must be unique. Use this allocation and
`configure_sensor_unit.sh`:

| Component | Unit 1 | Unit 2 |
| --- | --- | --- |
| Sensor PC / ROSBridge | `10.20.0.21:9090` | `10.20.0.31:9090` |
| FLIR | `10.20.0.22` | `10.20.0.32` |
| Livox host address | `192.168.1.50` | `192.168.1.51` |
| Livox LiDAR | `192.168.1.125` | `192.168.1.126` |

TCP port `9090` may still be reused because each sensor PC has a different IP.

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

For the recommended private-rig layout:

- Create one NetworkManager profile for the private sensor interface.
- Assign its camera/Livox-side addresses: `10.20.0.21/24` and
  `192.168.1.50/24`.
- Create another profile for the server/output interface.
- Give that interface the unit's unique server address, such as
  `10.30.0.31/24` for unit 2.
- Set `ROS_IP` and `ROS_MASTER_URI` in `network.env` to the unique
  server/output address, not to the private sensor address.

Find interface names first:

```bash
nmcli -f NAME,DEVICE,TYPE connection show
ip -brief link
```

For unit 2, the important `network.env` values are:

```bash
ROS_IP=10.30.0.31
ROS_MASTER_URI=http://10.30.0.31:11311
FLIR_CAMERA_IP=10.20.0.22
LIVOX_HOST_IP=192.168.1.50
LIVOX_DEVICE_IP=192.168.1.125
```

The master URI always points back to that sensor computer's own server-facing
`ROS_IP`; it must not point to the server or another sensor unit.

`configure_sensor_unit.sh` is for the alternative shared-switch layout. It
places both host addresses on one interface, so do not use it for separate
sensor and server interfaces.

### Configure the FLIR address permanently

After the host profile is active and the camera is reachable, write its
persistent address using its actual serial:

```bash
/opt/spinnaker/bin/GigEConfig -s REPLACE_FLIR_SERIAL \
  -i 10.20.0.22 -n 255.255.255.0 -g 10.20.0.1
/opt/spinnaker/bin/GigEConfig -s REPLACE_FLIR_SERIAL
```

Both `GevDeviceIPAddress` and `GevPersistentIPAddress` must show
`10.20.0.22`. If the camera is link-local (`169.254.x.x`), follow the recovery
procedure in `LOCAL_SETUP.md`. Only connect the camera being commissioned while
performing an automatic Force-IP operation.

### Configure the Livox address and identity

Every Livox has a unique 15-character broadcast code; copy it from the unit's
label and set `LIVOX_BROADCAST_CODE` in `network.env`. Configure
`192.168.1.125/24` on each isolated private sensor network, or use a unique
address when LiDARs share a switch/VLAN. Restart the LiDAR after changing its
address.

References: [official Livox ROS driver and broadcast-code documentation](https://github.com/Livox-SDK/livox_ros_driver)
and [official Livox static/dynamic IP API](https://github.com/Livox-SDK/Livox-SDK/blob/master/sdk_core/include/livox_sdk.h).

The launch uses the broadcast code as a whitelist, ensuring each sensor
computer connects only to its assigned LiDAR.

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
export ROS_IP=10.30.0.31
export ROS_MASTER_URI=http://10.30.0.31:11311
source /opt/ros/noetic/setup.bash
rostopic hz /camera/image_raw
rostopic hz /livox/lidar
rostopic hz /merged_colored_cloud
```

The bundled Noetic FLIR driver includes automatic recovery from a transient
GigE frame timeout: it closes the active acquisition correctly, reconnects the
camera, reapplies its configuration, and resumes `/camera/image_raw`.

For unattended startup, review and install `deploy/node-pc.service`; each
clone's `network.env` supplies that unit's addresses.

## Connect one server to several units

Configure the server Ethernet interface once:

```bash
sudo nmcli connection modify '<surface-wired-profile>' \
  ipv4.method manual ipv4.addresses 10.30.0.10/24 \
  ipv4.gateway '' ipv4.never-default yes
sudo nmcli connection up '<surface-wired-profile>'
```

The server can then ping every unit from its single address:

```bash
ping 10.30.0.21
ping 10.30.0.31
ping 10.30.0.41
```

### Recommended: one ROSBridge connection per unit

A server application can open all of these concurrently:

```text
ws://10.30.0.21:9090
ws://10.30.0.31:9090
ws://10.30.0.41:9090
```

The topic names may be identical because each WebSocket is a separate
connection. Tag data in the server application by unit/IP.

### Native ROS 1/TCPROS

One ROS 1 process has one `ROS_MASTER_URI`; it cannot register with three
independent masters at once. Use a separate process or terminal per unit:

```bash
# Terminal/process for unit 1
export ROS_IP=10.30.0.10
export ROS_MASTER_URI=http://10.30.0.21:11311
rostopic hz /merged_colored_cloud

# Terminal/process for unit 2
export ROS_IP=10.30.0.10
export ROS_MASTER_URI=http://10.30.0.31:11311
rostopic hz /merged_colored_cloud
```

Both processes advertise the same server address, which is correct. They use
different masters because their `ROS_MASTER_URI` values differ.

If one unified native ROS graph is required, deploy an explicit ROS 1
multi-master bridge or change the design to one central master and give every
unit a unique ROS namespace. A central master removes independent startup and
is not the repository default.

## Collision checklist

Before connecting all units simultaneously, confirm:

- every server-facing sensor-computer `ROS_IP` is unique;
- each sensor computer's `ROS_MASTER_URI` points to its own server-facing IP;
- the server remains `10.30.0.10/24` and runs no competing `roscore`;
- every rig's sensor LAN is physically separate or VLAN-isolated from other
  rigs and the server network;
- FLIR serials and Livox broadcast codes match the physical rig;
- duplicate FLIR/Livox IPs are used only on isolated sensor LANs;
- the firewall permits `10.30.0.10` to reach device ports `11311`, `9090`, and
  the native ROS dynamic TCP range.
