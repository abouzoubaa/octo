"""Combined Dual-Objective Distillation Loss for BitDistill.

Composes Logit Distillation (LD) and Attention/State Distillation (AD)
into a single training objective:

    L_total = alpha_logit * L_LD + alpha_attention * L_AD

For the Qwen 3.5 hybrid architecture:
- L_AD uses KL divergence on attention maps for Gated Attention layers (25%)
- L_AD uses MSE on hidden states for GDN layers (75%)
"""

from __future__ import annotations

from typing import Optional

import torch
import torch.nn as nn

from bitdistill.distillation.logit_distill import LogitDistillationLoss
from bitdistill.distillation.attention_distill import (
    AttentionDistillationLoss,
    GDNStateDistillationLoss,
)
from bitdistill.config import DistillationConfig, LayerType


class DualObjectiveDistillationLoss(nn.Module):
    """Combined logit and attention/state distillation loss.

    Args:
        config: Distillation configuration.
    """

    def __init__(self, config: Optional[DistillationConfig] = None):
        super().__init__()
        self.config = config or DistillationConfig()

        # Logit distillation
        self.logit_loss = LogitDistillationLoss(
            temperature=self.config.temperature
        )

        # Attention distillation (for Gated Attention layers)
        self.attention_loss = AttentionDistillationLoss(
            num_heads=self.config.num_distill_heads
        )

        # GDN state distillation (for Gated Delta Network layers)
        self.gdn_state_loss = GDNStateDistillationLoss(normalize=True)

        # Loss weights
        self.alpha_logit = self.config.alpha_logit
        self.alpha_attention = self.config.alpha_attention

    def forward(
        self,
        student_logits: torch.Tensor,
        teacher_logits: torch.Tensor,
        student_attentions: Optional[dict[int, torch.Tensor]] = None,
        teacher_attentions: Optional[dict[int, torch.Tensor]] = None,
        student_gdn_states: Optional[dict[int, torch.Tensor]] = None,
        teacher_gdn_states: Optional[dict[int, torch.Tensor]] = None,
        layer_types: Optional[dict[int, LayerType]] = None,
        aux_loss: Optional[torch.Tensor] = None,
    ) -> dict[str, torch.Tensor]:
        """Compute the combined dual-objective loss.

        Args:
            student_logits: Student model output logits.
            teacher_logits: Teacher model output logits (frozen).
            student_attentions: Dict mapping layer_idx to student attention weights.
            teacher_attentions: Dict mapping layer_idx to teacher attention weights.
            student_gdn_states: Dict mapping layer_idx to student GDN hidden states.
            teacher_gdn_states: Dict mapping layer_idx to teacher GDN hidden states.
            layer_types: Dict mapping layer_idx to LayerType.
            aux_loss: MoE auxiliary load-balancing loss.

        Returns:
            Dict with 'total', 'logit', 'attention', 'gdn_state', 'aux' losses.
        """
        losses = {}

        # 1. Logit Distillation Loss
        l_ld = self.logit_loss(student_logits, teacher_logits)
        losses["logit"] = l_ld

        # 2. Attention / GDN State Distillation Loss
        l_ad = torch.tensor(0.0, device=student_logits.device)
        attn_count = 0

        if student_attentions and teacher_attentions:
            for layer_idx in student_attentions:
                if layer_idx not in teacher_attentions:
                    continue

                layer_type = (
                    layer_types.get(layer_idx, LayerType.GATED_ATTENTION)
                    if layer_types
                    else LayerType.GATED_ATTENTION
                )

                if layer_type == LayerType.GATED_ATTENTION:
                    # Standard relational distillation for attention layers
                    l_ad = l_ad + self.attention_loss(
                        student_attentions[layer_idx],
                        teacher_attentions[layer_idx],
                    )
                    attn_count += 1

        if student_gdn_states and teacher_gdn_states:
            for layer_idx in student_gdn_states:
                if layer_idx not in teacher_gdn_states:
                    continue
                # MSE state distillation for GDN layers
                l_ad = l_ad + self.gdn_state_loss(
                    student_gdn_states[layer_idx],
                    teacher_gdn_states[layer_idx],
                )
                attn_count += 1

        if attn_count > 0:
            l_ad = l_ad / attn_count

        losses["attention"] = l_ad

        # 3. Combined loss
        total = self.alpha_logit * l_ld + self.alpha_attention * l_ad

        # 4. Add MoE auxiliary loss if present
        if aux_loss is not None:
            losses["aux"] = aux_loss
            total = total + aux_loss

        losses["total"] = total
        return losses
