# SCI ROCK 5 Model A CPU inference

This directory is self-contained. Copy the entire **SBC inference** directory to a
ROCK 5A running 64-bit Radxa OS/Debian/Ubuntu, then run these commands inside it.

## Optimization report

See `ROCK5A_CPU_Optimization_Report.pdf` for the before/after architecture changes,
CPU benchmark tables and graphs, output-fidelity checks, deployment contents, and
instructions for reproducing the benchmark on the ROCK 5A. The reported timing
comparison was measured on the development x86 CPU; run `benchmark.py` on the board
to obtain the final ARM performance figures.

## Quick start

```bash
cd "SBC inference"
chmod +x install_rock5a.sh run_rock5a.sh
./install_rock5a.sh
./run_rock5a.sh sample_input.png --benchmark
```

The enhanced file is written to `outputs/sample_input_enhanced.png`.

For your own image or a whole directory:

```bash
./run_rock5a.sh /path/to/dark.jpg --output outputs --benchmark
./run_rock5a.sh /path/to/images --output outputs --recursive --benchmark
```

Run the before/after benchmark **on the ROCK 5A**. It compares the original eager
model, TorchScript, and ONNX Runtime:

```bash
.venv/bin/python benchmark.py --runs 50 --save-images
```

This writes `results/benchmark.csv`, `results/benchmark.json`, and both baseline
and optimized sample outputs. Board performance must be measured on the board
because cooling, OS image, power mode, and throttling matter.

## ROCK 5A CPU tuning

The RK3588S contains four Cortex-A76 performance cores (up to 2.4 GHz) and four
Cortex-A55 efficiency cores (up to 1.8 GHz). The scripts automatically detect the
fastest Linux CPU cluster, pin the process to it, and use four inference threads.
This avoids moving convolution work between unlike CPU clusters.

- Start with the defaults: `--threads 4 --affinity auto`.
- Benchmark `--threads 1`, `--threads 2`, and `--threads 4`; keep the lowest median
  for your OS/PyTorch combination.
- TorchScript is the default backend because it was faster on the development host.
  If the `optimized_onnx` row is faster on your ROCK 5A, run inference with
  `--backend onnx`.
- If automatic Linux detection is unavailable, use `--affinity 4,5,6,7` only after
  confirming those are your A76 core IDs with `lscpu -e` and the sysfs frequency files.
- `--affinity none` lets Linux schedule across all eight cores. It can help with
  multiple concurrent images, but commonly hurts single-image latency.
- `--max-side 640` is an optional high-speed mode. It resizes large inputs before
  inference. The default `0` retains the full input resolution and quality.
- Use a heatsink/fan and a stable USB-C PD supply. Radxa recommends its 30 W adapter.
- Model-only timing excludes image decoding and PNG writing. PNG output uses low
  compression because maximum PNG compression wastes CPU without changing pixels.

## What was optimized

The original training model has three iterative stages and a 16-channel
self-calibration network. SCI intentionally discards the calibrator for inference:
only the shared, 3-channel illumination estimator is needed. This package then:

1. removes training losses and the calibrator;
2. folds BatchNorm into the preceding convolution exactly;
3. uses in-place activations/arithmetic to reduce temporary memory;
4. freezes the inference graph as portable TorchScript;
5. uses channels-last image memory, `torch.inference_mode()`, A76 affinity, and a
   small ARM-friendly thread pool;
6. avoids `torchvision`, OpenCV, and all training dependencies.

The deployed graph has only **252 scalar parameters after BatchNorm fusion** and
three 3x3 convolutions. `model_info.json` records export validation errors.

## Files

- `model_cpu.pt`: ready-to-run frozen TorchScript model.
- `model_cpu.onnx`: alternative optimized ONNX Runtime model.
- `infer.py`: single-image and directory inference CLI.
- `benchmark.py`: reproducible original-vs-optimized latency and output check.
- `weights/Model_V3.pt`: original checkpoint used for export and baseline timing.
- `export_model.py`, `model_def.py`: reproducible model export; not needed for normal inference.
- `sample_input.png`: test image.
- `results/`: measured benchmark and sample enhanced images.

To rebuild the deployment model after changing weights:

```bash
.venv/bin/python -m pip install -r requirements-export.txt
.venv/bin/python export_model.py --weights weights/Model_V3.pt --output model_cpu.pt
```

## Important notes

- Use **64-bit** Linux (`uname -m` must print `aarch64`).
- This is CPU-only as requested. The RK3588S NPU is deliberately not used.
- The package uses the existing `Model_V3.pt` checkpoint. Switching V1/V2 changes
  learned image appearance, not network speed.
- Optimized and baseline images should be visually identical. Tiny floating-point
  differences from BatchNorm folding are expected and reported by the benchmark.
- If `pip` cannot find a compatible `torch` wheel, update the OS/Python and follow
  the current CPU/Linux install selector at https://pytorch.org/get-started/locally/.
