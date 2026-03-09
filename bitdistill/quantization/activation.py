"""INT8 activation quantization for BitDistill (W1.58A8 scheme).

Activations are quantized to 8-bit integers using per-token absmax scaling
to preserve outlier features critical for model performance.
"""

from __future__ import annotations

import torch


class STEActivationQuantize(torch.autograd.Function):
    """Quantize activations to INT8 with STE gradient passthrough."""

    @staticmethod
    def forward(
        ctx, x: torch.Tensor, eps: float = 1e-8
    ) -> torch.Tensor:
        # Per-token absmax: compute max absolute value along feature dim
        # x shape: (batch, seq_len, hidden_dim) or (batch, hidden_dim)
        if x.dim() >= 2:
            gamma = x.abs().amax(dim=-1, keepdim=True)
        else:
            gamma = x.abs().max()

        # Scale to INT8 range [-128, 127]
        scale = 127.0 / (gamma + eps)
        x_scaled = x * scale
        # Round and clip to INT8 range
        x_int8 = torch.clamp(torch.round(x_scaled), -128, 127)
        # Dequantize back to float for subsequent computation
        x_deq = x_int8 / scale

        return x_deq

    @staticmethod
    def backward(ctx, grad_output: torch.Tensor) -> tuple[torch.Tensor, None]:
        # STE: pass gradient through unchanged
        return grad_output, None


def quantize_activations_int8(
    x: torch.Tensor, eps: float = 1e-8
) -> torch.Tensor:
    """Quantize activation tensor to INT8 using per-token absmax scaling.

    Q_INT8(X) = (127/gamma) * RoundClip((gamma/127) * X, -128, 127)

    where gamma = max(|X|) computed per-token.

    Args:
        x: Activation tensor in full precision.
        eps: Numerical stability constant.

    Returns:
        Dequantized activation tensor (simulated INT8).
    """
    return STEActivationQuantize.apply(x, eps)
