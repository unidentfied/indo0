"""
Task-specific heads for the Sindio Foundation Model.

1. StressHead: regresses stress (0–1) per infrastructure type per cell.
2. ForecastHead: autoregressive decoder for next 72 hours.
3. BreachClassifier: binary — will capacity be exceeded in 7 days?
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List, Optional, Tuple


class StressHead(nn.Module):
    """Regresses current stress (0–1) per infrastructure type per cell.

    Input: (B, 1024) fused latent
    Output: (B, num_types, num_cells) stress values.

    Infrastructure types: [power, water, road] → num_types = 3.
    Each cell has one stress value per type.
    """

    def __init__(
        self,
        latent_dim: int = 1024,
        num_types: int = 3,
        num_cells: int = 1,
        hidden_dim: int = 512,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.num_types = num_types
        self.num_cells = num_cells

        self.shared_layers = nn.Sequential(
            nn.Linear(latent_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(dropout),
        )

        # Per-type head for fine-grained stress prediction
        self.type_heads = nn.ModuleList([
            nn.Sequential(
                nn.Linear(hidden_dim // 2, 256),
                nn.GELU(),
                nn.Linear(256, num_cells),
                nn.Sigmoid(),  # stress in [0, 1]
            )
            for _ in range(num_types)
        ])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (B, 1024) fused latent.
        Returns:
            (B, num_types, num_cells) stress predictions in [0, 1].
        """
        features = self.shared_layers(x)  # (B, hidden_dim // 2)

        outputs = []
        for head in self.type_heads:
            out = head(features)  # (B, num_cells)
            outputs.append(out)

        return torch.stack(outputs, dim=1)  # (B, num_types, num_cells)


class AutoregressiveDecoderBlock(nn.Module):
    """Single autoregressive decoding block with causal self-attention."""

    def __init__(self, dim: int = 512, num_heads: int = 8, ff_mult: float = 4.0, dropout: float = 0.1):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.self_attn = nn.MultiheadAttention(dim, num_heads, dropout=dropout, batch_first=True)
        self.norm2 = nn.LayerNorm(dim)
        self.cross_attn = nn.MultiheadAttention(dim, num_heads, dropout=dropout, batch_first=True)
        self.norm3 = nn.LayerNorm(dim)
        self.ff = nn.Sequential(
            nn.Linear(dim, int(dim * ff_mult)),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(int(dim * ff_mult), dim),
            nn.Dropout(dropout),
        )

    def forward(
        self,
        x: torch.Tensor,
        memory: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        T = x.size(1)
        mask = causal_mask[:T, :T] if causal_mask is not None else None
        x = x + self.self_attn(x, x, x, attn_mask=mask, need_weights=False)[0]
        x = x + self.cross_attn(x, memory, memory, need_weights=False)[0]
        x = x + self.ff(self.norm3(x))
        return x


class ForecastHead(nn.Module):
    """Autoregressive decoder for next 72-hour predictions.

    Generates one step at a time, conditioned on the fused latent.
    Predicts: population, water demand, power demand, mobility pressure,
              stress (per type).

    Input:  (B, 1024) fused latent
    Output: (B, forecast_len, num_types * 3 + 4) per-step predictions.

    num_types * 3 = stress per type (3 stress values for power/water/road)
    + 4 = population, water_demand, power_demand, mobility_pressure
    Total output dim = num_types * 3 + 4
    """

    def __init__(
        self,
        latent_dim: int = 1024,
        forecast_len: int = 72,
        num_types: int = 3,
        num_cells: int = 1,
        d_model: int = 512,
        num_layers: int = 3,
        num_heads: int = 8,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.forecast_len = forecast_len
        self.num_cells = num_cells
        num_features = num_types * num_cells + 4  # stress per type + 4 scalar series
        out_dim = num_features

        self.latent_proj = nn.Linear(latent_dim, d_model)
        self.pos_embed = nn.Parameter(torch.randn(1, forecast_len, d_model) * 0.02)
        self.start_token = nn.Parameter(torch.randn(1, 1, d_model) * 0.02)

        # Causal mask
        causal = torch.triu(torch.ones(forecast_len, forecast_len) * float("-inf"), diagonal=1)
        self.register_buffer("causal_mask", causal)

        self.blocks = nn.ModuleList([
            AutoregressiveDecoderBlock(d_model, num_heads, dropout=dropout)
            for _ in range(num_layers)
        ])

        self.norm_out = nn.LayerNorm(d_model)
        self.output_proj = nn.Sequential(
            nn.Linear(d_model, d_model // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, out_dim),
        )

    def forward(self, latent: torch.Tensor) -> torch.Tensor:
        """
        Args:
            latent: (B, 1024) fused latent representation.
        Returns:
            (B, forecast_len, output_dim) forecast values.
        """
        B = latent.shape[0]
        memory = self.latent_proj(latent).unsqueeze(1)  # (B, 1, d_model)

        # Start token repeated across forecast horizon
        x = self.start_token.expand(B, self.forecast_len, -1) + self.pos_embed

        for block in self.blocks:
            x = block(x, memory, self.causal_mask)

        x = self.norm_out(x)
        out = self.output_proj(x)  # (B, forecast_len, output_dim)
        return out


class BreachClassifier(nn.Module):
    """Binary classifier: will infrastructure capacity be exceeded in next 7 days?

    Input:  (B, 1024) fused latent  +  (B, num_types, num_cells) stress from StressHead
    Output: (B, num_types, num_cells) logits for breach probability.
    """

    def __init__(
        self,
        latent_dim: int = 1024,
        num_types: int = 3,
        num_cells: int = 1,
        hidden_dim: int = 512,
        dropout: float = 0.1,
        forecast_window_days: int = 7,
    ):
        super().__init__()
        self.num_types = num_types
        self.num_cells = num_cells
        self.forecast_window_days = forecast_window_days

        # Combine latent + stress predictions
        stress_dim = num_types * num_cells
        input_dim = latent_dim + stress_dim

        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, num_types * num_cells),
        )

    def forward(self, latent: torch.Tensor, stress: torch.Tensor) -> torch.Tensor:
        """
        Args:
            latent: (B, 1024) fused latent.
            stress: (B, num_types, num_cells) stress predictions.
        Returns:
            (B, num_types, num_cells) raw logits for breach.
        """
        B = latent.shape[0]
        stress_flat = stress.reshape(B, -1)  # (B, num_types * num_cells)
        combined = torch.cat([latent, stress_flat], dim=-1)  # (B, latent_dim + stress_dim)

        logits = self.net(combined)  # (B, num_types * num_cells)
        return logits.reshape(B, self.num_types, self.num_cells)
