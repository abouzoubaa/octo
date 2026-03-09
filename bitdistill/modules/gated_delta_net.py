"""Gated Delta Network (GDN) block with BitDistill modifications.

The GDN operates as a linear-complexity recurrent alternative to softmax
attention. It compresses historical context into a fixed-size hidden memory
state S, achieving O(N) scaling for sequence modeling.

Key components:
- Decay gate (alpha): Controls rate of historical memory decay.
- Update gate (beta): Modulates how new tokens modify internal state.
- SubLN: Inserted before output projection to stabilize ternary states.

For distillation, this block exposes its hidden memory states for MSE-based
state distillation (since QK^T attention maps are undefined for GDN).
"""

from __future__ import annotations

from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from bitdistill.quantization.bitlinear import BitLinear
from bitdistill.modules.subln import SubLayerNorm


class GatedDeltaNetBlock(nn.Module):
    """Gated Delta Network sequence mixing block.

    Args:
        hidden_size: Model hidden dimension.
        num_v_heads: Number of attention heads for V projection (32 for 4B).
        num_qk_heads: Number of heads for QK projection (16 for 4B).
        head_dim: Dimension per head (128 for GDN in 4B).
        use_bitlinear: Whether to use BitLinear (True for student).
        eps: Numerical stability constant.
    """

    def __init__(
        self,
        hidden_size: int = 2560,
        num_v_heads: int = 32,
        num_qk_heads: int = 16,
        head_dim: int = 128,
        use_bitlinear: bool = True,
        eps: float = 1e-8,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_v_heads = num_v_heads
        self.num_qk_heads = num_qk_heads
        self.head_dim = head_dim

        LinearClass = BitLinear if use_bitlinear else nn.Linear

        # Projections
        self.q_proj = LinearClass(hidden_size, num_qk_heads * head_dim, bias=False)
        self.k_proj = LinearClass(hidden_size, num_qk_heads * head_dim, bias=False)
        self.v_proj = LinearClass(hidden_size, num_v_heads * head_dim, bias=False)
        self.o_proj = LinearClass(num_v_heads * head_dim, hidden_size, bias=False)

        # Gating projections for decay (alpha) and update (beta)
        self.decay_gate = LinearClass(hidden_size, num_v_heads * head_dim, bias=False)
        self.update_gate = LinearClass(hidden_size, num_v_heads * head_dim, bias=False)

        # SubLN before output projection (critical for BitDistill)
        self.sub_ln = SubLayerNorm(num_v_heads * head_dim, eps=eps)

        # Pre-normalization (RMSNorm)
        self.input_norm = RMSNorm(hidden_size, eps=eps)

        # Store hidden state for distillation
        self._hidden_state: Optional[torch.Tensor] = None

    def forward(
        self,
        x: torch.Tensor,
        prev_state: Optional[torch.Tensor] = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Forward pass through GDN block.

        Args:
            x: Input tensor of shape (batch, seq_len, hidden_size).
            prev_state: Previous hidden memory state.

        Returns:
            Tuple of (output, new_hidden_state).
        """
        batch, seq_len, _ = x.shape
        residual = x

        # Pre-normalization
        x = self.input_norm(x)

        # Compute projections
        q = self.q_proj(x)
        k = self.k_proj(x)
        v = self.v_proj(x)

        # Reshape for multi-head processing
        v = v.view(batch, seq_len, self.num_v_heads, self.head_dim)

        # Compute gating values
        alpha = torch.sigmoid(self.decay_gate(x))  # Decay gate
        beta = torch.sigmoid(self.update_gate(x))  # Update gate
        alpha = alpha.view(batch, seq_len, self.num_v_heads, self.head_dim)
        beta = beta.view(batch, seq_len, self.num_v_heads, self.head_dim)

        # Initialize state if needed
        if prev_state is None:
            state = torch.zeros(
                batch, self.num_v_heads, self.head_dim,
                device=x.device, dtype=x.dtype,
            )
        else:
            state = prev_state

        # Linear recurrence: S_t = alpha_t * S_{t-1} + beta_t * V_t
        outputs = []
        for t in range(seq_len):
            state = alpha[:, t] * state + beta[:, t] * v[:, t]
            outputs.append(state)

        # Stack temporal outputs
        output = torch.stack(outputs, dim=1)  # (batch, seq_len, heads, head_dim)

        # Store hidden state for distillation access
        self._hidden_state = state.detach()

        # Reshape back to hidden dimension
        output = output.reshape(batch, seq_len, -1)

        # SubLN before output projection (critical for ternary stability)
        output = self.sub_ln(output)

        # Output projection
        output = self.o_proj(output)

        # Residual connection
        output = residual + output

        return output, state

    def get_hidden_state(self) -> Optional[torch.Tensor]:
        """Return last hidden state for distillation."""
        return self._hidden_state


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
