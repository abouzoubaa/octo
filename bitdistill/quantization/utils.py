"""Core quantization primitives for BitDistill.

Implements:
- Straight-Through Estimator (STE) for gradient flow through rounding
- Absmean ternary weight quantization to {-1, 0, 1}
- RoundClip function for bounded integer rounding
"""

from __future__ import annotations

import torch
import torch.nn as nn


class STERound(torch.autograd.Function):
    """Straight-Through Estimator for the rounding operation.

    During the forward pass, this performs standard rounding.
    During the backward pass, the gradient passes through unchanged
    (identity function), enabling gradient flow through the
    non-differentiable rounding operation.
    """

    @staticmethod
    def forward(ctx, x: torch.Tensor) -> torch.Tensor:
        return torch.round(x)

    @staticmethod
    def backward(ctx, grad_output: torch.Tensor) -> torch.Tensor:
        # STE: treat gradient of round() as identity
        return grad_output


def ste_round(x: torch.Tensor) -> torch.Tensor:
    """Apply rounding with Straight-Through Estimator."""
    return STERound.apply(x)


def round_clip(
    x: torch.Tensor, min_val: float = -1.0, max_val: float = 1.0
) -> torch.Tensor:
    """Round and clip tensor values to [min_val, max_val].

    RoundClip(Y, a, b) = clamp(round(Y), a, b)
    Uses STE for differentiable rounding.
    """
    return torch.clamp(ste_round(x), min_val, max_val)


def absmean_quantize_weights(
    w: torch.Tensor, eps: float = 1e-8
) -> tuple[torch.Tensor, torch.Tensor]:
    """Quantize weights to ternary {-1, 0, 1} using absmean scaling.

    Q_w(W) = delta * RoundClip(W / (delta + eps), -1, 1)

    where delta = mean(|W|) is the per-tensor absolute mean.

    Args:
        w: Weight tensor in full precision (FP16/FP32).
        eps: Small constant for numerical stability.

    Returns:
        Tuple of (quantized_weights, scale_factor).
        quantized_weights has values in {-delta, 0, +delta}.
        scale_factor is the absmean value delta.
    """
    # Per-tensor absolute mean scaling factor
    delta = w.abs().mean()
    # Scale, round to nearest integer, clip to [-1, 1]
    w_scaled = w / (delta + eps)
    w_ternary = round_clip(w_scaled, -1.0, 1.0)
    # Scale back by delta
    w_quantized = delta * w_ternary
    return w_quantized, delta


def compute_weight_ternary_codes(
    w: torch.Tensor, eps: float = 1e-8
) -> torch.Tensor:
    """Return raw ternary codes {-1, 0, 1} without scaling.

    Useful for hardware-optimized inference where integer
    additions replace floating-point multiplications.
    """
    delta = w.abs().mean()
    w_scaled = w / (delta + eps)
    return round_clip(w_scaled, -1.0, 1.0)
