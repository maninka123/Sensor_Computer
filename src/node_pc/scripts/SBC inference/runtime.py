"""Shared high-speed image I/O and TorchScript runtime helpers."""

from __future__ import annotations

import os
import platform
from pathlib import Path

import numpy as np
import torch


IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def performance_cpus() -> list[int]:
    """Detect the fastest Linux CPU cluster without assuming core numbering."""
    if platform.system() != "Linux":
        return []
    capacities: dict[int, int] = {}
    for cpu_dir in Path("/sys/devices/system/cpu").glob("cpu[0-9]*"):
        try:
            cpu = int(cpu_dir.name[3:])
        except ValueError:
            continue
        values: list[int] = []
        for relative in ("cpu_capacity", "cpufreq/cpuinfo_max_freq"):
            try:
                values.append(int((cpu_dir / relative).read_text(encoding="ascii").strip()))
            except (FileNotFoundError, PermissionError, ValueError):
                pass
        if values:
            capacities[cpu] = max(values)
    if not capacities:
        return []
    fastest = max(capacities.values())
    return sorted(cpu for cpu, capacity in capacities.items() if capacity == fastest)


def default_threads() -> int:
    # RK3588S has four Cortex-A76 performance cores. Keeping this very narrow
    # network off the A55 cluster reduces scheduling and synchronization overhead.
    fast_cores = performance_cpus()
    return len(fast_cores) if fast_cores else max(1, min(4, os.cpu_count() or 1))


def configure_cpu(threads: int, affinity: str = "auto") -> list[int]:
    if threads < 1:
        raise ValueError("--threads must be at least 1")
    selected: list[int] = []
    if affinity != "none" and hasattr(os, "sched_setaffinity"):
        if affinity == "auto":
            selected = performance_cpus()
        else:
            try:
                selected = sorted({int(value) for value in affinity.split(",")})
            except ValueError as error:
                raise ValueError("--affinity must be 'auto', 'none', or comma-separated CPU IDs") from error
        if selected:
            available = set(os.sched_getaffinity(0))
            selected = [cpu for cpu in selected if cpu in available]
            if selected:
                os.sched_setaffinity(0, selected)
    torch.set_num_threads(threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        # Inter-op threads can only be set once per process.
        pass
    return selected


def load_model(path: Path) -> torch.jit.ScriptModule:
    model = torch.jit.load(str(path), map_location="cpu").eval()
    return model


def load_onnx_model(path: Path, threads: int):
    try:
        import onnxruntime as ort
    except ImportError as error:
        raise RuntimeError("ONNX backend requires: python -m pip install onnxruntime") from error
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def run_model(model, tensor: torch.Tensor, backend: str) -> torch.Tensor:
    if backend == "onnx":
        array = tensor.numpy()
        return torch.from_numpy(model.run(None, {"input": array})[0])
    return model(tensor)


def discover_images(path: Path, recursive: bool = False) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image type: {path.suffix}")
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(path)
    iterator = path.rglob("*") if recursive else path.glob("*")
    return sorted(item for item in iterator if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS)


def image_to_tensor(path: Path, max_side: int = 0) -> tuple[torch.Tensor, tuple[int, int]]:
    from PIL import Image

    with Image.open(path) as opened:
        image = opened.convert("RGB")
        original_size = image.size
        if max_side > 0 and max(image.size) > max_side:
            scale = max_side / max(image.size)
            resized = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            image = image.resize(resized, Image.Resampling.BILINEAR)
        array = np.asarray(image, dtype=np.float32)
    # HWC numpy -> NCHW tensor naturally has channels-last strides, avoiding an
    # extra memory-layout conversion before ARM convolution kernels.
    tensor = torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0).div_(255.0)
    return tensor, original_size


def tensor_to_image(tensor: torch.Tensor):
    from PIL import Image

    array = (
        tensor.squeeze(0)
        .permute(1, 2, 0)
        .mul(255.0)
        .round_()
        .clamp_(0.0, 255.0)
        .to(torch.uint8)
        .cpu()
        .numpy()
    )
    return Image.fromarray(array, mode="RGB")


def save_image(image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        image.save(path, quality=95, subsampling=0)
    elif suffix == ".png":
        image.save(path, compress_level=1)
    else:
        image.save(path)


def bgr_array_to_tensor(image: np.ndarray) -> torch.Tensor:
    """Convert an OpenCV/ROS BGR8 array directly to an RGB model tensor."""
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"Expected an HxWx3 BGR image, got shape {image.shape}")
    if image.dtype != np.uint8:
        raise ValueError(f"Expected uint8 image data, got {image.dtype}")
    rgb = np.ascontiguousarray(image[:, :, ::-1])
    return torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(torch.float32).div_(255.0)


def tensor_to_bgr_array(tensor: torch.Tensor) -> np.ndarray:
    """Convert a model RGB tensor directly to a contiguous OpenCV BGR8 array."""
    rgb = (
        tensor.squeeze(0)
        .permute(1, 2, 0)
        .mul(255.0)
        .round_()
        .clamp_(0.0, 255.0)
        .to(torch.uint8)
        .cpu()
        .numpy()
    )
    return np.ascontiguousarray(rgb[:, :, ::-1])
