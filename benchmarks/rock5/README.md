# ROCK 5A hardware pipeline benchmark

This benchmark runs the **existing production ROS nodes** against the attached
FLIR camera and Livox LiDAR. Its launch overrides are confined to this folder;
`src/node_pc/config/pipeline.yaml`, the production launch files, and processing
code are unchanged. Production services are stopped while a benchmark owns the
sensors and restarted on normal completion or interruption.

## Configurations

| Run | LiDAR scans per merged cloud | Image enhancement | Minimum matched camera frames | Expected output at 10 Hz input |
| --- | ---: | :---: | ---: | ---: |
| A | 1 | Off | 1 | 10 Hz |
| B | 3 | Off | 3 | 3.33 Hz |
| C | 10 | Off | 3 | 1 Hz |
| D | 10 | On | 3 | 1 Hz |

All other filtering, camera, synchronization, and thermal-protection settings
come from the production configuration. The enhancement run is only valid if
`/image_enhancement/status` stays true; the benchmark refuses a thermally
disabled run. It samples `soc-thermal` at `/sys/class/thermal/thermal_zone0`.
The default start limit is below 70 °C and the run aborts at 80 °C, below the
production enhancer's 85 °C thermal cutoff.

## Results — 25 September 2026 thermal-limited pilot

These are **10-second measurements after a 5-second warm-up**, not sustained
performance claims. They were taken on a Radxa ROCK 5A with the desktop still
running; SoC temperature was 83–85 °C, and run B touched the production
enhancement cutoff. Compare rates and payloads directionally, not as a cooled
or headless performance baseline. The [6 KB summary](results/2026-09-25-thermal-pilot.json)
contains the exact values and sample counts.

An attempted D run reached 85.9 °C and the thermal protector turned
enhancement off, so it is **invalid and excluded**. The 30-minute C stability
run was deferred because of the user's time limit and high temperature.

| Metric | A: stack 1 | B: stack 3 | C: stack 10 | D: stack 10 + enhancement |
| --- | ---: | ---: | ---: | ---: |
| LiDAR input Hz | 9.97 | 9.98 | 9.97 | Invalid |
| Camera FPS | 34.94 | 34.97 | 34.90 | Invalid |
| Merged Hz | 9.97 | 3.39 | 0.96 | Invalid |
| Filtered Hz | 10.07 | 3.29 | 0.96 | Invalid |
| Final coloured cloud Hz | 10.07 | 3.29 | 0.96 | Invalid |
| Merge latency ms | 6.1 | 20.6 | 72.0 | Invalid |
| Filter latency ms | 42.1 | 119.2 | 351.7 | Invalid |
| Colourization latency ms | 7.7 | 25.1 | 56.2 | Invalid |
| **Total processing-path latency ms** | **56.6** | **165.1** | **482.4** | Invalid |
| Raw LiDAR points/message | 24,000 | 24,000 | 24,000 | Invalid |
| Merged points/message | 24,000 | 72,000 | 240,000 | Invalid |
| Filtered points/message | 17,966 | 54,016 | 179,805 | Invalid |
| Final points/message | 17,966 | 54,016 | 179,805 | Invalid |
| Final cloud MB/message | 0.65 | 1.95 | 6.47 | Invalid |
| **Final output MB/s** | **6.51** | **6.41** | **6.21** | Invalid |
| System CPU % | 43.1 | 52.6 | 47.9 | Invalid |
| Pipeline CPU, % of one core | 115.2 | 111.9 | 108.9 | Invalid |
| RAM used MB | 4,452 | 4,480 | 4,586 | Invalid |
| SoC average / maximum °C | 83.2 / 84.1 | 84.4 / 85.0 | 83.7 / 84.1 | Invalid |
| Dropped / expected batches | 0 / 103 | 0 / 35 | 0 / 10 | Invalid |
| Matched / input frames | 104 / 104 | 102 / 102 | 100 / 100 | Invalid |

For stability, only configuration C is scheduled to run for 30 minutes. Its
sustained final rate, dropped batches, matching ratio, and maximum SoC
temperature remain pending a cooler, longer session.

## Run it

From the workspace root, with both sensors connected and adequate cooling:

```bash
bash benchmarks/rock5/run_all.sh
```

The command prompts for `sudo` to stop and restore the three boot services.
Allow server disconnection during the test. Default measurements are 60 seconds
per configuration after a 20-second warm-up, followed by a 1,800-second C
stability run. Use `--duration`, `--warmup`, or `--stability-seconds` to change
those lengths. `--skip-enhancement --skip-stability` runs only A–C, as done for
the thermal-limited pilot. The only repository output is one compact JSON summary under
`results/`; temporary launch logs and per-run summaries stay in `/tmp` and are
not committed. To inspect current service health afterward:

```bash
systemctl is-active node-pc.service node-pc-rosbridge.service \
  node-pc-transport-supervisor.service
./monitor_pipeline.sh
```

## Metric definitions and limitations

Rates count received messages over measured wall time. Points are mean
`width × height`; final MB/message is mean point payload bytes ÷ 1,000,000,
and MB/s is all final point payload bytes ÷ measured seconds. CPU is the mean
whole-board busy percentage across logical cores; optional per-node figures
are percentages of **one core**, so they can exceed 100%. RAM is mean
`MemTotal − MemAvailable`, including other system activity, not just pipeline
RSS. Temperature is the mean and maximum `soc-thermal` reading.

Merge, filter, colourization, and total timings are **observer-side
topic-to-topic latencies**, matched by cloud header timestamp: shifted LiDAR →
merged, merged → filtered, filtered → final, and shifted LiDAR → final. They
include ROS scheduling/serialization and observer load, so they are not pure
internal function times. The total is measured directly; it need not equal
the sum of stage medians. Stack accumulation wait is excluded from the total.

`expected_batches` is the number of merged clouds observed, and
`dropped_batches` is the change in the colourizer's cumulative drop counter.
Matched/input frames are sums of the colourizer's status values in the
measurement window. The small observer subscribes to large clouds to read
point counts and payload sizes; its overhead is included in system CPU. Keep
the same observer and cooling setup for every run.
