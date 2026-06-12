"""
Cross-attention fusion between vision, graph, and temporal encoders.
Outputs a 1024-dim latent vector.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List, Optional, Tuple


class MultiHeadCrossAttention(nn.Module):
    """Cross-attention: query from one modality, key/value from another."""

    def __init__(self, dim: int = 1024, num_heads: int = 8, dropout: float = 0.1):
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = dim // num_heads
        self.scale = self.head_dim ** -0.5

        self.q_proj = nn.Linear(dim, dim)
        self.k_proj = nn.Linear(dim, dim)
        self.v_proj = nn.Linear(dim, dim)
        self.out_proj = nn.Linear(dim, dim)
        self.dropout = nn.Dropout(dropout)

    def forward(self, query: torch.Tensor, key_value: torch.Tensor) -> torch.Tensor:
        B, d = query.shape
        q = self.q_proj(query).view(B, 1, self.num_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(key_value).view(B, 1, self.num_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(key_value).view(B, 1, self.num_heads, self.head_dim).transpose(1, 2)

        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = F.softmax(attn, dim=-1)
        attn = self.dropout(attn)

        out = (attn @ v).transpose(1, 2).reshape(B, d)
        return self.out_proj(out)


class GatedFusion(nn.Module):
    """Gated fusion: learn how much each modality contributes to the final embedding."""

    def __init__(self, dim: int = 1024, n_modalities: int = 3):
        super().__init__()
        self.gate = nn.Sequential(
            nn.Linear(dim * n_modalities, dim),
            nn.Sigmoid(),
        )
        self.n_modalities = n_modalities

    def forward(self, embeddings: List[torch.Tensor]) -> torch.Tensor:
        concat = torch.cat(embeddings, dim=-1)  # (B, dim * 3)
        gates = self.gate(concat)  # (B, dim)
        stacked = torch.stack(embeddings, dim=0)  # (3, B, dim)
        weighted = stacked * gates.unsqueeze(0)  # (3, B, dim)
        return weighted.sum(dim=0)  # (B, dim)


class CrossModalFusion(nn.Module):
    """Fuses vision, graph, and temporal embeddings via multi-directional cross-attention.

    Input:  vision (B, 1024), graph (B, 1024), temporal (B, 1024)
    Output: (B, 1024) fused latent representation.

    Fuses in 3 directions:
      - Vision → Graph
      - Graph  → Temporal
      - Temporal → Vision
    Then gates the outputs together.
    """

    def __init__(
        self,
        dim: int = 1024,
        num_heads: int = 8,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.cross_v2g = MultiHeadCrossAttention(dim, num_heads, dropout)
        self.cross_g2t = MultiHeadCrossAttention(dim, num_heads, dropout)
        self.cross_t2v = MultiHeadCrossAttention(dim, num_heads, dropout)
        self.gate = GatedFusion(dim, n_modalities=3)
        self.norm = nn.LayerNorm(dim)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        vision: torch.Tensor,
        graph: torch.Tensor,
        temporal: torch.Tensor,
    ) -> torch.Tensor:
        """
        Args:
            vision:   (B, 1024) from SwinEncoder.
            graph:    (B, 1024) from GINEncoder.
            temporal: (B, 1024) from TemporalTransformerEncoder.
        Returns:
            (B, 1024) fused latent representation.
        """
        v2g = self.cross_v2g(vision, graph)
        g2t = self.cross_g2t(graph, temporal)
        t2v = self.cross_t2v(temporal, vision)

        fused = self.gate([v2g, g2t, t2v])
        fused = self.norm(fused)
        fused = self.dropout(fused)
        return fused
