# Performance optimizations and measurements

This document records the optimizations applied to the Rock 5A sensor
computer, the measurements behind them, and the remaining bottlenecks. Values
are tied to the stated configuration and should be remeasured after changing
camera resolution, frame rate, point-cloud filters, clients, or cooling.

## Measurement context

The live measurements below were collected on 2026-09-24 with:

- FLIR Blackfly S BFS-PGE-27S5C at `484x366`, BayerRG8, and approximately
  `35 FPS`
- Livox Avia live acquisition
- `0.02 m` voxel filtering and point-cloud colourisation enabled
- neural image enhancement disabled by thermal protection
- a ROSBridge client actively receiving data
- the graphical desktop and VS Code running on the Rock 5A

Process CPU percentages are percentages of one CPU core. For example, `48%`
means approximately `0.48` of one core, not 48% of the entire eight-core CPU.

## Camera data reduction

The camera uses `4x4` binning:

| Configuration | Pixels/frame | Approximate Bayer8 payload at 35 FPS |
|---|---:|---:|
| Full sensor, `1936x1464` | 2,834,304 | 99.2 MB/s |
| Current, `484x366` | 177,144 | 6.2 MB/s |

This reduces pixel count and raw image payload by **16x** while preserving the
current `484x366` calibrated output dimensions. It also reduces debayering,
image-history, and colourisation work. The optical enclosure still causes a
measured sharpness loss of approximately 56%; increasing ordinary sharpening
cannot recover all of that information.

## Automatic ROS transport selection

The boot deployment separates transport from sensor processing:

- `node-pc.service` owns camera, LiDAR, synchronization, filtering, and
  colourisation.
- `node-pc-rosbridge.service` provides the initial WebSocket fallback.
- `node-pc-transport-supervisor.service` detects remote direct TCPROS
  subscriptions and controls the bridge independently.

ROSBridge starts at boot. A remote native ROS node subscribed directly to
`/merged_colored_cloud` from the point-cloud colorizer for 15 seconds causes ROSBridge
and the web TF republisher to stop. If every qualifying native client is absent
for 45 seconds, ROSBridge starts again. The sensor pipeline is not restarted
during either transition.

During the live sample, ROSBridge consumed approximately **47.8% of one CPU
core** while an external WebSocket client was actively subscribed. Removing it
after a TCPROS handoff therefore has a meaningful CPU and thermal benefit.
Actual savings depend on WebSocket subscriptions and message sizes; an idle
bridge costs much less.

`./monitor_pipeline.sh` reports one of these states:

- `ROSBRIDGE (WEBSOCKET FALLBACK)`
- `HANDOFF: TCPROS + ROSBRIDGE`
- `TCPROS (DIRECT NATIVE)`
- `NO CLIENT - FALLBACK PENDING`

## Live CPU profile

The main pipeline processes measured over a three-second live sample were:

| Process | CPU usage |
|---|---:|
| ROSBridge WebSocket server | 47.8% |
| Point-cloud voxel filter | 38.9% |
| FLIR camera nodelet manager | 34.9% |
| Point-cloud colourizer | 13.6% |
| Livox driver | 12.0% |
| Point-cloud merger | 5.7% |
| Disabled image-enhancer controller | 4.7% |
| Timestamp shift | 3.3% |

The machine averaged approximately **51% total CPU busy across eight cores**
during a nearby sample. The graphical desktop, VS Code, and display server were
also significant consumers, so production deployment should be headless when
possible.

The next major compute target is the radius/voxel filtering path. ROSBridge
handoff removes avoidable transport work; it does not eliminate filtering,
camera, or point-cloud processing costs.

## Network and memory traffic

The live interface sample showed:

| Interface | Receive | Transmit | Interpretation |
|---|---:|---:|---|
| `eth0` | 14.3 MB/s | 8.0 MB/s | Camera, LiDAR, and remote output traffic |
| loopback | 39.6 MB/s | 39.6 MB/s | ROS messages exchanged between local processes |
| `wlan0` | 0.14 KB/s | 0.11 KB/s | Nearly idle during the sample |
| second Wi-Fi interface | 0 KB/s | 0.04 KB/s | Nearly idle duplicate connection |

The complete pipeline service held approximately **849 MiB RAM** and 186
tasks during the same inspection. Large ROS messages explain the high loopback
traffic even though they never leave the device.

The Realtek RTL8852BE Wi-Fi module had power saving disabled and exposed two
interfaces connected to the same access point. Those settings can waste some
power, especially with the measured weak `-86 dBm` signal, but Wi-Fi traffic
was effectively zero. The reported 82-85 C sensors were all SoC, CPU, GPU, or
NPU sensors. The evidence points to pipeline and desktop compute—not Wi-Fi—as
the main thermal source.

## Thermal controls

The image enhancer publishes the SoC temperature every 30 seconds. Enhancement
is automatically disabled at `85 C` and can resume at `70 C`. This protects the
raw sensor and point-cloud pipeline but does not prevent the Linux thermal
governor from throttling other workloads.

At 84-85 C, the kernel was already applying CPU and device-frequency cooling
states. Recommended operating measures are:

1. Prefer native TCPROS so the supervisor can stop ROSBridge.
2. Run the deployed sensor computer without the graphical desktop and VS Code.
3. Profile and reduce the radius/voxel filtering workload.
4. Improve heatsink contact, enclosure airflow, and active cooling.
5. Enable Wi-Fi power saving and remove the duplicate Wi-Fi connection only
   after confirming management access remains available.

## Enclosure image-correction candidate

The enclosure colour/flare correction remains an evaluated candidate and is
**not part of the pipeline**. At `484x366`, the measured processing cost was:

| Implementation | Latency/frame | CPU demand at 35 FPS |
|---|---:|---:|
| Optimized offline OpenCV path | approximately 6.0 ms | approximately 0.21 core |
| Temporary live Python viewer | approximately 7.8 ms | approximately 0.27 core |

The best test combined a regularized colour matrix, a low-frequency spatial
flare template, and mild sharpening. In the same-scene validation it reduced
pixels differing by more than 20 intensity levels from 58.2% to 16.8% and
improved SSIM from 0.878 to 0.897. These values are optimistic because the
training and evaluation frames showed the same static scene. The method reduced
warm flare but did not remove the sharp LiDAR reflection or saturated lamps.

If adopted, correction should occur **after timestamp synchronization and
matched-image selection**, immediately before point colours are sampled. That
keeps the original capture timestamp and `32.43 ms` capture offset unchanged,
and avoids processing all 35 camera frames. Processing ten selected images per
second would use roughly 6-8% of one CPU core rather than 21-27% at 35 FPS.

A ColorChecker, uniform-grey field, and independent lighting/scene validation
are required before enabling this correction in production.

## Other safeguards

- Camera GigE uses conservative MTU-1500 packet sizing and stream buffering.
- The pipeline wrapper restarts roslaunch after both failures and clean child
  exits, preventing a silent stopped service.
- The status monitor avoids decoding large intermediate clouds and uses small
  status topics for output health.
- ROS logs older than 90 days are removed at startup and by a daily timer, so
  accumulated logs do not eventually consume the device filesystem.

## Reproducing checks

Use these commands after deployment:

```bash
./monitor_pipeline.sh
./scripts/pipeline_diagnostics.sh
systemctl status node-pc.service node-pc-rosbridge.service \
  node-pc-transport-supervisor.service
pidstat 1 5
sar -n DEV 1 5
```

Always record the camera mode, active clients, pipeline configuration,
temperature, and whether the graphical desktop is running when comparing new
measurements with this document.
