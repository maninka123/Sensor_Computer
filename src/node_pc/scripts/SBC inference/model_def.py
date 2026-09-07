"""Minimal SCI inference definitions.

This file intentionally contains no training losses or calibration network.  SCI uses
the calibration network only to train the shared illumination estimator; deployment
is a single illumination-estimation pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import torch
from torch import Tensor, nn


class BaselineSCI(nn.Module):
    """Inference part of the original ``Finetunemodel`` implementation."""

    def __init__(self) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(3, 3, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(3, 3, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm2d(3)
        self.conv3 = nn.Conv2d(3, 3, kernel_size=3, padding=1)

    def forward(self, x: Tensor) -> Tensor:
        features = torch.relu(self.conv1(x))
        features = features + torch.relu(self.bn2(self.conv2(features)))
        illumination = torch.clamp(torch.sigmoid(self.conv3(features)) + x, 0.0001, 1.0)
        return torch.clamp(x / illumination, 0.0, 1.0)


class FusedSCI(nn.Module):
    """Deployment graph with BatchNorm folded into conv2 and fewer allocations."""

    def __init__(self) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(3, 3, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(3, 3, kernel_size=3, padding=1)
        self.conv3 = nn.Conv2d(3, 3, kernel_size=3, padding=1)

    def forward(self, x: Tensor) -> Tensor:
        features = torch.relu_(self.conv1(x))
        features.add_(torch.relu_(self.conv2(features)))
        illumination = torch.sigmoid_(self.conv3(features))
        illumination.add_(x).clamp_(0.0001, 1.0)
        return torch.div(x, illumination).clamp_(0.0, 1.0)


def _unwrap_checkpoint(checkpoint: object) -> Mapping[str, Tensor]:
    if not isinstance(checkpoint, Mapping):
        raise TypeError("Checkpoint must contain a state-dict mapping")
    for key in ("model", "state_dict", "model_state_dict"):
        nested = checkpoint.get(key)
        if isinstance(nested, Mapping):
            checkpoint = nested
            break
    return checkpoint  # type: ignore[return-value]


def _load_checkpoint(path: str | Path) -> Mapping[str, Tensor]:
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:  # PyTorch < 2.0
        checkpoint = torch.load(path, map_location="cpu")
    return _unwrap_checkpoint(checkpoint)


def load_baseline(path: str | Path) -> BaselineSCI:
    """Load the enhancement weights from an original SCI training checkpoint."""
    state = _load_checkpoint(path)
    required = {
        "conv1.weight": "enhance.in_conv.0.weight",
        "conv1.bias": "enhance.in_conv.0.bias",
        "conv2.weight": "enhance.conv.0.weight",
        "conv2.bias": "enhance.conv.0.bias",
        "bn2.weight": "enhance.conv.1.weight",
        "bn2.bias": "enhance.conv.1.bias",
        "bn2.running_mean": "enhance.conv.1.running_mean",
        "bn2.running_var": "enhance.conv.1.running_var",
        "bn2.num_batches_tracked": "enhance.conv.1.num_batches_tracked",
        "conv3.weight": "enhance.out_conv.0.weight",
        "conv3.bias": "enhance.out_conv.0.bias",
    }
    missing = [source for source in required.values() if source not in state]
    if missing:
        raise KeyError(f"Checkpoint is missing SCI enhancement tensors: {missing}")
    model = BaselineSCI()
    model.load_state_dict({target: state[source] for target, source in required.items()})
    return model.eval()


def fuse_for_deployment(baseline: BaselineSCI) -> FusedSCI:
    """Fold eval-mode BatchNorm into conv2 without approximation."""
    baseline = baseline.cpu().eval()
    fused = FusedSCI().eval()
    with torch.no_grad():
        fused.conv1.load_state_dict(baseline.conv1.state_dict())
        fused.conv3.load_state_dict(baseline.conv3.state_dict())

        conv = baseline.conv2
        bn = baseline.bn2
        scale = bn.weight / torch.sqrt(bn.running_var + bn.eps)
        fused.conv2.weight.copy_(conv.weight * scale.reshape(-1, 1, 1, 1))
        fused.conv2.bias.copy_(bn.bias + (conv.bias - bn.running_mean) * scale)
    return fused
