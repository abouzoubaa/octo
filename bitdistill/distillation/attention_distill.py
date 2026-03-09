"""Attention and GDN State Distillation Losses for BitDistill.

Two distillation objectives for internal representations:

1. AttentionDistillationLoss: For Gated Attention layers (25% of blocks).
   Uses KL divergence on the self-attention relational matrices R.
   R = softmax(QK^T / sqrt(d))

2. GDNStateDistillationLoss: For Gated Delta Network layers (75% of blocks).
   Uses MSE on the hidden memory states since QK^T attention maps are
   undefined for linear recurrence. This ensures the decay (alpha) and
   update (beta) gates of the student mimic the teacher's temporal
   state transitions.
"""

from __future__ import annotations

from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


class AttentionDistillationLoss(nn.Module):
    """Relational distillation for standard softmax attention layers.

    Minimizes the statistical divergence between the self-attention
    relation matrices of the teacher and student.

    Derived from MiniLM methodology.

    Args:
        reduction: Loss reduction method.
        num_heads: If specified, only distill from first N heads.
    """

    def __init__(
        self, reduction: str = "mean", num_heads: Optional[int] = None
    ):
        super().__init__()
        self.reduction = reduction
        self.num_heads = num_heads

    def forward(
        self,
        student_attention: torch.Tensor,
        teacher_attention: torch.Tensor,
    ) -> torch.Tensor:
        """Compute attention distribution divergence.

        Args:
            student_attention: Student attention weights
                shape (batch, heads, seq_len, seq_len).
            teacher_attention: Teacher attention weights
                shape (batch, heads, seq_len, seq_len).

        Returns:
            Scalar attention distillation loss.
        """
        # Optionally select subset of heads
        if self.num_heads is not None:
            student_attention = student_attention[:, : self.num_heads]
            teacher_attention = teacher_attention[:, : self.num_heads]

        # Handle potential head count mismatch between teacher/student
        min_heads = min(
            student_attention.shape[1], teacher_attention.shape[1]
        )
        student_attention = student_attention[:, :min_heads]
        teacher_attention = teacher_attention[:, :min_heads]

        # KL divergence on attention distributions
        # Attention weights are already probabilities (post-softmax)
        student_log = torch.log(student_attention + 1e-10)

        loss = F.kl_div(
            student_log.reshape(-1, student_log.shape[-1]),
            teacher_attention.reshape(-1, teacher_attention.shape[-1]),
            reduction="batchmean",
            log_target=False,
        )

        return loss


class GDNStateDistillationLoss(nn.Module):
    """Hidden state distillation for Gated Delta Network layers.

    Since GDN layers have no QK^T attention map, we distill the
    continuous memory state evaluations using MSE.

    L_AD = MSE(S_t^{FP16}, S_t^{1.58-bit})

    This ensures the decay (alpha) and update (beta) gates of the
    ternary student accurately mimic the teacher's temporal state
    transitions.

    Args:
        normalize: Whether to normalize states before comparison.
        reduction: Loss reduction method.
    """

    def __init__(self, normalize: bool = True, reduction: str = "mean"):
        super().__init__()
        self.normalize = normalize
        self.reduction = reduction

    def forward(
        self,
        student_states: torch.Tensor,
        teacher_states: torch.Tensor,
    ) -> torch.Tensor:
        """Compute MSE between GDN hidden memory states.

        Args:
            student_states: Student GDN hidden states
                shape (batch, num_heads, head_dim) or
                shape (batch, seq_len, num_heads, head_dim).
            teacher_states: Teacher GDN hidden states (same shape).

        Returns:
            Scalar state distillation loss.
        """
        if self.normalize:
            # L2 normalize states for scale-invariant comparison
            student_states = F.normalize(student_states.float(), dim=-1)
            teacher_states = F.normalize(teacher_states.float(), dim=-1)

        loss = F.mse_loss(
            student_states, teacher_states, reduction=self.reduction
        )

        return loss
