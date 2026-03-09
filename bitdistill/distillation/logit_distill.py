"""Logit Distillation Loss for BitDistill.

Implements temperature-scaled Kullback-Leibler (KL) Divergence to transfer
output token probability distributions from the FP16 teacher to the
1.58-bit student.

L_LD = (1/N) * sum KL(P_teacher(y|x) || P_student(y|x))

Temperature scaling enriches "dark knowledge" by softening the distribution,
allowing the student to learn relative probabilities of incorrect tokens
which encode grammatical and semantic relationships.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class LogitDistillationLoss(nn.Module):
    """Temperature-scaled KL Divergence for logit distillation.

    Args:
        temperature: Temperature scalar for softening distributions.
            Higher = softer distributions, more "dark knowledge".
            Recommended: 2.0 for BitDistill.
        reduction: Loss reduction method ('mean' or 'sum').
    """

    def __init__(self, temperature: float = 2.0, reduction: str = "mean"):
        super().__init__()
        self.temperature = temperature
        self.reduction = reduction

    def forward(
        self,
        student_logits: torch.Tensor,
        teacher_logits: torch.Tensor,
    ) -> torch.Tensor:
        """Compute temperature-scaled KL divergence loss.

        Args:
            student_logits: Raw logits from student model (batch, seq, vocab).
            teacher_logits: Raw logits from teacher model (batch, seq, vocab).

        Returns:
            Scalar KL divergence loss.
        """
        # Temperature-scaled softmax: P(y|x) = softmax(z/tau)
        student_log_probs = F.log_softmax(
            student_logits / self.temperature, dim=-1
        )
        teacher_probs = F.softmax(
            teacher_logits / self.temperature, dim=-1
        )

        # KL divergence: KL(P_teacher || P_student)
        # F.kl_div expects log-probabilities as input and probabilities as target
        kl_loss = F.kl_div(
            student_log_probs,
            teacher_probs,
            reduction="batchmean",
            log_target=False,
        )

        # Scale by T^2 to ensure gradients are properly weighted
        # (standard practice in knowledge distillation)
        kl_loss = kl_loss * (self.temperature ** 2)

        return kl_loss
