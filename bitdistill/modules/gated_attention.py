"""Gated Attention block with BitDistill modifications.

Standard softmax attention used in 25% of Qwen 3.5 layers (every 4th layer)
to periodically refresh global context. Uses Grouped Query Attention (GQA)
with rotary position embeddings (RoPE).

SubLN is inserted before the output projection to stabilize ternary states.
Exposes attention weight matrices for relational distillation.
"""

from __future__ import annotations

import math
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from bitdistill.quantization.bitlinear import BitLinear
from bitdistill.modules.subln import SubLayerNorm


class RotaryEmbedding(nn.Module):
    """Rotary Position Embeddings (RoPE)."""

    def __init__(self, dim: int, max_seq_len: int = 262144, base: float = 10000.0):
        super().__init__()
        inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2).float() / dim))
        self.register_buffer("inv_freq", inv_freq, persistent=False)
        self.max_seq_len = max_seq_len

    def forward(self, x: torch.Tensor, seq_len: int) -> tuple[torch.Tensor, torch.Tensor]:
        t = torch.arange(seq_len, device=x.device, dtype=self.inv_freq.dtype)
        freqs = torch.outer(t, self.inv_freq)
        emb = torch.cat((freqs, freqs), dim=-1)
        return emb.cos(), emb.sin()


def rotate_half(x: torch.Tensor) -> torch.Tensor:
    """Rotate half of the hidden dimensions."""
    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat((-x2, x1), dim=-1)


def apply_rotary_pos_emb(
    q: torch.Tensor, k: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    """Apply rotary position embeddings to Q and K tensors."""
    q_embed = (q * cos) + (rotate_half(q) * sin)
    k_embed = (k * cos) + (rotate_half(k) * sin)
    return q_embed, k_embed


class GatedAttentionBlock(nn.Module):
    """Gated softmax attention block with GQA and RoPE.

    Args:
        hidden_size: Model hidden dimension.
        num_q_heads: Number of query heads (16 for 4B).
        num_kv_heads: Number of key-value heads (4 for 4B, GQA).
        head_dim: Dimension per head (256 for attention in 4B).
        rope_dim: Dimension for RoPE (64 for 4B).
        use_bitlinear: Whether to use BitLinear (True for student).
        eps: Numerical stability constant.
    """

    def __init__(
        self,
        hidden_size: int = 2560,
        num_q_heads: int = 16,
        num_kv_heads: int = 4,
        head_dim: int = 256,
        rope_dim: int = 64,
        use_bitlinear: bool = True,
        eps: float = 1e-8,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_q_heads = num_q_heads
        self.num_kv_heads = num_kv_heads
        self.head_dim = head_dim
        self.num_kv_groups = num_q_heads // num_kv_heads

        LinearClass = BitLinear if use_bitlinear else nn.Linear

        # Projections
        self.q_proj = LinearClass(hidden_size, num_q_heads * head_dim, bias=False)
        self.k_proj = LinearClass(hidden_size, num_kv_heads * head_dim, bias=False)
        self.v_proj = LinearClass(hidden_size, num_kv_heads * head_dim, bias=False)
        self.o_proj = LinearClass(num_q_heads * head_dim, hidden_size, bias=False)

        # SubLN before output projection
        self.sub_ln = SubLayerNorm(num_q_heads * head_dim, eps=eps)

        # Pre-normalization
        self.input_norm = RMSNorm(hidden_size, eps=eps)

        # Rotary embeddings
        self.rotary_emb = RotaryEmbedding(rope_dim)

        # Attention scaling factor
        self.scale = 1.0 / math.sqrt(head_dim)

        # Store attention weights for distillation
        self._attention_weights: Optional[torch.Tensor] = None

    def forward(
        self,
        x: torch.Tensor,
        attention_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Forward pass through gated attention block.

        Args:
            x: Input tensor of shape (batch, seq_len, hidden_size).
            attention_mask: Optional causal mask.

        Returns:
            Output tensor of shape (batch, seq_len, hidden_size).
        """
        batch, seq_len, _ = x.shape
        residual = x

        # Pre-normalization
        x = self.input_norm(x)

        # Compute QKV projections
        q = self.q_proj(x).view(batch, seq_len, self.num_q_heads, self.head_dim)
        k = self.k_proj(x).view(batch, seq_len, self.num_kv_heads, self.head_dim)
        v = self.v_proj(x).view(batch, seq_len, self.num_kv_heads, self.head_dim)

        # Transpose for attention: (batch, heads, seq_len, head_dim)
        q = q.transpose(1, 2)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)

        # Apply RoPE to Q and K
        cos, sin = self.rotary_emb(q, seq_len)
        # Only apply to the first rope_dim dimensions
        q_rope = q[..., : cos.shape[-1]]
        k_rope = k[..., : cos.shape[-1]]
        q_rope, k_rope = apply_rotary_pos_emb(q_rope, k_rope, cos, sin)
        q = torch.cat([q_rope, q[..., cos.shape[-1]:]], dim=-1)
        k = torch.cat([k_rope, k[..., cos.shape[-1]:]], dim=-1)

        # Expand KV heads for GQA
        if self.num_kv_groups > 1:
            k = k.repeat_interleave(self.num_kv_groups, dim=1)
            v = v.repeat_interleave(self.num_kv_groups, dim=1)

        # Scaled dot-product attention
        attn_weights = torch.matmul(q, k.transpose(-2, -1)) * self.scale

        # Apply causal mask
        if attention_mask is None:
            causal_mask = torch.triu(
                torch.full((seq_len, seq_len), float("-inf"), device=x.device),
                diagonal=1,
            )
            attn_weights = attn_weights + causal_mask

        attn_weights = F.softmax(attn_weights, dim=-1, dtype=torch.float32).to(
            q.dtype
        )

        # Store attention weights for distillation
        self._attention_weights = attn_weights.detach()

        # Apply attention to values
        output = torch.matmul(attn_weights, v)

        # Reshape: (batch, heads, seq_len, head_dim) -> (batch, seq_len, hidden)
        output = output.transpose(1, 2).reshape(batch, seq_len, -1)

        # SubLN before output projection
        output = self.sub_ln(output)

        # Output projection
        output = self.o_proj(output)

        # Residual connection
        output = residual + output

        return output

    def get_attention_weights(self) -> Optional[torch.Tensor]:
        """Return attention weights for relational distillation."""
        return self._attention_weights


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization."""

    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        variance = x.pow(2).mean(dim=-1, keepdim=True)
        x = x * torch.rsqrt(variance + self.eps)
        return x * self.weight
