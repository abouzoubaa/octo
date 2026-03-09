"""
BitDistill: Architectural distillation and extreme quantization framework
for compressing full-precision LLMs into 1.58-bit ternary models.

Implements the BitDistill pipeline for Qwen 3.5 hybrid architectures
(Gated Delta Networks + Mixture-of-Experts).
"""

from bitdistill.config import BitDistillConfig, QuantizationConfig, DistillationConfig
from bitdistill.pipeline import BitDistillPipeline

__version__ = "0.1.0"
__all__ = [
    "BitDistillConfig",
    "QuantizationConfig",
    "DistillationConfig",
    "BitDistillPipeline",
]
