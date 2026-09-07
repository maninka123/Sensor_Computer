"""Benchmark baseline eager SCI against the fused/frozen deployment model."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import statistics
import time
from pathlib import Path

import torch

from model_def import load_baseline
from runtime import (
    configure_cpu,
    default_threads,
    image_to_tensor,
    load_model,
    load_onnx_model,
    run_model,
    save_image,
    tensor_to_image,
)


ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "sample_input.png")
    parser.add_argument("--weights", type=Path, default=ROOT / "weights" / "Model_V3.pt")
    parser.add_argument("--model", type=Path, default=ROOT / "model_cpu.pt")
    parser.add_argument("--onnx-model", type=Path, default=ROOT / "model_cpu.onnx")
    parser.add_argument("--threads", type=int, default=default_threads())
    parser.add_argument(
        "--affinity",
        default="auto",
        help="Linux CPU affinity: auto, none, or comma-separated CPU IDs",
    )
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--save-images", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    return parser.parse_args()


def measure(model: torch.nn.Module, tensor: torch.Tensor, warmup: int, runs: int) -> list[float]:
    for _ in range(max(0, warmup)):
        model(tensor)
    timings: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        model(tensor)
        timings.append((time.perf_counter() - started) * 1000.0)
    return timings


def measure_backend(model, tensor: torch.Tensor, backend: str, warmup: int, runs: int) -> list[float]:
    for _ in range(max(0, warmup)):
        run_model(model, tensor, backend)
    timings: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        run_model(model, tensor, backend)
        timings.append((time.perf_counter() - started) * 1000.0)
    return timings


def summarize(name: str, values: list[float]) -> dict[str, float | str]:
    median = statistics.median(values)
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return {
        "model": name,
        "median_ms": median,
        "mean_ms": statistics.fmean(values),
        "p95_ms": p95,
        "fps_from_median": 1000.0 / median,
    }


def main() -> None:
    args = parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    affinity = configure_cpu(args.threads, args.affinity)
    tensor, _ = image_to_tensor(args.input)
    baseline = load_baseline(args.weights).to(memory_format=torch.channels_last)
    optimized = load_model(args.model)
    onnx_model = None
    if args.onnx_model.exists():
        try:
            onnx_model = load_onnx_model(args.onnx_model, args.threads)
        except RuntimeError as error:
            print(f"ONNX benchmark skipped: {error}")

    with torch.inference_mode():
        baseline_output = baseline(tensor)
        optimized_output = optimized(tensor)
        difference = (baseline_output - optimized_output).abs()
        baseline_times = measure(baseline, tensor, args.warmup, args.runs)
        optimized_times = measure(optimized, tensor, args.warmup, args.runs)

    rows = [summarize("baseline_eager", baseline_times), summarize("optimized_torchscript", optimized_times)]
    onnx_difference = None
    if onnx_model is not None:
        onnx_output = run_model(onnx_model, tensor, "onnx")
        onnx_difference = (baseline_output - onnx_output).abs()
        onnx_times = measure_backend(onnx_model, tensor, "onnx", args.warmup, args.runs)
        rows.append(summarize("optimized_onnx", onnx_times))

    speedup = float(rows[0]["median_ms"]) / float(rows[1]["median_ms"])
    report = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "threads": args.threads,
        "cpu_affinity": affinity or "OS-managed",
        "resolution": f"{tensor.shape[-1]}x{tensor.shape[-2]}",
        "runs": args.runs,
        "speedup": speedup,
        "max_abs_output_error": float(difference.max()),
        "mean_abs_output_error": float(difference.mean()),
        "onnx_max_abs_output_error": None if onnx_difference is None else float(onnx_difference.max()),
        "results": rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with (args.output / "benchmark.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    if args.save_images:
        save_image(tensor_to_image(baseline_output), args.output / "sample_output_baseline.png")
        save_image(tensor_to_image(optimized_output), args.output / "sample_output_optimized.png")
        if onnx_model is not None:
            save_image(tensor_to_image(onnx_output), args.output / "sample_output_onnx.png")

    for row in rows:
        print(
            f"{row['model']:<23} median={float(row['median_ms']):8.3f} ms  "
            f"mean={float(row['mean_ms']):8.3f} ms  FPS={float(row['fps_from_median']):7.2f}"
        )
    print(f"Speedup: {speedup:.2f}x")
    print(
        f"Output check: max error={report['max_abs_output_error']:.8g}, "
        f"mean error={report['mean_abs_output_error']:.8g}"
    )
    print(f"Saved benchmark files to {args.output}")


if __name__ == "__main__":
    main()
