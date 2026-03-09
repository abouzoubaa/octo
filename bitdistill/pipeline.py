"""BitDistill Pipeline Orchestrator.

Executes the complete 3-stage BitDistill pipeline:

Stage 1: Topological Modification
  - Replace nn.Linear -> BitLinear (1.58-bit ternary quantization)
  - Inject SubLN before output projections
  - Protect vision tower (FP16) and MoE router (FP16)

Stage 2: Continual Pre-Training Warm-up
  - Warm up ternary weights on general corpus
  - Freeze vision tower, use mixed text + image-caption data
  - Align discrete weight states to linguistic distributions

Stage 3: Dual-Objective Knowledge Distillation
  - Frozen FP16 teacher supervises 1.58-bit student
  - Logit distillation: Temperature-scaled KL divergence
  - Attention distillation: KL on attention maps (Gated Attention)
  - State distillation: MSE on hidden states (Gated Delta Networks)
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Optional

import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from bitdistill.config import BitDistillConfig, QWEN35_CONFIGS
from bitdistill.topology.converter import TopologyConverter
from bitdistill.training.warmup import WarmupPreTrainer
from bitdistill.training.trainer import DistillationTrainer

logger = logging.getLogger(__name__)


class BitDistillPipeline:
    """Complete BitDistill pipeline for Qwen 3.5 models.

    Orchestrates the 3-stage conversion from FP16 to 1.58-bit:
    1. Topology modification (BitLinear + SubLN)
    2. Warm-up pre-training
    3. Dual-objective distillation

    Args:
        config: BitDistill configuration.
    """

    def __init__(self, config: BitDistillConfig):
        self.config = config
        self.teacher: Optional[nn.Module] = None
        self.student: Optional[nn.Module] = None
        self.tokenizer: Optional[object] = None

    @classmethod
    def from_model_name(
        cls,
        model_name: str,
        teacher_model_path: str = "",
        output_dir: str = "./bitdistill_output",
        **kwargs,
    ) -> "BitDistillPipeline":
        """Create pipeline from a known Qwen 3.5 model variant.

        Args:
            model_name: One of the known model names (e.g., 'qwen3.5-4b').
            teacher_model_path: Path to the FP16 teacher model.
            output_dir: Output directory.

        Returns:
            Configured BitDistillPipeline.
        """
        if model_name not in QWEN35_CONFIGS:
            raise ValueError(
                f"Unknown model: {model_name}. "
                f"Available: {list(QWEN35_CONFIGS.keys())}"
            )

        config = BitDistillConfig(
            model=QWEN35_CONFIGS[model_name],
            teacher_model_path=teacher_model_path,
            output_dir=output_dir,
        )

        # Override any additional config values
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)

        return cls(config)

    def load_teacher(self, model: nn.Module) -> None:
        """Load the FP16 teacher model.

        The teacher is frozen and used for supervision during Stage 3.

        Args:
            model: Pre-trained FP16 model.
        """
        self.teacher = model
        self.teacher.eval()
        for param in self.teacher.parameters():
            param.requires_grad = False
        logger.info("Teacher model loaded and frozen")

    def load_teacher_from_pretrained(self, path: str) -> None:
        """Load teacher from a HuggingFace-style pretrained path.

        Requires the `transformers` library.

        Args:
            path: Model path or HuggingFace model ID.
        """
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer

            logger.info(f"Loading teacher model from: {path}")
            self.teacher = AutoModelForCausalLM.from_pretrained(
                path, torch_dtype=torch.float16, trust_remote_code=True
            )
            self.tokenizer = AutoTokenizer.from_pretrained(
                path, trust_remote_code=True
            )
            self.teacher.eval()
            for param in self.teacher.parameters():
                param.requires_grad = False
            logger.info("Teacher model and tokenizer loaded")
        except ImportError:
            raise ImportError(
                "The `transformers` library is required to load pretrained models. "
                "Install it with: pip install transformers"
            )

    def stage1_topology_modification(
        self,
        model: Optional[nn.Module] = None,
        protected_patterns: Optional[set[str]] = None,
    ) -> nn.Module:
        """Stage 1: Topological refinement via SubLN and BitLinear.

        Replaces nn.Linear with BitLinear and injects SubLN, while
        protecting vision tower and MoE router.

        Args:
            model: Model to convert. If None, copies from teacher.
            protected_patterns: Additional module patterns to protect.

        Returns:
            Topology-converted student model.
        """
        logger.info("=" * 60)
        logger.info("Stage 1: Topological Modification")
        logger.info("=" * 60)

        if model is None:
            if self.teacher is None:
                raise ValueError(
                    "No model provided and no teacher loaded. "
                    "Call load_teacher() first or pass a model."
                )
            # Deep copy teacher as starting point for student
            logger.info("Creating student from deep copy of teacher")
            model = copy.deepcopy(self.teacher)
            # Re-enable gradients on student
            for param in model.parameters():
                param.requires_grad = True

        # Convert topology
        converter = TopologyConverter(
            config=self.config.quantization,
            protected_patterns=protected_patterns,
        )
        self.student = converter.convert(model)

        # Log conversion statistics
        stats = converter.get_stats()
        logger.info(f"Conversion stats: {stats}")

        summary = TopologyConverter.get_quantization_summary(self.student)
        logger.info(
            f"Quantized parameters: {summary['quantized_params']:,} / "
            f"{summary['total_params']:,} total "
            f"({100 * summary['quantized_params'] / max(summary['total_params'], 1):.1f}%)"
        )
        logger.info(
            f"FP16 parameters: {summary['fp16_params']:,} "
            f"({100 * summary['fp16_params'] / max(summary['total_params'], 1):.1f}%)"
        )

        return self.student

    def stage2_warmup_pretraining(
        self,
        train_dataloader: DataLoader,
        eval_dataloader: Optional[DataLoader] = None,
    ) -> dict[str, list[float]]:
        """Stage 2: Continual pre-training warm-up.

        Warms up the ternary student on a general text corpus.
        Vision tower is frozen during this stage.

        Args:
            train_dataloader: DataLoader for warm-up corpus.
            eval_dataloader: Optional validation DataLoader.

        Returns:
            Training metrics history.
        """
        logger.info("=" * 60)
        logger.info("Stage 2: Continual Pre-Training Warm-up")
        logger.info("=" * 60)

        if self.student is None:
            raise ValueError(
                "Student model not initialized. Run stage1_topology_modification() first."
            )

        warmup_trainer = WarmupPreTrainer(
            config=self.config,
            model=self.student,
            tokenizer=self.tokenizer,
        )

        history = warmup_trainer.train(
            train_dataloader=train_dataloader,
            eval_dataloader=eval_dataloader,
        )

        return history

    def stage3_distillation(
        self,
        train_dataloader: DataLoader,
        eval_dataloader: Optional[DataLoader] = None,
    ) -> dict[str, list[float]]:
        """Stage 3: Dual-objective knowledge distillation.

        Uses frozen FP16 teacher to supervise 1.58-bit student through
        logit distillation and attention/state distillation.

        Args:
            train_dataloader: DataLoader for distillation data.
            eval_dataloader: Optional validation DataLoader.

        Returns:
            Training metrics history.
        """
        logger.info("=" * 60)
        logger.info("Stage 3: Dual-Objective Knowledge Distillation")
        logger.info("=" * 60)

        if self.student is None:
            raise ValueError(
                "Student model not initialized. Run stage1 and stage2 first."
            )
        if self.teacher is None:
            raise ValueError(
                "Teacher model not loaded. Call load_teacher() first."
            )

        distill_trainer = DistillationTrainer(
            config=self.config,
            student=self.student,
            teacher=self.teacher,
            tokenizer=self.tokenizer,
        )

        history = distill_trainer.train(
            train_dataloader=train_dataloader,
            eval_dataloader=eval_dataloader,
        )

        return history

    def run(
        self,
        warmup_dataloader: DataLoader,
        distill_dataloader: DataLoader,
        eval_dataloader: Optional[DataLoader] = None,
        model: Optional[nn.Module] = None,
    ) -> nn.Module:
        """Run the complete 3-stage BitDistill pipeline.

        Args:
            warmup_dataloader: DataLoader for Stage 2 warm-up corpus.
            distill_dataloader: DataLoader for Stage 3 distillation data.
            eval_dataloader: Optional validation DataLoader.
            model: Optional model to convert (uses teacher copy if None).

        Returns:
            Trained 1.58-bit student model.
        """
        logger.info("=" * 60)
        logger.info("BitDistill Pipeline - Full Execution")
        logger.info(f"Model: {self.config.model.model_name}")
        logger.info(f"Quantization: {self.config.quantization.scheme.value}")
        logger.info(f"MoE: {self.config.model.is_moe}")
        logger.info("=" * 60)

        # Stage 1: Topology Modification
        self.stage1_topology_modification(model=model)

        # Stage 2: Warm-up Pre-training
        self.stage2_warmup_pretraining(
            train_dataloader=warmup_dataloader,
            eval_dataloader=eval_dataloader,
        )

        # Stage 3: Distillation
        self.stage3_distillation(
            train_dataloader=distill_dataloader,
            eval_dataloader=eval_dataloader,
        )

        # Save final model
        self.save_student()

        return self.student

    def save_student(self, path: Optional[str] = None) -> None:
        """Save the distilled student model.

        Args:
            path: Output path. Defaults to config.output_dir.
        """
        if self.student is None:
            raise ValueError("No student model to save")

        save_path = path or os.path.join(self.config.output_dir, "final_model")
        os.makedirs(save_path, exist_ok=True)

        torch.save(
            self.student.state_dict(),
            os.path.join(save_path, "model.pt"),
        )

        # Save config
        import json

        config_dict = {
            "model_name": self.config.model.model_name,
            "quantization_scheme": self.config.quantization.scheme.value,
            "weight_bits": self.config.quantization.weight_bits,
            "activation_bits": self.config.quantization.activation_bits,
            "is_moe": self.config.model.is_moe,
            "hidden_size": self.config.model.hidden_size,
            "num_layers": self.config.model.num_layers,
            "temperature": self.config.distillation.temperature,
        }
        with open(os.path.join(save_path, "config.json"), "w") as f:
            json.dump(config_dict, f, indent=2)

        logger.info(f"Student model saved to: {save_path}")

        # Log quantization summary
        summary = TopologyConverter.get_quantization_summary(self.student)
        total = summary["total_params"]
        if total > 0:
            effective_bits = (
                summary["quantized_params"] * 1.58
                + summary["fp16_params"] * 16
            ) / total
            logger.info(f"Effective bits per parameter: {effective_bits:.2f}")

            # Estimate memory savings
            fp16_memory_gb = total * 2 / (1024 ** 3)
            ternary_memory_gb = (
                summary["quantized_params"] * 1.58 / 8
                + summary["fp16_params"] * 2
            ) / (1024 ** 3)
            logger.info(
                f"Memory: FP16={fp16_memory_gb:.2f}GB -> "
                f"BitDistill={ternary_memory_gb:.2f}GB "
                f"({fp16_memory_gb / max(ternary_memory_gb, 0.001):.1f}x reduction)"
            )
