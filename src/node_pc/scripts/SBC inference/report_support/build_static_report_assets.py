"""Build reproducible static chart assets for the PDF print representation."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "charts"
OUT.mkdir(exist_ok=True)

INK = "#202124"
MUTED = "#6b7280"
GRID = "#e5e7eb"
BLUE = "#1677c8"
ORANGE = "#e07a28"
OLIVE = "#72843c"


def read_csv(name: str) -> list[dict[str, str]]:
    with (ROOT / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def style_axis(axis) -> None:
    axis.set_facecolor("white")
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color(GRID)
    axis.spines["bottom"].set_color(GRID)
    axis.tick_params(colors=MUTED, labelsize=9, length=0)
    axis.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    axis.set_axisbelow(True)


def latency_chart() -> None:
    rows = read_csv("benchmark_aggregate.csv")
    threads = [1, 2, 4]
    backends = ["Original eager PyTorch", "Fused TorchScript", "ONNX Runtime"]
    colors = [MUTED, BLUE, ORANGE]
    lookup = {(int(row["threads"]), row["backend"]): float(row["median_ms"]) for row in rows}
    x = np.arange(len(threads))
    width = 0.23
    fig, axis = plt.subplots(figsize=(9.2, 4.4), dpi=180)
    for index, (backend, color) in enumerate(zip(backends, colors)):
        values = [lookup[(thread, backend)] for thread in threads]
        bars = axis.bar(
            x + (index - 1) * width,
            values,
            width,
            label=backend,
            color=color,
            edgecolor=INK if backend == "Original eager PyTorch" else color,
            linewidth=0.65,
            zorder=3,
        )
        for bar, value in zip(bars, values):
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                value + 0.14,
                f"{value:.2f}",
                ha="center",
                va="bottom",
                color=INK,
                fontsize=8,
                fontweight="semibold",
            )
    style_axis(axis)
    axis.set_xticks(x, [str(thread) for thread in threads])
    axis.set_xlabel("CPU threads", color=INK, fontsize=10, labelpad=9)
    axis.set_ylabel("Median latency (ms)", color=INK, fontsize=10, labelpad=8)
    axis.set_ylim(0, 9.5)
    axis.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=3,
        frameon=False,
        fontsize=8.5,
        labelcolor=INK,
    )
    fig.tight_layout(pad=1.2)
    fig.savefig(OUT / "latency_by_threads.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def size_chart() -> None:
    rows = read_csv("file_inventory.csv")
    labels = [row["artifact"] for row in rows]
    values = [float(row["kib"]) for row in rows]
    colors = [MUTED, BLUE, OLIVE]
    x = np.arange(len(labels))
    fig, axis = plt.subplots(figsize=(8.4, 4.0), dpi=180)
    bars = axis.bar(x, values, width=0.56, color=colors, edgecolor=colors, linewidth=0.7, zorder=3)
    for bar, value in zip(bars, values):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.8,
            f"{value:.2f} KiB",
            ha="center",
            va="bottom",
            color=INK,
            fontsize=9,
            fontweight="semibold",
        )
    style_axis(axis)
    axis.set_xticks(x, labels)
    axis.set_ylabel("Artifact size (KiB)", color=INK, fontsize=10, labelpad=8)
    axis.set_ylim(0, 50)
    fig.tight_layout(pad=1.2)
    fig.savefig(OUT / "artifact_sizes.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    latency_chart()
    size_chart()
    print(f"Wrote static report charts to {OUT}")
