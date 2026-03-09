"""Stage 2: Continual Quantization-Aware Pre-Training Warm-up.

This stage operates over a general text corpus (e.g., FALCON) to:
1. Allow the network to relearn internal representations with ternary weights
2. Align discrete weight states to broader linguistic distributions
3. Minimize the initial loss spike from FP16 -> 1.58-bit transition

Key details:
- Retains AdamW optimizer states from FP16 teacher to minimize transition shock
- Vision tower is FROZEN during warm-up (multimodal safety)
- Should include code-specific data for Qwen 3.5 models
- Does NOT use teacher distillation (that's Stage 3)
"""

from __future__ import annotations

import logging
from typing import Optional

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from bitdistill.config import BitDistillConfig
from bitdistill.training.scheduler import BitDistillScheduler

logger = logging.getLogger(__name__)


class WarmupPreTrainer:
    """Continual pre-training warm-up for BitDistill Stage 2.

    Warms up the quantized student model on a general text corpus
    before task-specific distillation begins.

    Args:
        config: BitDistill configuration.
        model: Student model (already topology-converted with BitLinear).
        tokenizer: Tokenizer for the model.
    """

    def __init__(
        self,
        config: BitDistillConfig,
        model: nn.Module,
        tokenizer: Optional[object] = None,
    ):
        self.config = config
        self.model = model
        self.tokenizer = tokenizer
        self.device = next(model.parameters()).device

        # Setup optimizer (AdamW with BitDistill hyperparameters)
        self.optimizer = self._create_optimizer()
        self.scheduler = BitDistillScheduler(
            optimizer=self.optimizer,
            max_lr=config.training.max_lr,
            min_lr=config.training.min_lr,
            warmup_steps=config.training.warmup_steps,
            total_steps=config.training.warmup_pretrain_steps,
        )

        # Freeze vision tower if present
        self._freeze_vision_tower()

    def _create_optimizer(self) -> torch.optim.AdamW:
        """Create AdamW optimizer with BitDistill hyperparameters."""
        tc = self.config.training
        return torch.optim.AdamW(
            filter(lambda p: p.requires_grad, self.model.parameters()),
            lr=tc.max_lr,
            betas=(tc.beta1, tc.beta2),
            eps=tc.eps,
            weight_decay=tc.weight_decay,
        )

    def _freeze_vision_tower(self) -> None:
        """Freeze vision encoder parameters during warm-up."""
        frozen_count = 0
        for name, param in self.model.named_parameters():
            name_lower = name.lower()
            if any(
                pattern in name_lower
                for pattern in ["visual", "vision", "vit", "projector"]
            ):
                param.requires_grad = False
                frozen_count += 1
        if frozen_count > 0:
            logger.info(f"Froze {frozen_count} vision tower parameters")

    def train(
        self,
        train_dataloader: DataLoader,
        eval_dataloader: Optional[DataLoader] = None,
    ) -> dict[str, list[float]]:
        """Run warm-up pre-training loop.

        Args:
            train_dataloader: DataLoader for warm-up corpus.
            eval_dataloader: Optional DataLoader for validation.

        Returns:
            Dict with training metrics history.
        """
        tc = self.config.training
        self.model.train()
        history = {"loss": [], "lr": [], "perplexity": []}
        global_step = 0
        accumulated_loss = 0.0

        logger.info(
            f"Starting warm-up pre-training for {tc.warmup_pretrain_steps} steps"
        )

        while global_step < tc.warmup_pretrain_steps:
            for batch in train_dataloader:
                if global_step >= tc.warmup_pretrain_steps:
                    break

                # Move batch to device
                input_ids = batch["input_ids"].to(self.device)
                attention_mask = batch.get("attention_mask")
                if attention_mask is not None:
                    attention_mask = attention_mask.to(self.device)
                labels = batch.get("labels", input_ids).to(self.device)

                # Forward pass with standard language modeling loss
                outputs = self.model(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    labels=labels,
                )

                # Handle different output formats
                if isinstance(outputs, dict):
                    loss = outputs["loss"]
                elif hasattr(outputs, "loss"):
                    loss = outputs.loss
                else:
                    loss = outputs[0]

                loss = loss / tc.gradient_accumulation_steps
                loss.backward()
                accumulated_loss += loss.item()

                if (global_step + 1) % tc.gradient_accumulation_steps == 0:
                    # Gradient clipping
                    torch.nn.utils.clip_grad_norm_(
                        self.model.parameters(), tc.max_grad_norm
                    )
                    self.optimizer.step()
                    self.scheduler.step()
                    self.optimizer.zero_grad()

                global_step += 1

                # Logging
                if global_step % tc.logging_steps == 0:
                    avg_loss = accumulated_loss / tc.logging_steps
                    perplexity = torch.exp(
                        torch.tensor(avg_loss * tc.gradient_accumulation_steps)
                    ).item()
                    current_lr = self.scheduler.get_lr()

                    history["loss"].append(avg_loss)
                    history["lr"].append(current_lr)
                    history["perplexity"].append(perplexity)

                    logger.info(
                        f"Step {global_step}/{tc.warmup_pretrain_steps} | "
                        f"Loss: {avg_loss:.4f} | "
                        f"PPL: {perplexity:.2f} | "
                        f"LR: {current_lr:.2e}"
                    )
                    accumulated_loss = 0.0

                # Evaluation
                if (
                    eval_dataloader
                    and global_step % tc.eval_steps == 0
                ):
                    eval_loss = self._evaluate(eval_dataloader)
                    logger.info(
                        f"Step {global_step} | Eval Loss: {eval_loss:.4f}"
                    )
                    self.model.train()

                # Checkpointing
                if global_step % tc.save_steps == 0:
                    self._save_checkpoint(global_step)

        logger.info("Warm-up pre-training complete")
        return history

    @torch.no_grad()
    def _evaluate(self, dataloader: DataLoader) -> float:
        """Run evaluation loop."""
        self.model.eval()
        total_loss = 0.0
        num_batches = 0

        for batch in dataloader:
            input_ids = batch["input_ids"].to(self.device)
            labels = batch.get("labels", input_ids).to(self.device)
            attention_mask = batch.get("attention_mask")
            if attention_mask is not None:
                attention_mask = attention_mask.to(self.device)

            outputs = self.model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                labels=labels,
            )

            if isinstance(outputs, dict):
                loss = outputs["loss"]
            elif hasattr(outputs, "loss"):
                loss = outputs.loss
            else:
                loss = outputs[0]

            total_loss += loss.item()
            num_batches += 1

        return total_loss / max(num_batches, 1)

    def _save_checkpoint(self, step: int) -> None:
        """Save training checkpoint."""
        import os

        checkpoint_dir = os.path.join(
            self.config.output_dir, f"warmup_checkpoint_{step}"
        )
        os.makedirs(checkpoint_dir, exist_ok=True)
        torch.save(
            {
                "step": step,
                "model_state_dict": self.model.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "scheduler_state_dict": self.scheduler.state_dict(),
            },
            os.path.join(checkpoint_dir, "checkpoint.pt"),
        )
        logger.info(f"Saved warm-up checkpoint at step {step}")
