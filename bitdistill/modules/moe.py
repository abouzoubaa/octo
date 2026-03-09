"""Mixture-of-Experts (MoE) module with selective quantization.

Implements the Sparse-BitNet strategy for Qwen 3.5 MoE variants:
- Expert FFN networks: Quantized to 1.58-bit (BitLinear)
- MoE router/gating: Preserved in FP16 (NEVER quantized to avoid collapse)
- Attention layers: Optionally in 4-bit/6-bit for semantic fidelity

Quantizing the router to 1.58-bit causes catastrophic routing collapse
where tokens are distributed uniformly or to a single dead expert.
"""

from __future__ import annotations

from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from bitdistill.quantization.bitlinear import BitLinear
from bitdistill.modules.subln import SubLayerNorm


class BitDistillExpert(nn.Module):
    """Single MoE expert with BitLinear quantization and SubLN.

    Uses SwiGLU FFN architecture with ternary-quantized weights.
    SubLN is placed before the final down projection.

    Args:
        hidden_size: Model hidden dimension.
        intermediate_size: Expert intermediate dimension.
        use_bitlinear: Whether to quantize to 1.58-bit.
        eps: Numerical stability constant.
    """

    def __init__(
        self,
        hidden_size: int,
        intermediate_size: int,
        use_bitlinear: bool = True,
        eps: float = 1e-8,
    ):
        super().__init__()
        LinearClass = BitLinear if use_bitlinear else nn.Linear

        # w1 (gate), w2 (down), w3 (up) - standard MoE naming
        self.w1 = LinearClass(hidden_size, intermediate_size, bias=False)  # gate
        self.w2 = LinearClass(intermediate_size, hidden_size, bias=False)  # down
        self.w3 = LinearClass(hidden_size, intermediate_size, bias=False)  # up

        # SubLN before down projection (w2)
        self.sub_ln = SubLayerNorm(intermediate_size, eps=eps)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass through expert.

        Args:
            x: Input tensor of shape (..., hidden_size).

        Returns:
            Output tensor of shape (..., hidden_size).
        """
        # SwiGLU: gate * silu(up)
        gate = self.w1(x)
        up = self.w3(x)
        hidden = F.silu(gate) * up

        # SubLN before down projection
        hidden = self.sub_ln(hidden)

        return self.w2(hidden)


class MoERouter(nn.Module):
    """MoE routing/gating network - ALWAYS kept in FP16.

    The router must maintain continuous precision for contextually-aware
    expert assignment. Quantizing to 1.58-bit causes routing collapse.

    Uses top-k selection with load-balancing auxiliary loss.

    Args:
        hidden_size: Model hidden dimension.
        num_experts: Total number of experts.
        num_active_experts: Number of experts activated per token (top-k).
        aux_loss_coeff: Coefficient for load-balancing auxiliary loss.
    """

    def __init__(
        self,
        hidden_size: int,
        num_experts: int,
        num_active_experts: int = 2,
        aux_loss_coeff: float = 0.01,
    ):
        super().__init__()
        self.num_experts = num_experts
        self.num_active_experts = num_active_experts
        self.aux_loss_coeff = aux_loss_coeff

        # Router gate - ALWAYS nn.Linear (FP16), never BitLinear
        self.gate = nn.Linear(hidden_size, num_experts, bias=False)

    def forward(
        self, x: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, Optional[torch.Tensor]]:
        """Route tokens to top-k experts.

        Args:
            x: Input tensor of shape (batch * seq_len, hidden_size).

        Returns:
            Tuple of (router_weights, selected_experts, aux_loss).
            router_weights: Softmax probabilities for selected experts.
            selected_experts: Indices of selected experts.
            aux_loss: Load-balancing auxiliary loss (None during eval).
        """
        # Compute routing logits (in FP16)
        logits = self.gate(x.to(self.gate.weight.dtype))
        router_probs = F.softmax(logits, dim=-1)

        # Select top-k experts
        router_weights, selected_experts = torch.topk(
            router_probs, self.num_active_experts, dim=-1
        )
        # Normalize selected weights to sum to 1
        router_weights = router_weights / router_weights.sum(dim=-1, keepdim=True)

        # Load-balancing auxiliary loss
        aux_loss = None
        if self.training:
            aux_loss = self._compute_aux_loss(router_probs, selected_experts)

        return router_weights, selected_experts, aux_loss

    def _compute_aux_loss(
        self, router_probs: torch.Tensor, selected_experts: torch.Tensor
    ) -> torch.Tensor:
        """Compute load-balancing auxiliary loss.

        Encourages uniform expert utilization to prevent expert collapse.
        """
        num_tokens = router_probs.shape[0]

        # Fraction of tokens routed to each expert
        expert_mask = F.one_hot(selected_experts, self.num_experts).float()
        expert_mask = expert_mask.sum(dim=1)  # Sum over top-k
        tokens_per_expert = expert_mask.sum(dim=0) / num_tokens

        # Average routing probability per expert
        avg_probs = router_probs.mean(dim=0)

        # Auxiliary loss: dot product encourages uniform distribution
        aux_loss = self.num_experts * (tokens_per_expert * avg_probs).sum()
        return self.aux_loss_coeff * aux_loss


class BitDistillMoE(nn.Module):
    """Mixture-of-Experts layer with selective quantization.

    Expert networks are quantized to 1.58-bit while the router
    is strictly preserved in FP16.

    Args:
        hidden_size: Model hidden dimension.
        intermediate_size: Expert intermediate dimension.
        num_experts: Total number of experts.
        num_active_experts: Top-k experts per token.
        use_bitlinear: Whether to quantize expert weights.
        eps: Numerical stability constant.
    """

    def __init__(
        self,
        hidden_size: int,
        intermediate_size: int,
        num_experts: int = 16,
        num_active_experts: int = 2,
        use_bitlinear: bool = True,
        eps: float = 1e-8,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_experts = num_experts
        self.num_active_experts = num_active_experts

        # Router - ALWAYS FP16
        self.router = MoERouter(hidden_size, num_experts, num_active_experts)

        # Expert networks - quantized to 1.58-bit
        self.experts = nn.ModuleList([
            BitDistillExpert(
                hidden_size, intermediate_size,
                use_bitlinear=use_bitlinear, eps=eps,
            )
            for _ in range(num_experts)
        ])

        # Pre-normalization
        self.input_norm = RMSNorm(hidden_size, eps=eps)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, Optional[torch.Tensor]]:
        """Forward pass through MoE layer.

        Args:
            x: Input tensor of shape (batch, seq_len, hidden_size).

        Returns:
            Tuple of (output, aux_loss).
        """
        batch, seq_len, hidden = x.shape
        residual = x
        x = self.input_norm(x)

        # Flatten for routing: (batch * seq_len, hidden)
        x_flat = x.reshape(-1, hidden)

        # Route tokens to experts
        router_weights, selected_experts, aux_loss = self.router(x_flat)

        # Compute expert outputs
        output = torch.zeros_like(x_flat)
        for expert_idx in range(self.num_experts):
            # Find tokens routed to this expert
            # selected_experts shape: (num_tokens, top_k)
            expert_mask = (selected_experts == expert_idx).any(dim=-1)
            if not expert_mask.any():
                continue

            # Get tokens for this expert
            expert_input = x_flat[expert_mask]
            expert_output = self.experts[expert_idx](expert_input)

            # Get routing weights for this expert
            weight_mask = (selected_experts[expert_mask] == expert_idx).float()
            expert_weights = (router_weights[expert_mask] * weight_mask).sum(dim=-1, keepdim=True)

            output[expert_mask] += expert_weights * expert_output

        output = output.reshape(batch, seq_len, hidden)
        return residual + output, aux_loss


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
