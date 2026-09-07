"""Build the portable, CPU-optimized TorchScript SCI model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from model_def import fuse_for_deployment, load_baseline


ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, default=ROOT / "weights" / "Model_V3.pt")
    parser.add_argument("--output", type=Path, default=ROOT / "model_cpu.pt")
    parser.add_argument("--onnx-output", type=Path, default=ROOT / "model_cpu.onnx")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(7)

    baseline = load_baseline(args.weights)
    fused = fuse_for_deployment(baseline).to(memory_format=torch.channels_last)

    # Script, freeze, and save a shape-independent graph. Avoid the x86-specific
    # optimize_for_inference pass so this artifact remains portable to ARM64.
    scripted = torch.jit.script(fused)
    frozen = torch.jit.freeze(scripted.eval())

    checks: list[dict[str, float | int]] = []
    with torch.inference_mode():
        for height, width in ((64, 96), (240, 320), (400, 600)):
            sample = torch.rand(1, 3, height, width).contiguous(
                memory_format=torch.channels_last
            )
            expected = baseline(sample)
            actual = frozen(sample)
            difference = (expected - actual).abs()
            checks.append(
                {
                    "height": height,
                    "width": width,
                    "max_abs_error": float(difference.max()),
                    "mean_abs_error": float(difference.mean()),
                }
            )
    worst_error = max(float(check["max_abs_error"]) for check in checks)
    if worst_error > 2e-5:
        raise RuntimeError(f"Export validation failed: max error is {worst_error:.8g}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.jit.save(frozen, str(args.output))
    try:
        import onnx  # noqa: F401
    except ImportError:
        print("ONNX export skipped; install requirements-export.txt to rebuild it")
    else:
        onnx_example = torch.rand(1, 3, 240, 320)
        torch.onnx.export(
            fused,
            onnx_example,
            str(args.onnx_output),
            input_names=["input"],
            output_names=["enhanced"],
            opset_version=17,
            dynamic_axes={
                "input": {2: "height", 3: "width"},
                "enhanced": {2: "height", 3: "width"},
            },
            do_constant_folding=True,
        )
    parameters = sum(parameter.numel() for parameter in fused.parameters())
    metadata = {
        "source_checkpoint": args.weights.name,
        "parameters_after_fusion": parameters,
        "torch_version_used_for_export": torch.__version__,
        "portable_targets": ["linux-aarch64", "linux-x86_64", "windows-x86_64"],
        "validation": checks,
    }
    metadata_path = args.output.with_name("model_info.json")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {args.output} ({args.output.stat().st_size / 1024:.1f} KiB)")
    if args.onnx_output.exists():
        print(f"Saved {args.onnx_output} ({args.onnx_output.stat().st_size / 1024:.1f} KiB)")
    print(f"Validation max absolute error: {worst_error:.8g}")


if __name__ == "__main__":
    main()
