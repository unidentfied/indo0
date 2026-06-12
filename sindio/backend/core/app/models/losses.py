"""
Combined loss functions for SindioFoundationModel.

Loss = λ₁ * MSE(stress) + λ₂ * BCE(breach) + λ₃ * Contrastive(alignment)

Contrastive loss aligns the three modality embeddings — vision, graph,
temporal — in the shared latent space via InfoNCE.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, Tuple


class ModalityContrastiveLoss(nn.Module):
    """InfoNCE contrastive loss for three modalities.

    For each pair (vision↔graph, graph↔temporal, temporal↔vision),
    treat matching embeddings as positive pairs and other batch
    members as negatives.

    Loss = -1/B Σ log(exp(sim(a_i, b_i)/τ) / Σ_j exp(sim(a_i, b_j)/τ))
    """

    def __init__(self, temperature: float = 0.07):
        super().__init__()
        self.temperature = temperature
        self.logit_scale = nn.Parameter(torch.log(torch.tensor(1.0 / temperature)))

    def forward(
        self,
        vision: torch.Tensor,
        graph: torch.Tensor,
        temporal: torch.Tensor,
    ) -> torch.Tensor:
        """
        Args:
            vision: (B, D)
            graph: (B, D)
            temporal: (B, D)
        Returns:
            Scalar loss (mean across 3 pairs).
        """
        logit_scale = self.logit_scale.exp()

        def pairwise_nce(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
            a = F.normalize(a, p=2, dim=-1)
            b = F.normalize(b, p=2, dim=-1)
            logits = (a @ b.T) * logit_scale  # (B, B)
            labels = torch.arange(a.size(0), device=a.device)
            return F.cross_entropy(logits, labels)

        loss_vg = pairwise_nce(vision, graph)
        loss_gt = pairwise_nce(graph, temporal)
        loss_tv = pairwise_nce(temporal, vision)

        return (loss_vg + loss_gt + loss_tv) / 3.0


class SindioLoss(nn.Module):
    """Combined training loss for SindioFoundationModel.

    L_total = λ_stress * MSE(stress_pred, stress_gt)
            + λ_breach * BCE(breach_logits, breach_gt)
            + λ_contrastive * Contrastive(vision, graph, temporal)
            + λ_forecast * MSE(forecast_pred, forecast_gt)

    All losses are masked where ground-truth is unavailable.
    """

    def __init__(
        self,
        lambda_stress: float = 1.0,
        lambda_breach: float = 2.0,
        lambda_contrastive: float = 0.1,
        lambda_forecast: float = 1.5,
        temperature: float = 0.07,
    ):
        super().__init__()
        self.lambda_stress = lambda_stress
        self.lambda_breach = lambda_breach
        self.lambda_contrastive = lambda_contrastive
        self.lambda_forecast = lambda_forecast

        self.mse = nn.MSELoss(reduction="none")
        self.bce = nn.BCEWithLogitsLoss(reduction="none")
        self.contrastive = ModalityContrastiveLoss(temperature=temperature)

    def forward(
        self,
        stress_pred: torch.Tensor,
        stress_gt: torch.Tensor,
        breach_logits: torch.Tensor,
        breach_gt: torch.Tensor,
        vision_emb: torch.Tensor,
        graph_emb: torch.Tensor,
        temporal_emb: torch.Tensor,
        forecast_pred: Optional[torch.Tensor] = None,
        forecast_gt: Optional[torch.Tensor] = None,
        stress_mask: Optional[torch.Tensor] = None,
        breach_mask: Optional[torch.Tensor] = None,
        forecast_mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, dict]:
        """
        Returns (total_loss, components_dict).
        """
        components: dict = {}
        batch = stress_pred.size(0)

        # ── Stress ──────────────────────────────────────
        stress_gt = stress_gt.to(stress_pred.device, dtype=stress_pred.dtype)
        if stress_mask is not None:
            stress_mask = stress_mask.to(stress_pred.device, dtype=stress_pred.dtype)

        stress_loss = self.mse(stress_pred, stress_gt)
        if stress_mask is not None:
            stress_loss = stress_loss * stress_mask
            denom = stress_mask.sum().clamp(min=1)
        else:
            denom = batch

        stress_loss = stress_loss.sum() / denom
        components["stress"] = stress_loss

        # ── Breach ──────────────────────────────────────
        breach_gt = breach_gt.to(breach_logits.device, dtype=breach_logits.dtype)
        if breach_mask is not None:
            breach_mask = breach_mask.to(breach_logits.device, dtype=breach_logits.dtype)

        breach_loss = self.bce(breach_logits, breach_gt)
        if breach_mask is not None:
            breach_loss = breach_loss * breach_mask
            denom = breach_mask.sum().clamp(min=1)
        else:
            denom = batch

        breach_loss = breach_loss.sum() / denom
        components["breach"] = breach_loss

        # ── Contrastive ────────────────────────────────
        contrastive_loss = self.contrastive(vision_emb, graph_emb, temporal_emb)
        components["contrastive"] = contrastive_loss

        # ── Forecast (optional) ────────────────────────
        forecast_loss_val = torch.tensor(0.0, device=stress_pred.device)
        if forecast_pred is not None and forecast_gt is not None:
            forecast_gt = forecast_gt.to(forecast_pred.device, dtype=forecast_pred.dtype)
            if forecast_mask is not None:
                forecast_mask = forecast_mask.to(forecast_pred.device, dtype=forecast_pred.dtype)

            fl = self.mse(forecast_pred, forecast_gt)
            if forecast_mask is not None:
                fl = fl * forecast_mask.unsqueeze(-1)
                denom = forecast_mask.sum().clamp(min=1)
            else:
                denom = batch
            forecast_loss_val = fl.sum() / denom
            components["forecast"] = forecast_loss_val

        # ── Combined ───────────────────────────────────
        total = (
            self.lambda_stress * stress_loss
            + self.lambda_breach * breach_loss
            + self.lambda_contrastive * contrastive_loss
            + self.lambda_forecast * forecast_loss_val
        )
        components["total"] = total.detach()

        return total, components
