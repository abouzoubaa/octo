"""Stage 3: Distillation Trainer for BitDistill.

Implements the dual-objective knowledge distillation training loop
using a frozen FP16 teacher model to supervise the 1.58-bit student.

For Qwen 3.5 hybrid architecture:
- Gated Attention layers (25%): Relational distillation via KL on attention maps
- Gated Delta Net layers (75%): State distillation via MSE on hidden states
- MoE variants: Includes auxiliary load-balancing loss
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from bitdistill.config import BitDistillConfig, LayerType
from bitdistill.distillation.loss import DualObjectiveDistillationLoss
from bitdistill.training.scheduler import BitDistillScheduler

logger = logging.getLogger(__name__)


class DistillationTrainer:
    """BitDistill Stage 3 distillation trainer.

    Uses a frozen FP16 teacher to supervise the 1.58-bit student
    through dual-objective loss (logit + attention/state distillation).

    Args:
        config: BitDistill configuration.
        student: Student model (1.58-bit, topology-converted and warmed up).
        teacher: Teacher model (frozen FP16).
        tokenizer: Tokenizer for the models.
    """

    def __init__(
        self,
        config: BitDistillConfig,
        student: nn.Module,
        teacher: nn.Module,
        tokenizer: Optional[object] = None,
    ):
        self.config = config
        self.student = student
        self.teacher = teacher
        self.tokenizer = tokenizer
        self.device = next(student.parameters()).device

        # Freeze teacher completely
        self.teacher.eval()
        for param in self.teacher.parameters():
            param.requires_grad = False

        # Move teacher to device
        self.teacher = self.teacher.to(self.device)

        # Distillation loss
        self.criterion = DualObjectiveDistillationLoss(config.distillation)

        # Optimizer
        self.optimizer = self._create_optimizer()
        self.scheduler = BitDistillScheduler(
            optimizer=self.optimizer,
            max_lr=config.training.max_lr,
            min_lr=config.training.min_lr,
            warmup_steps=config.training.warmup_steps,
            total_steps=config.training.distill_steps,
        )

        # Build layer type mapping
        self.layer_types = self._build_layer_type_map()

        # Freeze vision tower on student
        self._freeze_vision_tower()

    def _create_optimizer(self) -> torch.optim.AdamW:
        """Create AdamW optimizer with BitDistill hyperparameters."""
        tc = self.config.training
        return torch.optim.AdamW(
            filter(lambda p: p.requires_grad, self.student.parameters()),
            lr=tc.max_lr,
            betas=(tc.beta1, tc.beta2),
            eps=tc.eps,
            weight_decay=tc.weight_decay,
        )

    def _freeze_vision_tower(self) -> None:
        """Freeze vision encoder in student model."""
        for name, param in self.student.named_parameters():
            name_lower = name.lower()
            if any(
                p in name_lower
                for p in ["visual", "vision", "vit", "projector"]
            ):
                param.requires_grad = False

    def _build_layer_type_map(self) -> dict[int, LayerType]:
        """Build mapping from layer index to layer type."""
        layer_types = {}
        for i in range(self.config.model.num_layers):
            layer_types[i] = self.config.model.get_layer_type(i)
        return layer_types

    def _extract_internal_states(
        self, model: nn.Module
    ) -> tuple[dict[int, torch.Tensor], dict[int, torch.Tensor]]:
        """Extract attention weights and GDN states from model.

        Walks through model modules to find stored attention weights
        and GDN hidden states (stored during forward pass).

        Returns:
            Tuple of (attention_weights_dict, gdn_states_dict).
        """
        attentions = {}
        gdn_states = {}
        layer_idx = 0

        for name, module in model.named_modules():
            if hasattr(module, "get_attention_weights"):
                attn_w = module.get_attention_weights()
                if attn_w is not None:
                    attentions[layer_idx] = attn_w
                    layer_idx += 1
            elif hasattr(module, "get_hidden_state"):
                state = module.get_hidden_state()
                if state is not None:
                    gdn_states[layer_idx] = state
                    layer_idx += 1

        return attentions, gdn_states

    def _forward_with_states(
        self,
        model: nn.Module,
        input_ids: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
    ) -> tuple[torch.Tensor, dict[int, torch.Tensor], dict[int, torch.Tensor]]:
        """Run forward pass and extract internal states.

        Args:
            model: Model to run forward pass on.
            input_ids: Input token IDs.
            attention_mask: Optional attention mask.

        Returns:
            Tuple of (logits, attention_weights, gdn_states).
        """
        outputs = model(
            input_ids=input_ids,
            attention_mask=attention_mask,
        )

        # Get logits
        if isinstance(outputs, dict):
            logits = outputs.get("logits", outputs.get("last_hidden_state"))
        elif hasattr(outputs, "logits"):
            logits = outputs.logits
        elif isinstance(outputs, (tuple, list)):
            logits = outputs[0]
        else:
            logits = outputs

        # Extract internal states
        attentions, gdn_states = self._extract_internal_states(model)

        return logits, attentions, gdn_states

    def train(
        self,
        train_dataloader: DataLoader,
        eval_dataloader: Optional[DataLoader] = None,
    ) -> dict[str, list[float]]:
        """Run Stage 3 distillation training loop.

        Args:
            train_dataloader: DataLoader for distillation data.
            eval_dataloader: Optional validation DataLoader.

        Returns:
            Dict with training metrics history.
        """
        tc = self.config.training
        self.student.train()
        self.teacher.eval()

        history = {
            "total_loss": [], "logit_loss": [],
            "attention_loss": [], "lr": [],
        }
        global_step = 0
        accumulated_losses = {"total": 0.0, "logit": 0.0, "attention": 0.0}

        logger.info(
            f"Starting distillation training for {tc.distill_steps} steps"
        )

        while global_step < tc.distill_steps:
            for batch in train_dataloader:
                if global_step >= tc.distill_steps:
                    break

                input_ids = batch["input_ids"].to(self.device)
                attention_mask = batch.get("attention_mask")
                if attention_mask is not None:
                    attention_mask = attention_mask.to(self.device)

                # Teacher forward pass (no gradients)
                with torch.no_grad():
                    teacher_logits, teacher_attns, teacher_gdn = (
                        self._forward_with_states(
                            self.teacher, input_ids, attention_mask
                        )
                    )

                # Student forward pass
                student_logits, student_attns, student_gdn = (
                    self._forward_with_states(
                        self.student, input_ids, attention_mask
                    )
                )

                # Collect MoE auxiliary loss if present
                aux_loss = self._collect_aux_loss(self.student)

                # Compute dual-objective loss
                losses = self.criterion(
                    student_logits=student_logits,
                    teacher_logits=teacher_logits,
                    student_attentions=student_attns,
                    teacher_attentions=teacher_attns,
                    student_gdn_states=student_gdn,
                    teacher_gdn_states=teacher_gdn,
                    layer_types=self.layer_types,
                    aux_loss=aux_loss,
                )

                loss = losses["total"] / tc.gradient_accumulation_steps
                loss.backward()

                accumulated_losses["total"] += losses["total"].item()
                accumulated_losses["logit"] += losses["logit"].item()
                accumulated_losses["attention"] += losses["attention"].item()

                if (global_step + 1) % tc.gradient_accumulation_steps == 0:
                    torch.nn.utils.clip_grad_norm_(
                        self.student.parameters(), tc.max_grad_norm
                    )
                    self.optimizer.step()
                    self.scheduler.step()
                    self.optimizer.zero_grad()

                global_step += 1

                # Logging
                if global_step % tc.logging_steps == 0:
                    n = tc.logging_steps
                    current_lr = self.scheduler.get_lr()

                    history["total_loss"].append(accumulated_losses["total"] / n)
                    history["logit_loss"].append(accumulated_losses["logit"] / n)
                    history["attention_loss"].append(
                        accumulated_losses["attention"] / n
                    )
                    history["lr"].append(current_lr)

                    logger.info(
                        f"Step {global_step}/{tc.distill_steps} | "
                        f"Total: {accumulated_losses['total'] / n:.4f} | "
                        f"Logit: {accumulated_losses['logit'] / n:.4f} | "
                        f"Attn: {accumulated_losses['attention'] / n:.4f} | "
                        f"LR: {current_lr:.2e}"
                    )
                    accumulated_losses = {
                        "total": 0.0, "logit": 0.0, "attention": 0.0,
                    }

                # Evaluation
                if eval_dataloader and global_step % tc.eval_steps == 0:
                    eval_metrics = self._evaluate(eval_dataloader)
                    logger.info(
                        f"Step {global_step} | "
                        f"Eval Total: {eval_metrics['total']:.4f} | "
                        f"Eval Logit: {eval_metrics['logit']:.4f}"
                    )
                    self.student.train()

                # Checkpointing
                if global_step % tc.save_steps == 0:
                    self._save_checkpoint(global_step)

        logger.info("Distillation training complete")
        return history

    def _collect_aux_loss(self, model: nn.Module) -> Optional[torch.Tensor]:
        """Collect MoE auxiliary losses from all MoE layers."""
        aux_losses = []
        for module in model.modules():
            if hasattr(module, "_aux_loss") and module._aux_loss is not None:
                aux_losses.append(module._aux_loss)
        if aux_losses:
            return sum(aux_losses) / len(aux_losses)
        return None

    @torch.no_grad()
    def _evaluate(self, dataloader: DataLoader) -> dict[str, float]:
        """Run evaluation loop."""
        self.student.eval()
        total_losses = {"total": 0.0, "logit": 0.0, "attention": 0.0}
        num_batches = 0

        for batch in dataloader:
            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch.get("attention_mask")
            if attention_mask is not None:
                attention_mask = attention_mask.to(self.device)

            teacher_logits, teacher_attns, teacher_gdn = (
                self._forward_with_states(
                    self.teacher, input_ids, attention_mask
                )
            )
            student_logits, student_attns, student_gdn = (
                self._forward_with_states(
                    self.student, input_ids, attention_mask
                )
            )

            losses = self.criterion(
                student_logits=student_logits,
                teacher_logits=teacher_logits,
                student_attentions=student_attns,
                teacher_attentions=teacher_attns,
                student_gdn_states=student_gdn,
                teacher_gdn_states=teacher_gdn,
                layer_types=self.layer_types,
            )

            total_losses["total"] += losses["total"].item()
            total_losses["logit"] += losses["logit"].item()
            total_losses["attention"] += losses["attention"].item()
            num_batches += 1

        return {k: v / max(num_batches, 1) for k, v in total_losses.items()}

    def _save_checkpoint(self, step: int) -> None:
        """Save training checkpoint."""
        checkpoint_dir = os.path.join(
            self.config.output_dir, f"distill_checkpoint_{step}"
        )
        os.makedirs(checkpoint_dir, exist_ok=True)
        torch.save(
            {
                "step": step,
                "student_state_dict": self.student.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "scheduler_state_dict": self.scheduler.state_dict(),
            },
            os.path.join(checkpoint_dir, "checkpoint.pt"),
        )
        logger.info(f"Saved distillation checkpoint at step {step}")
