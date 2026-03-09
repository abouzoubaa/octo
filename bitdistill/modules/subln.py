"""Sub-Layer Normalization (SubLN) for BitDistill.

SubLN is inserted immediately before the final output projections within
attention, GDN, and FFN blocks. It re-centers and scales high-variance
outputs from ternary matrix multiplications before they are added to the
residual stream, preventing catastrophic numerical overflow in W1.58A8.

Standard transformer topology:
    Y = X + SelfAttention(LN(X))

With SubLN:
    Y = X + SubLN(SelfAttention(LN(X)))
"""

from __future__ import annotations

import torch
import torch.nn as nn


class SubLayerNorm(nn.Module):
    """Sub-Layer Normalization module.

    Applied immediately before output projections to stabilize
    discrete ternary-driven hidden states. Uses RMSNorm formulation
    for compatibility with Qwen 3.5 architecture.

    Args:
        dim: Hidden dimension size.
        eps: Numerical stability constant.
    """

    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.dim = dim
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def _rms_norm(self, x: torch.Tensor) -> torch.Tensor:
        variance = x.pow(2).mean(dim=-1, keepdim=True)
        return x * torch.rsqrt(variance + self.eps)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Apply SubLN normalization.

        Args:
            x: Input tensor of shape (..., dim).

        Returns:
            Normalized tensor of same shape.
        """
        return self._rms_norm(x.float()).type_as(x) * self.weight

    def extra_repr(self) -> str:
        return f"dim={self.dim}, eps={self.eps}"
