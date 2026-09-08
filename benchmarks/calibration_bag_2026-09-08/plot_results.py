#!/usr/bin/env python3
"""Create benchmark comparison plots from the collected CSV files."""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parent
PLOTS = ROOT / "plots"
PLOTS.mkdir(exist_ok=True)


def save(name):
    plt.tight_layout()
    plt.savefig(PLOTS / name, dpi=180)
    plt.close()


off = pd.read_csv(ROOT / "raw/off_topics_wall.csv")
on = pd.read_csv(ROOT / "raw/on_topics_wall.csv")
comparison = off[["topic", "mean_hz", "payload_mib_per_s"]].merge(
    on[["topic", "mean_hz", "payload_mib_per_s"]], on="topic", suffixes=("_off", "_on")
)

x = range(len(comparison))
plt.figure(figsize=(12, 5))
plt.bar([i - 0.2 for i in x], comparison.mean_hz_off, width=0.4, label="Enhancement off")
plt.bar([i + 0.2 for i in x], comparison.mean_hz_on, width=0.4, label="Enhancement on")
plt.xticks(list(x), [t.replace("/livox/", "") for t in comparison.topic], rotation=35, ha="right")
plt.ylabel("Messages per wall second")
plt.title("Pipeline topic frame rates")
plt.legend()
save("enhancement_topic_rates.png")

fusion_topics = ["/livox/lidar_filtered", "/merged_colored_cloud"]
fusion = comparison[comparison.topic.isin(fusion_topics)].copy()
fusion["label"] = fusion.topic.map({
    "/livox/lidar_filtered": "Filtered cloud",
    "/merged_colored_cloud": "Colourized cloud",
})
x = range(len(fusion))
fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
axes[0].bar([i - 0.2 for i in x], fusion.mean_hz_off, width=0.4, label="Enhancement off")
axes[0].bar([i + 0.2 for i in x], fusion.mean_hz_on, width=0.4, label="Enhancement on")
axes[0].set_xticks(list(x))
axes[0].set_xticklabels(fusion.label)
axes[0].set_ylabel("Messages per wall second")
axes[0].set_title("Fusion output frequency")
axes[0].legend()
axes[1].bar([i - 0.2 for i in x], fusion.payload_mib_per_s_off, width=0.4, label="Enhancement off")
axes[1].bar([i + 0.2 for i in x], fusion.payload_mib_per_s_on, width=0.4, label="Enhancement on")
axes[1].set_xticks(list(x))
axes[1].set_xticklabels(fusion.label)
axes[1].set_ylabel("Payload MiB/s")
axes[1].set_title("Fusion output data rate")
axes[1].legend()
save("colorized_output_performance.png")

partial = pd.read_csv(ROOT / "raw/partial_batch_summary.csv")
fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
axes[0].bar(partial["mode"], partial["mean_matched_frames"], color=["tab:blue", "tab:orange"])
axes[0].axhline(5, color="tab:red", linestyle="--", linewidth=1, label="Configured minimum")
axes[0].set_ylim(0, 10.5)
axes[0].set_ylabel("Mean synchronized source frames")
axes[0].set_title("Frames retained per colourized cloud")
axes[0].legend()
axes[1].bar(partial["mode"], partial["mean_points"], color=["tab:blue", "tab:orange"])
axes[1].set_ylabel("Mean output points")
axes[1].set_title("Partial-batch point count")
for axis in axes:
    axis.set_xticks(range(len(partial)))
    axis.set_xticklabels(["Enhancement off", "Enhancement on"])
save("partial_batch_results.png")

sync = pd.read_csv(ROOT / "raw/sync_edge_summary.csv")
x = range(len(sync))
fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
for position, (prefix, label, color) in enumerate([
        ("first_abs", "Earliest frame", "tab:blue"),
        ("last_abs", "Latest frame", "tab:orange")]):
    means = sync[f"{prefix}_mean_ms"].to_numpy()
    lower = means - sync[f"{prefix}_best_ms"].to_numpy()
    upper = sync[f"{prefix}_worst_ms"].to_numpy() - means
    axes[0].bar([i + (position - 0.5) * 0.36 for i in x], means, width=0.36,
                yerr=[lower, upper], capsize=4, label=label, color=color)
axes[0].set_xticks(list(x))
axes[0].set_xticklabels(["Enhancement off", "Enhancement on"])
axes[0].set_ylabel("Absolute camera-LiDAR delta (ms)")
axes[0].set_title("First/last frame synchronization\nbar=mean, whisker=best to worst")
axes[0].axhline(50, color="#444444", linestyle="--", linewidth=1,
                label="50 ms tolerance")
axes[0].legend()
lag_mean = sync.output_event_lag_mean_ms.to_numpy()
lag_lower = lag_mean - sync.output_event_lag_best_ms.to_numpy()
lag_upper = sync.output_event_lag_worst_ms.to_numpy() - lag_mean
axes[1].bar(list(x), lag_mean, yerr=[lag_lower, lag_upper], capsize=4,
            color=["tab:blue", "tab:orange"])
axes[1].set_xticks(list(x))
axes[1].set_xticklabels(["Enhancement off", "Enhancement on"])
axes[1].set_ylabel("Newest event to output (ms)")
axes[1].set_title("Colourized-cloud exit lag\nbar=mean, whisker=best to worst")
save("sync_edge_timing.png")

processes = pd.read_csv(ROOT / "raw/process_summary.csv")
cpu = processes.pivot(index="process", columns="mode", values="mean_cpu_percent")
x = range(len(cpu))
plt.figure(figsize=(11, 5))
plt.bar([i - 0.2 for i in x], cpu.off.to_numpy(), width=0.4, label="Enhancement off")
plt.bar([i + 0.2 for i in x], cpu.on.to_numpy(), width=0.4, label="Enhancement on")
plt.xticks(list(x), cpu.index, rotation=30, ha="right")
plt.ylabel("CPU utilization (% of one core; may exceed 100%)")
plt.title("Per-process CPU utilization")
plt.legend()
save("process_cpu_comparison.png")

voxel = pd.read_csv(ROOT / "raw/voxel_sweep.csv")
fig, left = plt.subplots(figsize=(8, 5))
left.plot(voxel.voxel_size_m.to_numpy(), voxel.mean_points.to_numpy(), "o-", color="tab:blue", label="Mean points")
left.set_xlabel("Voxel leaf size (m)")
left.set_ylabel("Mean output points", color="tab:blue")
left.tick_params(axis="y", labelcolor="tab:blue")
right = left.twinx()
right.plot(voxel.voxel_size_m.to_numpy(), voxel.mean_hz.to_numpy(), "s--", color="tab:red", label="Output Hz")
right.set_ylabel("Filtered output Hz", color="tab:red")
right.tick_params(axis="y", labelcolor="tab:red")
plt.title("Voxel size: point count and output frequency")
fig.tight_layout()
plt.savefig(PLOTS / "voxel_points_and_frequency.png", dpi=180)
plt.close()

fig, left = plt.subplots(figsize=(8, 5))
left.plot(voxel.voxel_size_m.to_numpy(), voxel.mean_payload_kib.to_numpy(), "o-", color="tab:green")
left.set_xlabel("Voxel leaf size (m)")
left.set_ylabel("Mean cloud payload (KiB)", color="tab:green")
left.tick_params(axis="y", labelcolor="tab:green")
right = left.twinx()
right.plot(voxel.voxel_size_m.to_numpy(), voxel.payload_mib_per_s.to_numpy(), "s--", color="tab:purple")
right.set_ylabel("Output data rate (MiB/s)", color="tab:purple")
right.tick_params(axis="y", labelcolor="tab:purple")
plt.title("Voxel size: output size and data rate")
fig.tight_layout()
plt.savefig(PLOTS / "voxel_size_and_data_rate.png", dpi=180)
plt.close()

print(PLOTS)
