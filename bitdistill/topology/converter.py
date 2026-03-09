"""Topology Converter for BitDistill.

Handles Stage 1 of the BitDistill pipeline: selective replacement of
nn.Linear layers with BitLinear modules and injection of SubLN.

Implements multimodal-safe conversion:
- Vision encoder/projector: ALWAYS kept in FP16 (quantization destroys vision)
- MoE router: ALWAYS kept in FP16 (quantization causes routing collapse)
- LLM backbone (attention, FFN, GDN): Converted to BitLinear
- Embeddings and LM head: Optionally preserved in full precision
"""

from __future__ import annotations

import logging
from typing import Optional

import torch
import torch.nn as nn

from bitdistill.quantization.bitlinear import BitLinear
from bitdistill.modules.subln import SubLayerNorm
from bitdistill.config import QuantizationConfig

logger = logging.getLogger(__name__)


# Module name patterns that should NEVER be quantized
PROTECTED_PATTERNS = frozenset([
    # Vision encoder components (multimodal safety)
    "visual",
    "vision",
    "vit",
    "image_encoder",
    "vision_tower",
    "vision_encoder",
    "visual_encoder",
    "mm_projector",
    "projector",
    "image_projector",
    "patch_embed",
    # MoE router (routing collapse prevention)
    "router",
    "gate",
    "moe_gate",
    # Embeddings and head
    "embed_tokens",
    "lm_head",
    "wte",
    "wpe",
])

# Projection names where SubLN should be injected BEFORE
SUBLN_TARGETS = frozenset([
    "o_proj",      # Attention/GDN output projection
    "down_proj",   # FFN down projection
    "w2",          # MoE expert down projection
])


class TopologyConverter:
    """Converts a full-precision model to BitDistill topology.

    Performs:
    1. Selective replacement of nn.Linear -> BitLinear
    2. Injection of SubLN before output projections
    3. Protection of vision tower and MoE router in FP16

    Args:
        config: Quantization configuration.
        protected_patterns: Additional module name patterns to protect.
    """

    def __init__(
        self,
        config: Optional[QuantizationConfig] = None,
        protected_patterns: Optional[set[str]] = None,
    ):
        self.config = config or QuantizationConfig()
        self.protected_patterns = PROTECTED_PATTERNS.copy()
        if protected_patterns:
            self.protected_patterns = self.protected_patterns | protected_patterns

        self._conversion_stats = {
            "converted": 0,
            "skipped_protected": 0,
            "subln_injected": 0,
            "total_linear": 0,
        }

    def convert(self, model: nn.Module) -> nn.Module:
        """Convert model topology for BitDistill.

        Args:
            model: Full-precision model to convert.

        Returns:
            Modified model with BitLinear layers and SubLN injections.
        """
        self._conversion_stats = {
            "converted": 0, "skipped_protected": 0,
            "subln_injected": 0, "total_linear": 0,
        }

        self._replace_linear_recursive(model, "")
        self._inject_subln(model)

        logger.info(
            "Topology conversion complete: "
            f"{self._conversion_stats['converted']} layers converted, "
            f"{self._conversion_stats['skipped_protected']} protected, "
            f"{self._conversion_stats['subln_injected']} SubLN injected"
        )
        return model

    def _is_protected(self, full_name: str) -> bool:
        """Check if a module should be protected from quantization."""
        name_lower = full_name.lower()
        for pattern in self.protected_patterns:
            if pattern.lower() in name_lower:
                return True
        # Also check skip_layers from config
        for skip in self.config.skip_layers:
            if skip.lower() in name_lower:
                return True
        return False

    def _replace_linear_recursive(
        self, module: nn.Module, prefix: str
    ) -> None:
        """Recursively replace nn.Linear with BitLinear."""
        for name, child in list(module.named_children()):
            full_name = f"{prefix}.{name}" if prefix else name

            if isinstance(child, nn.Linear):
                self._conversion_stats["total_linear"] += 1

                if self._is_protected(full_name):
                    logger.debug(f"Skipping protected module: {full_name}")
                    self._conversion_stats["skipped_protected"] += 1
                    continue

                # Replace with BitLinear
                bit_linear = BitLinear.from_linear(
                    child,
                    eps=self.config.eps,
                    quantize_activations=(self.config.activation_bits == 8),
                )
                setattr(module, name, bit_linear)
                self._conversion_stats["converted"] += 1
                logger.debug(f"Converted to BitLinear: {full_name}")

            elif isinstance(child, BitLinear):
                # Already converted
                continue
            else:
                # Recurse into children
                self._replace_linear_recursive(child, full_name)

    def _inject_subln(self, model: nn.Module) -> None:
        """Inject SubLN modules before output projections.

        SubLN placement targets:
        - Before o_proj in attention/GDN blocks
        - Before down_proj in FFN blocks
        - Before w2 in MoE expert networks
        """
        for name, module in model.named_modules():
            if self._is_protected(name):
                continue

            # Check if this module contains SubLN target projections
            for target_name in SUBLN_TARGETS:
                if hasattr(module, target_name) and not hasattr(
                    module, f"_subln_{target_name}"
                ):
                    target = getattr(module, target_name)
                    if isinstance(target, (nn.Linear, BitLinear)):
                        in_features = (
                            target.in_features
                            if hasattr(target, "in_features")
                            else target.weight.shape[1]
                        )
                        subln = SubLayerNorm(in_features)
                        setattr(module, f"_subln_{target_name}", subln)
                        self._conversion_stats["subln_injected"] += 1
                        logger.debug(
                            f"Injected SubLN before {name}.{target_name}"
                        )

    def get_stats(self) -> dict:
        """Return conversion statistics."""
        return dict(self._conversion_stats)

    @staticmethod
    def get_quantization_summary(model: nn.Module) -> dict:
        """Summarize quantization state of all linear layers."""
        summary = {
            "bitlinear_layers": [],
            "fp16_layers": [],
            "total_params": 0,
            "quantized_params": 0,
            "fp16_params": 0,
        }

        for name, module in model.named_modules():
            if isinstance(module, BitLinear):
                num_params = module.weight.numel()
                summary["bitlinear_layers"].append(name)
                summary["quantized_params"] += num_params
                summary["total_params"] += num_params
            elif isinstance(module, nn.Linear):
                num_params = module.weight.numel()
                summary["fp16_layers"].append(name)
                summary["fp16_params"] += num_params
                summary["total_params"] += num_params

        return summary
