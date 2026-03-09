"""BitLinear: Drop-in replacement for nn.Linear with 1.58-bit quantization.

During the forward pass, full-precision FP16 "shadow weights" are dynamically
quantized to ternary {-1, 0, 1} using absmean quantization. Activations are
quantized to INT8 using per-token absmax. The Straight-Through Estimator (STE)
enables gradient flow through the non-differentiable operations.
"""

from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F

from bitdistill.quantization.utils import absmean_quantize_weights
from bitdistill.quantization.activation import quantize_activations_int8


class BitLinear(nn.Module):
    """1.58-bit linear layer (W1.58A8).

    Maintains full-precision shadow weights for optimizer updates.
    During forward pass:
      - Weights quantized to {-1, 0, 1} via absmean + STE
      - Activations quantized to INT8 via per-token absmax + STE

    This replaces expensive floating-point matrix multiplications with
    efficient integer additions at inference time.

    Args:
        in_features: Size of input features.
        out_features: Size of output features.
        bias: Whether to include a bias term (default: False for BitNet).
        eps: Numerical stability constant.
        quantize_activations: Whether to quantize activations to INT8.
    """

    def __init__(
        self,
        in_features: int,
        out_features: int,
        bias: bool = False,
        eps: float = 1e-8,
        quantize_activations: bool = True,
    ):
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.eps = eps
        self.quantize_activations = quantize_activations

        # Shadow weights in full precision (FP16/FP32)
        self.weight = nn.Parameter(
            torch.empty(out_features, in_features)
        )
        if bias:
            self.bias = nn.Parameter(torch.empty(out_features))
        else:
            self.register_parameter("bias", None)

        # Input normalization (RMSNorm before quantization)
        self.input_norm = RMSNorm(in_features, eps=eps)

        self.reset_parameters()

    def reset_parameters(self) -> None:
        """Initialize shadow weights using Kaiming uniform."""
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))
        if self.bias is not None:
            fan_in, _ = nn.init._calculate_fan_in_and_fan_out(self.weight)
            bound = 1 / math.sqrt(fan_in) if fan_in > 0 else 0
            nn.init.uniform_(self.bias, -bound, bound)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass with ternary weight and INT8 activation quantization.

        Args:
            x: Input tensor of shape (..., in_features).

        Returns:
            Output tensor of shape (..., out_features).
        """
        # 1. Normalize input activations
        x_norm = self.input_norm(x)

        # 2. Quantize activations to INT8 (per-token absmax)
        if self.quantize_activations:
            x_q = quantize_activations_int8(x_norm, eps=self.eps)
        else:
            x_q = x_norm

        # 3. Quantize weights to ternary {-1, 0, 1} (per-tensor absmean)
        w_q, _scale = absmean_quantize_weights(self.weight, eps=self.eps)

        # 4. Linear operation with quantized weights and activations
        output = F.linear(x_q, w_q, self.bias)

        return output

    @classmethod
    def from_linear(
        cls,
        linear: nn.Linear,
        eps: float = 1e-8,
        quantize_activations: bool = True,
    ) -> "BitLinear":
        """Create a BitLinear from an existing nn.Linear, copying weights.

        Args:
            linear: Source nn.Linear module.
            eps: Numerical stability constant.
            quantize_activations: Whether to quantize activations.

        Returns:
            BitLinear module with weights copied from source.
        """
        has_bias = linear.bias is not None
        bit_linear = cls(
            in_features=linear.in_features,
            out_features=linear.out_features,
            bias=has_bias,
            eps=eps,
            quantize_activations=quantize_activations,
        )
        bit_linear.weight.data.copy_(linear.weight.data)
        if has_bias and linear.bias is not None:
            bit_linear.bias.data.copy_(linear.bias.data)
        return bit_linear

    def extra_repr(self) -> str:
        return (
            f"in_features={self.in_features}, "
            f"out_features={self.out_features}, "
            f"bias={self.bias is not None}, "
            f"scheme=W1.58A8"
        )


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization.

    Used as input normalization within BitLinear before activation quantization.
    """

    def __init__(self, dim: int, eps: float = 1e-8):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        rms = torch.sqrt(x.pow(2).mean(dim=-1, keepdim=True) + self.eps)
        return x / rms * self.weight
