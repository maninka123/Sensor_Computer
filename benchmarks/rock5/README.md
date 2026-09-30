# ROCK 5A pipeline benchmark

This uses the production ROS nodes and the connected FLIR camera and Livox
LiDAR. Benchmark launch overrides stay in this folder; the production pipeline
code and configuration are unchanged. The runner stops production while it
owns the sensors and restores it afterward.

| Run | LiDAR scans per cloud | Image enhancement | Expected final rate |
| --- | ---: | :---: | ---: |
| A | 1 | Off | 10 Hz |
| B | 3 | Off | 3.33 Hz |
| C | 10 | Off | 1 Hz |
| D | 10 | On | 1 Hz |

## Results

A–C were measured for about one minute each after warm-up. The final column
is a 30-minute stability run of C. The [single compact result file](results/benchmark.json)
contains the exact values and sample counts. D has no valid full-window result,
so it is not compared here.

| Metric | A · stack 1 | B · stack 3 | C · stack 10 | C · 30 min |
| --- | ---: | ---: | ---: | ---: |
| LiDAR input Hz | 10.008 | 9.998 | 10.011 | 10.000 |
| Camera FPS | 34.986 | 34.977 | 34.974 | 34.974 |
| Merged / filtered Hz | 10.008 / 9.991 | 3.322 / 3.338 | 0.991 / 1.008 | 1.000 / 1.000 |
| **Expected → measured final Hz** | **10.00 → 9.991** | **3.33 → 3.338** | **1.00 → 1.008** | **1.00 → 1.000** |
| Output-rate target¹ | 🟢 Met | 🟢 Met | 🟢 Met | 🟢 Met |
| Processing p95 vs output period² | 🟢 82.7 / 100 ms | 🟢 206.3 / 300 ms | 🟢 648.9 / 1,000 ms | 🟢 644.5 / 1,000 ms |
| Merge / filter / colourize median ms | 7.8 / 44.1 / 10.5 | 23.9 / 112.8 / 29.4 | 84.1 / 356.9 / 63.9 | 75.0 / 379.0 / 70.9 |
| Total processing median ms | 62.4 | 166.8 | 510.7 | 524.1 |
| Input / filtered / final points | 24,000 / 18,093 / 18,093 | 72,000 / 54,347 / 54,347 | 240,000 / 181,151 / 181,151 | 240,000 / 181,472 / 181,462 |
| Final MB/message | 0.651 | 1.956 | 6.521 | 6.533 |
| **Final MB/s** | **6.508** | **6.531** | **6.572** | **6.536** |
| System CPU % | 42.5 | 43.0 | 36.9 | 43.8 |
| Pipeline CPU, % of one core | 124.0 | 117.4 | 123.0 | 119.0 |
| RAM used MB | 3,474 | 3,500 | 3,555 | 3,600 |
| SoC average / maximum °C | 83.6 / 84.1 | 83.7 / 85.0 | 83.1 / 85.0 | 84.0 / 85.0 |
| Dropped / expected batches | 0 / 607 | 0 / 200 | 0 / 60 | **0 / 1,800** |
| Matched / input frames | 606 / 606 | 603 / 603 | 610 / 610 | **18,009 / 18,010** |

¹ A one-message boundary difference is allowed when judging rate. ² p95 is
observer-side topic-to-topic latency; it excludes the deliberate wait to
accumulate scans. Measurements include the running desktop and Wi-Fi, so a
different cooling or system workload may change them.

## Run it

From the workspace root, with both sensors connected:

```bash
bash benchmarks/rock5/run_all.sh
```

The default run measures A–D for 60 seconds each, then C for 30 minutes. It
prompts for `sudo` to stop and restore the boot services. Use `--help` for
shorter runs or individual cases; only a compact JSON summary belongs in Git.

Rates count received messages over measured time. MB uses decimal bytes;
system CPU covers the whole board, while pipeline CPU is relative to one core.
The timing values include ROS scheduling and observer overhead, not just the
processing functions.
