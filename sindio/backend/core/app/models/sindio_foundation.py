"""
SindioFoundationModel — multi-modal urban stress prediction model.

Encoder A: Swin Transformer (Sentinel-2 10-band satellite patches)
Encoder B: Graph Isomorphism Network (infrastructure topology)
Encoder C: RoPE Transformer (72-hour time-series windows)
Fusion: Cross-attention between all three → 1024-dim latent
Heads: StressHead, ForecastHead, BreachClassifier
"""

import torch
import torch.nn as nn
from typing import Any, Dict, List, Optional, Tuple

from .encoders_vision import SwinEncoder, swin_tiny_10band
from .encoders_graph import GINEncoder
from .encoders_temporal import TemporalTransformerEncoder
from .fusion import CrossModalFusion
from .heads import StressHead, ForecastHead, BreachClassifier


class SindioFoundationModel(nn.Module):
    """Multi-modal foundation model for urban infrastructure stress prediction.

    Three modalities → fused latent → three task heads.

    Usage:
        model = SindioFoundationModel()
        outputs = model(
            satellite=torch.randn(4, 10, 224, 224),
            node_features=torch.randn(128, 16),
            edge_index=torch.randint(0, 128, (2, 300)),
            node_types=torch.randint(0, 5, (128,)),
            time_series=torch.randn(4, 72, 8),
        )
        # outputs = {
        #     "stress": (4, 3, 1),
        #     "forecast": (4, 72, 7),
        #     "breach_logits": (4, 3, 1),
        #     "vision_emb": (4, 1024),
        #     "graph_emb": (4, 1024),
        #     "temporal_emb": (4, 1024),
        #     "fused": (4, 1024),
        # }
    """

    def __init__(
        self,
        # Vision
        vision_in_channels: int = 10,
        vision_image_size: int = 224,
        vision_pretrained_path: Optional[str] = None,
        # Graph
        graph_node_feat_dim: int = 16,
        graph_node_type_count: int = 5,
        graph_edge_feat_dim: int = 6,
        # Temporal
        temporal_seq_len: int = 72,
        temporal_features: int = 8,
        # Shared
        latent_dim: int = 1024,
        # Heads
        num_stress_types: int = 3,
        num_cells: int = 1,
        forecast_len: int = 72,
        breach_window_days: int = 7,
        # Regularisation
        dropout: float = 0.1,
    ):
        super().__init__()
        self.latent_dim = latent_dim

        # ── Encoders ────────────────────────────────────
        self.vision_encoder = swin_tiny_10band(
            latent_dim=latent_dim, pretrained_path=vision_pretrained_path
        )

        self.graph_encoder = GINEncoder(
            node_feat_dim=graph_node_feat_dim,
            node_type_count=graph_node_type_count,
            edge_feat_dim=graph_edge_feat_dim,
            latent_dim=latent_dim,
            dropout=dropout,
        )

        self.temporal_encoder = TemporalTransformerEncoder(
            seq_len=temporal_seq_len,
            features_per_step=temporal_features,
            latent_dim=latent_dim,
            dropout=dropout,
        )

        # ── Fusion ──────────────────────────────────────
        self.fusion = CrossModalFusion(
            dim=latent_dim,
            num_heads=8,
            dropout=dropout,
        )

        # ── Heads ───────────────────────────────────────
        self.stress_head = StressHead(
            latent_dim=latent_dim,
            num_types=num_stress_types,
            num_cells=num_cells,
            dropout=dropout,
        )

        self.forecast_head = ForecastHead(
            latent_dim=latent_dim,
            forecast_len=forecast_len,
            num_types=num_stress_types,
            num_cells=num_cells,
            dropout=dropout,
        )

        self.breach_classifier = BreachClassifier(
            latent_dim=latent_dim,
            num_types=num_stress_types,
            num_cells=num_cells,
            dropout=dropout,
            forecast_window_days=breach_window_days,
        )

    def encode(
        self,
        satellite: torch.Tensor,
        graph_batch: Dict[str, torch.Tensor],
        time_series: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Encode each modality independently.

        Returns:
            vision_emb, graph_emb, temporal_emb: each (B, 1024).
        """
        vision = self.vision_encoder(satellite)

        graph = self.graph_encoder(
            node_features=graph_batch["node_features"],
            edge_index=graph_batch["edge_index"],
            node_types=graph_batch.get("node_types"),
            edge_attr=graph_batch.get("edge_attr"),
            batch=graph_batch.get("batch"),
        )

        temporal = self.temporal_encoder(time_series)

        return vision, graph, temporal

    def forward(
        self,
        satellite: Optional[torch.Tensor] = None,
        graph_batch: Optional[Dict[str, torch.Tensor]] = None,
        time_series: Optional[torch.Tensor] = None,
        return_embeddings: bool = True,
    ) -> Dict[str, torch.Tensor]:
        """Full forward pass through encoders, fusion, and heads.

        At least one modality must be provided. Missing modalities
        are replaced with zero tensors of batch size inferred from
        provided inputs.
        """
        # Infer batch size from first available input
        batch: Optional[int] = None
        for t in (satellite, time_series):
            if t is not None:
                batch = t.size(0)
                break

        if graph_batch is not None and batch is None:
            if "batch" in graph_batch:
                batch = graph_batch["batch"].max().item() + 1
            else:
                batch = 1

        if batch is None:
            raise ValueError("At least one input modality must be provided.")

        device = next(self.parameters()).device

        # Encode or create zero placeholders
        if satellite is not None:
            vision_emb = self.vision_encoder(satellite.to(device))
        else:
            vision_emb = torch.zeros(batch, self.latent_dim, device=device)

        if graph_batch is not None:
            graph_emb = self.graph_encoder(
                node_features=graph_batch["node_features"].to(device),
                edge_index=graph_batch["edge_index"].to(device),
                node_types=graph_batch.get("node_types", None),
                edge_attr=graph_batch.get("edge_attr", None),
                batch=graph_batch.get("batch", None),
            )
        else:
            graph_emb = torch.zeros(batch, self.latent_dim, device=device)

        if time_series is not None:
            temporal_emb = self.temporal_encoder(time_series.to(device))
        else:
            temporal_emb = torch.zeros(batch, self.latent_dim, device=device)

        # Fusion
        fused = self.fusion(vision_emb, graph_emb, temporal_emb)

        # Task heads
        stress = self.stress_head(fused)
        forecast = self.forecast_head(fused)
        breach_logits = self.breach_classifier(fused, stress)

        output: Dict[str, torch.Tensor] = {
            "stress": stress,
            "forecast": forecast,
            "breach_logits": breach_logits,
            "fused": fused,
        }

        if return_embeddings:
            output["vision_emb"] = vision_emb
            output["graph_emb"] = graph_emb
            output["temporal_emb"] = temporal_emb

        return output

    @torch.no_grad()
    def predict_breach(self, **kwargs) -> torch.Tensor:
        """Convenience: probability of capacity breach in next 7 days."""
        out = self.forward(**kwargs)
        return torch.sigmoid(out["breach_logits"])

    @torch.no_grad()
    def get_stress_map(self, **kwargs) -> torch.Tensor:
        """Convenience: stress levels per infrastructure type."""
        out = self.forward(**kwargs)
        return out["stress"]
