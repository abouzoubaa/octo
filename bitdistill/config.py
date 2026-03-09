"""Configuration classes for the BitDistill pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class QuantizationScheme(Enum):
    """Supported quantization schemes."""

    W158_A8 = "w1.58_a8"  # Ternary weights, INT8 activations
    W158_A16 = "w1.58_a16"  # Ternary weights, FP16 activations
    FP16 = "fp16"  # Full precision (no quantization)
    INT8 = "int8"  # 8-bit weights and activations
    INT4 = "int4"  # 4-bit weights


class LayerType(Enum):
    """Layer types in the Qwen 3.5 hybrid architecture."""

    GATED_DELTA_NET = "gated_delta_net"
    GATED_ATTENTION = "gated_attention"
    DENSE_FFN = "dense_ffn"
    MOE_EXPERT = "moe_expert"
    MOE_ROUTER = "moe_router"
    EMBEDDING = "embedding"
    LM_HEAD = "lm_head"


@dataclass
class QuantizationConfig:
    """Configuration for quantization parameters."""

    scheme: QuantizationScheme = QuantizationScheme.W158_A8
    weight_bits: float = 1.58
    activation_bits: int = 8
    # Per-tensor absmean for weights
    weight_quant_method: str = "absmean"
    # Per-token absmax for activations
    activation_quant_method: str = "absmax"
    # Epsilon for numerical stability
    eps: float = 1e-8
    # Whether to use STE for gradient estimation
    use_ste: bool = True
    # MoE selective quantization settings
    router_precision: str = "fp16"  # Keep router in high precision
    attention_precision: str = "w1.58_a8"  # Quantize attention layers
    expert_precision: str = "w1.58_a8"  # Quantize expert FFNs
    # Layers to skip quantization (e.g., embeddings, lm_head)
    skip_layers: list[str] = field(
        default_factory=lambda: ["embed_tokens", "lm_head"]
    )


@dataclass
class DistillationConfig:
    """Configuration for the dual-objective distillation."""

    # Temperature for logit distillation (KL divergence)
    temperature: float = 2.0
    # Weight for logit distillation loss
    alpha_logit: float = 0.5
    # Weight for attention/state distillation loss
    alpha_attention: float = 0.5
    # Which layers to distill attention from (indices)
    distill_layer_indices: Optional[list[int]] = None
    # Whether to distill GDN hidden states (MSE) vs attention maps (KL)
    distill_gdn_states: bool = True
    # Number of attention heads to distill (None = all)
    num_distill_heads: Optional[int] = None


@dataclass
class TrainingConfig:
    """Configuration for training hyperparameters."""

    # Optimizer settings (AdamW as specified by BitDistill)
    optimizer: str = "adamw"
    beta1: float = 0.9
    beta2: float = 0.98
    eps: float = 1e-6
    weight_decay: float = 0.01
    # Learning rate settings
    max_lr: float = 1e-4
    min_lr: float = 1e-6
    lr_schedule: str = "linear_decay"
    warmup_steps: int = 500
    # Warm-up pre-training settings
    warmup_pretrain_steps: int = 5000
    warmup_pretrain_batch_size: int = 8
    warmup_pretrain_seq_length: int = 2048
    # Distillation training settings
    distill_steps: int = 20000
    distill_batch_size: int = 4
    distill_seq_length: int = 2048
    # General
    gradient_accumulation_steps: int = 4
    max_grad_norm: float = 1.0
    fp16: bool = True
    bf16: bool = False
    seed: int = 42
    logging_steps: int = 100
    save_steps: int = 1000
    eval_steps: int = 500


@dataclass
class Qwen35ModelConfig:
    """Architecture configuration for Qwen 3.5 model variants."""

    model_name: str = "qwen3.5-4b"
    hidden_size: int = 2560
    num_layers: int = 32
    num_attention_heads: int = 16
    num_kv_heads: int = 4
    head_dim: int = 256
    intermediate_size: int = 9216
    vocab_size: int = 151936
    max_position_embeddings: int = 262144
    rope_dim: int = 64
    # GDN-specific
    gdn_num_v_heads: int = 32
    gdn_num_qk_heads: int = 16
    gdn_head_dim: int = 128
    # Hybrid layout: ratio of GDN to Attention blocks
    gdn_to_attn_ratio: int = 3  # 3:1 ratio
    # Layout pattern: repeating block of [GDN, GDN, GDN, Attn]
    hidden_layout: str = "3gdn_1attn"
    # MoE settings (for MoE variants)
    is_moe: bool = False
    num_experts: int = 1
    num_active_experts: int = 1
    moe_intermediate_size: Optional[int] = None
    rms_norm_eps: float = 1e-6

    def get_layer_type(self, layer_idx: int) -> LayerType:
        """Determine the layer type based on the hybrid layout pattern."""
        block_size = self.gdn_to_attn_ratio + 1  # e.g., 4 for 3:1
        position_in_block = layer_idx % block_size
        if position_in_block < self.gdn_to_attn_ratio:
            return LayerType.GATED_DELTA_NET
        return LayerType.GATED_ATTENTION


@dataclass
class BitDistillConfig:
    """Top-level configuration for the BitDistill pipeline."""

    quantization: QuantizationConfig = field(default_factory=QuantizationConfig)
    distillation: DistillationConfig = field(default_factory=DistillationConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    model: Qwen35ModelConfig = field(default_factory=Qwen35ModelConfig)
    # Teacher model path (frozen FP16)
    teacher_model_path: str = ""
    # Student model output path
    output_dir: str = "./bitdistill_output"
    # Pre-training corpus path (for warm-up stage)
    warmup_corpus_path: str = ""
    # Distillation dataset path
    distill_dataset_path: str = ""
    # Resume from checkpoint
    resume_from: Optional[str] = None


# Pre-defined configurations for known Qwen 3.5 variants
QWEN35_CONFIGS: dict[str, Qwen35ModelConfig] = {
    "qwen3.5-0.8b": Qwen35ModelConfig(
        model_name="qwen3.5-0.8b",
        hidden_size=1024,
        num_layers=24,
        num_attention_heads=8,
        num_kv_heads=2,
        intermediate_size=4096,
    ),
    "qwen3.5-4b": Qwen35ModelConfig(
        model_name="qwen3.5-4b",
        hidden_size=2560,
        num_layers=32,
        num_attention_heads=16,
        num_kv_heads=4,
        intermediate_size=9216,
    ),
    "qwen3.5-27b": Qwen35ModelConfig(
        model_name="qwen3.5-27b",
        hidden_size=5120,
        num_layers=64,
        num_attention_heads=40,
        num_kv_heads=8,
        intermediate_size=18432,
    ),
    "qwen3.5-35b-a3b": Qwen35ModelConfig(
        model_name="qwen3.5-35b-a3b",
        hidden_size=2560,
        num_layers=48,
        num_attention_heads=16,
        num_kv_heads=4,
        intermediate_size=9216,
        is_moe=True,
        num_experts=16,
        num_active_experts=2,
    ),
    "qwen3.5-122b-a10b": Qwen35ModelConfig(
        model_name="qwen3.5-122b-a10b",
        hidden_size=3072,
        num_layers=48,
        num_attention_heads=24,
        num_kv_heads=4,
        intermediate_size=12288,
        is_moe=True,
        num_experts=16,
        num_active_experts=4,
    ),
}
