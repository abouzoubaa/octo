"""Learning rate scheduler for BitDistill.

Implements linear decay schedule with warmup as specified by the
BitDistill protocol. The SubLN modules enable safe absorption of
the relatively high max learning rate (1e-4).
"""

from __future__ import annotations

import math

import torch
from torch.optim.lr_scheduler import LambdaLR


class BitDistillScheduler:
    """Linear decay learning rate scheduler with warmup.

    BitDistill mandates:
    - Max LR: 1e-4 (safely stabilized by SubLN)
    - Schedule: Linear decay throughout training
    - Warmup: Short linear warmup to max LR

    Args:
        optimizer: PyTorch optimizer (AdamW).
        max_lr: Maximum learning rate after warmup.
        min_lr: Minimum learning rate at end of training.
        warmup_steps: Number of linear warmup steps.
        total_steps: Total number of training steps.
    """

    def __init__(
        self,
        optimizer: torch.optim.Optimizer,
        max_lr: float = 1e-4,
        min_lr: float = 1e-6,
        warmup_steps: int = 500,
        total_steps: int = 20000,
    ):
        self.optimizer = optimizer
        self.max_lr = max_lr
        self.min_lr = min_lr
        self.warmup_steps = warmup_steps
        self.total_steps = total_steps
        self._step = 0

        # Set initial LR
        for param_group in optimizer.param_groups:
            param_group["lr"] = min_lr

        self.scheduler = LambdaLR(optimizer, lr_lambda=self._lr_lambda)

    def _lr_lambda(self, step: int) -> float:
        """Compute LR multiplier for a given step.

        Linear warmup from min_lr to max_lr, then linear decay back to min_lr.
        """
        if step < self.warmup_steps:
            # Linear warmup
            progress = step / max(self.warmup_steps, 1)
            return self.min_lr / self.max_lr + progress * (
                1.0 - self.min_lr / self.max_lr
            )
        else:
            # Linear decay from max_lr to min_lr
            decay_steps = self.total_steps - self.warmup_steps
            progress = (step - self.warmup_steps) / max(decay_steps, 1)
            progress = min(progress, 1.0)
            ratio = 1.0 - progress * (1.0 - self.min_lr / self.max_lr)
            return max(ratio, self.min_lr / self.max_lr)

    def step(self) -> None:
        """Advance scheduler by one step."""
        self._step += 1
        self.scheduler.step()

    def get_lr(self) -> float:
        """Return current learning rate."""
        return self.optimizer.param_groups[0]["lr"]

    def state_dict(self) -> dict:
        """Return scheduler state for checkpointing."""
        return {
            "step": self._step,
            "scheduler": self.scheduler.state_dict(),
        }

    def load_state_dict(self, state: dict) -> None:
        """Load scheduler state from checkpoint."""
        self._step = state["step"]
        self.scheduler.load_state_dict(state["scheduler"])
