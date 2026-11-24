# Device 5 camera brightness

Device 5's live comparison on **19 Nov 2026** selected **gamma 0.65** over 0.75.
Only the existing gamma control was changed; 35 FPS, the 20 ms exposure cap,
automatic exposure/gain/white balance, Bayer format, ISP state and calibration stayed unchanged.

| Measurement (10 frames per stage) | Before: 0.75 | Test: 0.65 | Restored: 0.75 |
|---|---:|---:|---:|
| Mean brightness, 0â€“255 | 103.59 | 113.74 | 103.50 |
| Median brightness, 0â€“255 | 100 | 113 | 100 |
| Fully clipped pixels | 5.645% | 5.646% | 5.639% |
| Camera FPS, frame-header estimate | 35.04 | 35.01 | 34.98 |

The test brightened the image by **9.8%** on average, with essentially unchanged
full clipping. Actual pixels changed even with ISP disabled. This is a brightness
choice for the tested scene; a colour chart is still needed to measure colour
accuracy, and gamma cannot recover detail already lost in reflections.

Device 5 now uses 0.65 at runtime, with `FLIR_GAMMA=0.65` saved in its own
`src/node_pc/config/network.env`. The previous file was backed up under
`/var/lib/cmp-maintenance/`. Acquisition and the Windows recorder were not restarted.

## Apply using existing controls

On the physical sensor PC, load its own environment and ROS installation:

```bash
source /opt/ros/noetic/setup.bash
set -a; source ~/catkin_ws_actual/src/node_pc/config/network.env; set +a
rosrun dynamic_reconfigure dynparam set /camera/spinnaker_camera_nodelet gamma 0.65
```

To persist it, change only `FLIR_GAMMA` in that PC's `network.env`. It is loaded
at the next full pipeline/service start. The already-running wrapper retains its
old environment, so an internal watchdog relaunch before that full restart may
temporarily restore the old launch value; verify gamma after any recovery.
No restart was forced during this test. For rollback, set gamma to **0.75** and
restore `FLIR_GAMMA=0.75` in that file.

Other cameras/lighting require their own before/after check. Do not copy Device 5's
addresses or calibration, change image dimensions, or enable heavy enhancement
just to apply this setting. Captured images and detailed test evidence stay in the
local Device Monitor analysis folder and are excluded from GitHub.
