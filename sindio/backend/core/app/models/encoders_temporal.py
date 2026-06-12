"""
Transformer encoder with rotary position embeddings (RoPE).
Encodes 72-hour historical windows of multivariate time series:
  population density, mobility pressure, power demand, water demand.

Input:  (B, 72, features_per_window)  [72 hourly steps × K features]
Output: (B, 1024) temporal latent embedding.
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional


class RotaryPositionalEmbedding(nn.Module):
    """Rotary Position Embedding (RoPE) — Su et al. 2021."""

    def __init__(self, dim: int, max_len: int = 10000):
        super().__init__()
        self.dim = dim
        inv_freq = 1.0 / (10000 ** (torch.arange(0, dim, 2).float() / dim))
        self.register_buffer("inv_freq", inv_freq)
        self._max_len = max_len
        self._cached_cos: Optional[torch.Tensor] = None
        self._cached_sin: Optional[torch.Tensor] = None

    def _build_cache(self, seq_len: int, device: torch.device):
        t = torch.arange(seq_len, device=device, dtype=self.inv_freq.dtype)
        freqs = torch.einsum("i,j->ij", t, self.inv_freq)
        emb = torch.cat((freqs, freqs), dim=-1)
        self._cached_cos = emb.cos().unsqueeze(0).unsqueeze(0)
        self._cached_sin = emb.sin().unsqueeze(0).unsqueeze(0)

    def forward(self, x: torch.Tensor, offset: int = 0) -> torch.Tensor:
        seq_len = x.size(1)
        if self._cached_cos is None or seq_len + offset > self._cached_cos.size(2):
            self._build_cache(seq_len + offset, x.device)
        cos = self._cached_cos[:, :, offset: offset + seq_len, :]
        sin = self._cached_sin[:, :, offset: offset + seq_len, :]
        x1, x2 = x.chunk(2, dim=-1)
        return torch.cat([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1)


class TransformerLayer(nn.Module):
    """Single RoPE transformer block with pre-norm and GELU FFN."""

    def __init__(
        self,
        dim: int,
        num_heads: int = 8,
        ff_mult: float = 4.0,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.rope = RotaryPositionalEmbedding(dim // num_heads)
        self.norm1 = nn.LayerNorm(dim)
        self.attn = nn.MultiheadAttention(
            dim, num_heads, dropout=dropout, batch_first=True
        )
        self.norm2 = nn.LayerNorm(dim)
        self.ff = nn.Sequential(
            nn.Linear(dim, int(dim * ff_mult)),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(int(dim * ff_mult), dim),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor, attn_mask: Optional[torch.Tensor] = None) -> torch.Tensor:
        residual = x
        x = self.norm1(x)
        q = k = self.rope(x)
        v = x
        x, _ = self.attn(q, k, v, attn_mask=attn_mask, need_weights=False)
        x = residual + x
        x = x + self.ff(self.norm2(x))
        return x


class TemporalTransformerEncoder(nn.Module):
    """RoPE Transformer for 72-hour multi-variate time-series windows.

    Hyperparameters
    ---------------
    seq_len : int = 72        Hours of history
    features_per_step : int   Number of channels per time step
    d_model : int = 256       Internal embedding dim
    num_layers : int = 4      Transformer layers
    num_heads : int = 8       Attention heads
    latent_dim : int = 1024   Output projection dim
    """

    def __init__(
        self,
        seq_len: int = 72,
        features_per_step: int = 8,
        d_model: int = 256,
        num_layers: int = 4,
        num_heads: int = 8,
        latent_dim: int = 1024,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.seq_len = seq_len

        self.input_proj = nn.Sequential(
            nn.Linear(features_per_step, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
        )

        self.layers = nn.ModuleList([
            TransformerLayer(d_model, num_heads=num_heads, dropout=dropout)
            for _ in range(num_layers)
        ])

        # Causal mask: prevent attending to future steps (autoregressive-friendly)
        causal_mask = torch.triu(
            torch.ones(seq_len, seq_len, dtype=torch.bool), diagonal=1
        )
        self.register_buffer("causal_mask", causal_mask)

        self.norm_out = nn.LayerNorm(d_model)

        # Time-aware aggregation: learned importance over time steps
        self.time_attn = nn.MultiheadAttention(
            d_model, num_heads=1, batch_first=True
        )
        self.time_query = nn.Parameter(torch.randn(1, 1, d_model) * 0.02)

        self.latent_proj = nn.Linear(d_model, latent_dim)

    def forward(
        self,
        x: torch.Tensor,
        mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Forward pass.

        Args:
            x: (B, 72, features_per_step) — time-series window.
            mask: (B, 72) optional padding mask (True = valid).
        Returns:
            (B, 1024) temporal latent embedding.
        """
        B, T, _ = x.shape

        # Pad/crop to expected sequence length
        if T < self.seq_len:
            pad = torch.zeros(B, self.seq_len - T, x.size(-1), device=x.device)
            x = torch.cat([x, pad], dim=1)
            if mask is not None:
                mask = torch.cat([mask, torch.zeros(B, self.seq_len - T, device=x.device, dtype=torch.bool)], dim=1)
        elif T > self.seq_len:
            x = x[:, -self.seq_len :]
            if mask is not None:
                mask = mask[:, -self.seq_len :]

        x = self.input_proj(x)  # (B, T, d_model)

        # Apply transformer layers with causal mask
        causal = self.causal_mask[: x.size(1), : x.size(1)]
        for layer in self.layers:
            x = layer(x, attn_mask=causal)

        x = self.norm_out(x)  # (B, T, d_model)

        # Time-aware pooling via learned query
        query = self.time_query.expand(B, -1, -1)
        x_pooled, _ = self.time_attn(query, x, x, need_weights=False)
        x_pooled = x_pooled.squeeze(1)  # (B, d_model)

        out = self.latent_proj(x_pooled)  # (B, latent_dim)
        return out
