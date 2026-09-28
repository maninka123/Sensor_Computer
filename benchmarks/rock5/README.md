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

## Results — 28 September 2026

The [comparison summary](results/2026-09-28-comparison.json) contains 60-second
measurements after a 20-second warm-up for A–C. D was stopped after 15.8 seconds
when the conservative 80 °C guard reached 81.3 °C. Enhancement was effective
in all 16 sampled status checks before that stop, but D is **invalid** as a
60-second comparison; its partial measurements are retained only for diagnosis.
The [30-minute C summary](results/2026-09-28-stability.json) is separate.

🔴 Wi‑Fi, VS Code, Firefox, and the graphical desktop were active on the board.
The runs were thermally limited (about 83–85 °C). A cooler, headless setup
could improve performance; these are **observed results, not the board's maximum**.

| Metric | A: stack 1 | B: stack 3 | C: stack 10 | D: stack 10 + enhancement |
| --- | ---: | ---: | ---: | ---: |
| LiDAR input Hz | 10.008 | 9.998 | 10.011 | Invalid |
| Camera FPS | 34.986 | 34.977 | 34.974 | Invalid |
| Merged Hz | 10.008 | 3.322 | 0.991 | Invalid |
| Filtered Hz | 9.991 | 3.338 | 1.008 | Invalid |
| **Expected → measured final Hz** | **10.00 → 9.991** | **3.33 → 3.338** | **1.00 → 1.008** | **1.00 → invalid** |
| Output-rate target¹ | 🟢 Met | 🟢 Met | 🟢 Met | 🔴 Not verified |
| Processing within output period² | 🟢 82.7 < 100 ms | 🟢 206.3 < 300 ms | 🟢 648.9 < 1,000 ms | 🔴 Not verified |
| Merge latency median ms | 7.8 | 23.9 | 84.1 | Invalid |
| Filter latency median ms | 44.1 | 112.8 | 356.9 | Invalid |
| Colourization latency median ms | 10.5 | 29.4 | 63.9 | Invalid |
| **Total processing-path latency median ms** | **62.4** | **166.8** | **510.7** | Invalid |
| Raw LiDAR points/message | 24,000 | 24,000 | 24,000 | Invalid |
| Merged points/message | 24,000 | 72,000 | 240,000 | Invalid |
| Filtered points/message | 18,093 | 54,347 | 181,151 | Invalid |
| Final points/message | 18,093 | 54,347 | 181,151 | Invalid |
| Final cloud MB/message | 0.651 | 1.956 | 6.521 | Invalid |
| **Final output MB/s** | **6.508** | **6.531** | **6.572** | Invalid |
| System CPU % | 42.5 | 43.0 | 36.9 | Invalid |
| Pipeline CPU, % of one core | 124.0 | 117.4 | 123.0 | Invalid |
| RAM used MB | 3,474 | 3,500 | 3,555 | Invalid |
| SoC average / maximum °C | 83.6 / 84.1 | 83.7 / 85.0 | 83.1 / 85.0 | Invalid |
| Dropped / expected batches | 0 / 607 | 0 / 200 | 0 / 60 | Invalid |
| Matched / input frames | 606 / 606 | 603 / 603 | 610 / 610 | Invalid |

¹ In a 60-second window, a one-message boundary difference is about 0.017 Hz;
the rate check allows that counting uncertainty. ² The value shown is the
**95th-percentile** observed topic-to-topic latency, compared with the output
period. It excludes the intentional wait to accumulate 3 or 10 LiDAR scans and
does not guarantee every cloud meets its deadline.

The 30-minute **C stability run** produced 1,801 final clouds in 1,800.129 s:

| Stability metric | Result |
| --- | ---: |
| Expected → measured final Hz | **1.00 → 1.000** 🟢 |
| Processing p95 vs 1,000 ms output period | **644.5 ms** 🟢 |
| LiDAR / camera input | 10.000 Hz / 34.974 FPS |
| Merge / filter / colourization median | 75.0 / 379.0 / 70.9 ms |
| Total processing-path median / p95 | 524.1 / 644.5 ms |
| Final points / MB per message / MB/s | 181,462 / 6.533 / 6.536 |
| System CPU / pipeline CPU of one core | 43.8% / 119.0% |
| RAM used | 3,600 MB |
| SoC average / maximum | 84.0 / 85.0 °C |
| Dropped / expected batches | **0 / 1,800** |
| Matched / input frames | **18,009 / 18,010** |

This sustained run met the 1 Hz output target and had no reported dropped
batches, despite the thermally constrained desktop environment. The near-perfect
matching ratio is 99.994%, not 100%.

## Results — 25 September 2026 thermal-limited pilot

These are **10-second measurements after a 5-second warm-up**, not sustained
performance claims. They were taken on a Radxa ROCK 5A with the desktop still
running; SoC temperature was 83–85 °C, and run B touched the production
enhancement cutoff. Compare rates and payloads directionally, not as a cooled
or headless performance baseline. The [6 KB summary](results/2026-09-25-thermal-pilot.json)
contains the exact values and sample counts.

🔴 Wi‑Fi, VS Code, Firefox, and the graphical desktop were active during this
pilot. A cooler, headless run may give better CPU and latency results; this
table is **not** the ROCK 5A's maximum achievable performance.

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
| Expected → measured final Hz | 10.00 → 10.07 | 3.33 → 3.29 | 1.00 → 0.96 | 1.00 → invalid |
| Rate target in 10-second window | 🟢 Met | 🟢 Met | 🟢 Met | 🔴 Not verified |
| Processing within output period | 🟢 56.6 < 100 ms | 🟢 165.1 < 300 ms | 🟢 482.4 < 1,000 ms | 🔴 Not verified |
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

The rate check allows one message of boundary uncertainty in each 10-second
window (0.1 Hz); it is **not** a sustained-rate pass. The processing check
compares median topic-to-topic latency with the expected output period and
does not prove every individual cloud met that deadline.

The later 30-minute C stability run above supersedes this pilot for sustained
rate and reliability assessment.

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
