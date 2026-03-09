"""Feed-Forward Network (FFN) block with BitDistill modifications.

Implements the SwiGLU-style gated FFN used in Qwen 3.5 with SubLN
inserted immediately before the down projection to stabilize ternary states.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from bitdistill.quantization.bitlinear import BitLinear
from bitdistill.modules.subln import SubLayerNorm


class BitDistillFFN(nn.Module):
    """Gated FFN (SwiGLU) with BitLinear and SubLN.

    Architecture: gate_proj * silu(up_proj) -> SubLN -> down_proj

    Args:
        hidden_size: Model hidden dimension.
        intermediate_size: FFN intermediate (expanded) dimension.
        use_bitlinear: Whether to use BitLinear (True for student).
        eps: Numerical stability constant.
    """

    def __init__(
        self,
        hidden_size: int = 2560,
        intermediate_size: int = 9216,
        use_bitlinear: bool = True,
        eps: float = 1e-8,
    ):
        super().__init__()
        LinearClass = BitLinear if use_bitlinear else nn.Linear

        self.up_proj = LinearClass(hidden_size, intermediate_size, bias=False)
        self.gate_proj = LinearClass(hidden_size, intermediate_size, bias=False)
        self.down_proj = LinearClass(intermediate_size, hidden_size, bias=False)

        # SubLN before down projection (critical for BitDistill)
        self.sub_ln = SubLayerNorm(intermediate_size, eps=eps)

        # Pre-normalization
        self.input_norm = RMSNorm(hidden_size, eps=eps)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass through gated FFN.

        Args:
            x: Input tensor of shape (batch, seq_len, hidden_size).

        Returns:
            Output tensor of shape (batch, seq_len, hidden_size).
        """
        residual = x
        x = self.input_norm(x)

        # SwiGLU: gate * silu(up)
        gate = self.gate_proj(x)
        up = self.up_proj(x)
        hidden = F.silu(gate) * up

        # SubLN before down projection
        hidden = self.sub_ln(hidden)

        # Down projection
        output = self.down_proj(hidden)

        return residual + output


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization."""

    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        variance = x.pow(2).mean(dim=-1, keepdim=True)
        x = x * torch.rsqrt(variance + self.eps)
        return x * self.weight
