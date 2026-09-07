"""Fast standalone SCI inference for one image or a directory."""

from __future__ import annotations

import argparse
import platform
import statistics
import time
from pathlib import Path

import torch

from runtime import (
    configure_cpu,
    default_threads,
    discover_images,
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
    parser.add_argument("input", type=Path, help="Input image or directory")
    parser.add_argument("--output", "-o", type=Path, default=ROOT / "outputs")
    parser.add_argument("--model", type=Path, default=ROOT / "model_cpu.pt")
    parser.add_argument("--onnx-model", type=Path, default=ROOT / "model_cpu.onnx")
    parser.add_argument(
        "--backend",
        choices=("torchscript", "onnx"),
        default="torchscript",
        help="CPU runtime; benchmark both on the board before choosing",
    )
    parser.add_argument("--threads", type=int, default=default_threads())
    parser.add_argument(
        "--affinity",
        default="auto",
        help="Linux CPU affinity: auto selects the fastest cluster; use none or e.g. 4,5,6,7",
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=0,
        help="Optional speed mode: resize so the longest side is this size; 0 keeps full resolution",
    )
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--benchmark", action="store_true", help="Print model-only latency")
    return parser.parse_args()


def output_path(source: Path, input_root: Path, output_root: Path) -> Path:
    if input_root.is_file():
        relative = Path(source.name)
    else:
        relative = source.relative_to(input_root)
    return output_root / relative.parent / f"{relative.stem}_enhanced.png"


def main() -> None:
    args = parse_args()
    affinity = configure_cpu(args.threads, args.affinity)
    model = load_onnx_model(args.onnx_model, args.threads) if args.backend == "onnx" else load_model(args.model)
    sources = discover_images(args.input, recursive=args.recursive)
    if not sources:
        raise SystemExit(f"No supported images found in {args.input}")

    latencies_ms: list[float] = []
    with torch.inference_mode():
        for index, source in enumerate(sources):
            tensor, original_size = image_to_tensor(source, max_side=args.max_side)
            if index == 0:
                for _ in range(max(0, args.warmup)):
                    run_model(model, tensor, args.backend)

            started = time.perf_counter()
            enhanced = run_model(model, tensor, args.backend)
            latency_ms = (time.perf_counter() - started) * 1000.0
            latencies_ms.append(latency_ms)

            destination = output_path(source, args.input, args.output)
            save_image(tensor_to_image(enhanced), destination)
            resolution = f"{tensor.shape[-1]}x{tensor.shape[-2]}"
            resize_note = "" if original_size == (tensor.shape[-1], tensor.shape[-2]) else f" from {original_size[0]}x{original_size[1]}"
            print(f"{source.name} -> {destination} | {resolution}{resize_note} | {latency_ms:.2f} ms")

    if args.benchmark:
        median = statistics.median(latencies_ms)
        mean = statistics.fmean(latencies_ms)
        print(
            f"Model-only: median {median:.2f} ms, mean {mean:.2f} ms, "
            f"{1000.0 / median:.1f} FPS | threads={args.threads} | "
            f"backend={args.backend} | affinity={affinity or 'OS-managed'} | "
            f"{platform.machine()} | torch={torch.__version__}"
        )


if __name__ == "__main__":
    main()
