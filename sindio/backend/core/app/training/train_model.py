"""
train_model.py — Full training script for SindioFoundationModel.

Loads fused data 2020–2025, splits by time (80/10/10) with spatial
block holdout (entire wards held out for validation / test).

Logs to MLflow: metrics, checkpoints, hyperparameters.
After each epoch, saves per-infrastructure-type MAE, confusion matrix,
and geospatial error map as PNG.

Saves final model to models/trained/sindio_foundation_v1.pt

Usage:
    python -m app.training.train_model
    # or with accelerate:
    accelerate launch --num_processes=4 app/training/train_model.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from tqdm import tqdm

try:
    import mlflow
    import mlflow.pytorch
    HAS_MLFLOW = True
except ImportError:
    HAS_MLFLOW = False

from app.models.sindio_foundation import SindioFoundationModel
from app.models.losses import SindioLoss
from app.training.data_loader import create_dataloaders

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
logger = logging.getLogger("train_model")

# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────
MODEL_OUTPUT = Path("models/trained/sindio_foundation_v1.pt")
ARTIFACT_DIR = Path("models/trained/artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

HELD_OUT_WARDS = {
    "val": ["KIBERA", "KOROGOCHO", "HURUMA"],
    "test": ["MATHARE", "MUKURU KWA NJENGA", "KANGEMI"],
}

HYPERPARAMS = {
    "learning_rate": 1e-4,
    "batch_size": 64,
    "epochs": 50,
    "patience": 5,
    "lambda_stress": 1.0,
    "lambda_breach": 2.0,
    "lambda_contrastive": 0.1,
    "lambda_forecast": 1.5,
    "weight_decay": 1e-2,
    "latent_dim": 1024,
    "seq_len": 72,
    "forecast_len": 72,
    "num_stress_types": 3,
    "spatial_holdout": True,
    "data_years": "2020-2025",
}

INFRA_TYPES = ["power", "water", "road"]


# ──────────────────────────────────────────────────────────────
# Metrics
# ──────────────────────────────────────────────────────────────


def compute_per_type_mae(
    stress_pred: torch.Tensor, stress_gt: torch.Tensor
) -> Dict[str, float]:
    """Per-infrastructure-type MAE on stress predictions."""
    mae_per_type: Dict[str, float] = {}
    for i, label in enumerate(INFRA_TYPES):
        pred = stress_pred[:, i, :]
        gt = stress_gt[:, i, :]
        mask = gt > -0.5  # exclude missing
        if mask.sum() > 0:
            mae = (pred[mask] - gt[mask]).abs().mean().item()
        else:
            mae = float("nan")
        mae_per_type[label] = mae
    return mae_per_type


def confusion_matrix_breach(
    breach_logits: torch.Tensor, breach_gt: torch.Tensor, threshold: float = 0.5
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute confusion matrix counts for breach classifier."""
    probs = torch.sigmoid(breach_logits)
    preds = (probs > threshold).long()
    gt = breach_gt.long()

    tp = (preds * gt).sum().item()
    fp = (preds * (1 - gt)).sum().item()
    fn = ((1 - preds) * gt).sum().item()
    tn = ((1 - preds) * (1 - gt)).sum().item()

    cm = np.array([[tn, fp], [fn, tp]])
    metrics = {
        "accuracy": (tp + tn) / max(tp + tn + fp + fn, 1),
        "precision": tp / max(tp + fp, 1),
        "recall": tp / max(tp + fn, 1),
        "f1": (2 * tp) / max(2 * tp + fp + fn, 1),
    }
    return cm, metrics


def save_breach_cm(cm: np.ndarray, epoch: int) -> Path:
    """Save confusion matrix as PNG."""
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.matshow(cm, cmap="Blues", alpha=0.8)
    for i in range(2):
        for j in range(2):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center", fontsize=14, fontweight="bold")
    ax.set_xticklabels([""] + ["No Breach", "Breach"])
    ax.set_yticklabels([""] + ["No Breach", "Breach"])
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title(f"Breach Confusion Matrix — Epoch {epoch}")
    p = ARTIFACT_DIR / f"breach_cm_epoch_{epoch:03d}.png"
    fig.savefig(p, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return p


def save_error_map(
    cell_ids: List[str],
    stress_pred: torch.Tensor,
    stress_gt: torch.Tensor,
    ward_names: List[str],
    epoch: int,
    bbox: Tuple[float, float, float, float] = (36.7, -1.4, 37.1, -1.2),
) -> Path:
    """Plot geospatial error map over Nairobi extent.

    Each cell is colored by its mean absolute stress error.
    """
    errors = (stress_pred - stress_gt).abs().mean(dim=1)  # (B,)
    errors_np = errors.cpu().numpy()

    # Use ward colors for reference
    from collections import defaultdict

    unique_wards = sorted(set(ward_names))
    color_map = {w: plt.cm.tab20(i % 20) for i, w in enumerate(unique_wards)}

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_xlim(bbox[0], bbox[2])
    ax.set_ylim(bbox[1], bbox[3])
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(f"Stress MAE per Cell — Epoch {epoch}")

    # Simulate cell positions (in production, derive from cell_id)
    np.random.seed(42)
    xs = np.random.uniform(bbox[0], bbox[2], len(cell_ids))
    ys = np.random.uniform(bbox[1], bbox[3], len(cell_ids))

    scatter = ax.scatter(
        xs, ys, c=errors_np, cmap="YlOrRd", s=40, edgecolors="none",
        vmin=0, vmax=0.5, alpha=0.9,
    )
    cbar = fig.colorbar(scatter, ax=ax, shrink=0.8)
    cbar.set_label("Stress MAE")

    # Ward labels
    for i, w in enumerate(unique_wards):
        mask = [n == w for n in ward_names]
        if any(mask):
            cx = np.mean([xs[j] for j, m in enumerate(mask) if m])
            cy = np.mean([ys[j] for j, m in enumerate(mask) if m])
            ax.annotate(
                w[:12],
                (cx, cy),
                fontsize=6,
                ha="center",
                color="black",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.6),
            )

    p = ARTIFACT_DIR / f"error_map_epoch_{epoch:03d}.png"
    fig.savefig(p, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return p


# ──────────────────────────────────────────────────────────────
# Early Stopping
# ──────────────────────────────────────────────────────────────


class EarlyStopping:
    def __init__(self, patience: int = 5, min_delta: float = 1e-4):
        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.best_score: Optional[float] = None
        self.early_stop = False

    def step(self, val_loss: float) -> bool:
        score = -val_loss
        if self.best_score is None:
            self.best_score = score
            return False
        if score < self.best_score + self.min_delta:
            self.counter += 1
            if self.counter >= self.patience:
                self.early_stop = True
                return True
        else:
            self.best_score = score
            self.counter = 0
        return False


# ──────────────────────────────────────────────────────────────
# Main Training
# ──────────────────────────────────────────────────────────────


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Using device: %s", device)

    # ── MLflow setup ─────────────────────────────────────
    if HAS_MLFLOW:
        mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
        mlflow.set_experiment("sindio_foundation")
        mlflow.start_run(run_name=f"sindio_v1_{datetime.now().strftime('%Y%m%d_%H%M')}")
        mlflow.log_params(HYPERPARAMS)
        logger.info("MLflow tracking enabled.")
    else:
        logger.warning("MLflow not installed — logging locally only.")

    # ── Data ─────────────────────────────────────────────
    logger.info("Loading fused data (2020–2025) with spatial holdout…")
    train_dl, val_dl, test_dl = create_dataloaders(
        data_root=os.getenv("DATA_PROCESSED_DIR", "data/processed/fused"),
        batch_size=HYPERPARAMS["batch_size"],
        val_wards=HELD_OUT_WARDS["val"],
        test_wards=HELD_OUT_WARDS["test"],
    )

    logger.info("Train batches: %d  |  Val batches: %d  |  Test batches: %d",
                len(train_dl), len(val_dl), len(test_dl))

    # ── Model ────────────────────────────────────────────
    model = SindioFoundationModel(
        latent_dim=HYPERPARAMS["latent_dim"],
        temporal_seq_len=HYPERPARAMS["seq_len"],
        forecast_len=HYPERPARAMS["forecast_len"],
        num_stress_types=HYPERPARAMS["num_stress_types"],
    ).to(device)

    param_count = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info("Model parameters: %d total, %d trainable", param_count, trainable)

    # ── Optimiser & Loss ─────────────────────────────────
    optimiser = torch.optim.AdamW(
        model.parameters(),
        lr=HYPERPARAMS["learning_rate"],
        weight_decay=HYPERPARAMS["weight_decay"],
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimiser, T_max=HYPERPARAMS["epochs"], eta_min=1e-7
    )
    criterion = SindioLoss(
        lambda_stress=HYPERPARAMS["lambda_stress"],
        lambda_breach=HYPERPARAMS["lambda_breach"],
        lambda_contrastive=HYPERPARAMS["lambda_contrastive"],
        lambda_forecast=HYPERPARAMS["lambda_forecast"],
    )

    # ── Training loop ────────────────────────────────────
    early_stopper = EarlyStopping(patience=HYPERPARAMS["patience"])
    best_val_mae = float("inf")
    train_history: List[Dict[str, Any]] = []

    for epoch in range(1, HYPERPARAMS["epochs"] + 1):
        # ─── Train ─────────────────────────────────────
        model.train()
        epoch_losses: Dict[str, float] = {"stress": 0.0, "breach": 0.0, "contrastive": 0.0, "forecast": 0.0, "total": 0.0}
        train_steps = 0

        pbar = tqdm(train_dl, desc=f"Epoch {epoch:3d}", leave=False)
        for batch in pbar:
            satellite = batch["satellite"].to(device)
            graph_batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch["graph_batch"].items()}
            time_series = batch["time_series"].to(device)
            stress_gt = batch["stress_gt"].to(device)
            breach_gt = batch["breach_gt"].to(device)
            forecast_gt = batch["forecast_gt"].to(device)

            outputs = model(
                satellite=satellite,
                graph_batch=graph_batch,
                time_series=time_series,
                return_embeddings=True,
            )

            loss, components = criterion(
                stress_pred=outputs["stress"],
                stress_gt=stress_gt,
                breach_logits=outputs["breach_logits"],
                breach_gt=breach_gt,
                vision_emb=outputs["vision_emb"],
                graph_emb=outputs["graph_emb"],
                temporal_emb=outputs["temporal_emb"],
                forecast_pred=outputs.get("forecast"),
                forecast_gt=forecast_gt,
            )

            optimiser.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimiser.step()

            for k in epoch_losses:
                epoch_losses[k] += components.get(k, torch.tensor(0.0)).item()
            train_steps += 1

            pbar.set_postfix({
                "loss": f"{loss.item():.4f}",
                "stress": f"{components.get('stress', torch.tensor(0.0)).item():.4f}",
            })

        for k in epoch_losses:
            epoch_losses[k] /= max(train_steps, 1)

        scheduler.step()

        # ─── Validation ─────────────────────────────────
        val_metrics = evaluate(model, val_dl, criterion, device, epoch)
        val_mae = val_metrics["mae_mean"]

        # ─── MLflow Logging ─────────────────────────────
        lr = optimiser.param_groups[0]["lr"]
        log_entry = {
            "epoch": epoch,
            "lr": lr,
            **{f"train_{k}": v for k, v in epoch_losses.items()},
            **{f"val_{k}": v for k, v in val_metrics.items()},
        }
        train_history.append(log_entry)

        if HAS_MLFLOW:
            mlflow.log_metrics(log_entry, step=epoch)

            # Log artifacts every 5 epochs
            if epoch % 5 == 0 or epoch == 1:
                cm_path = ARTIFACT_DIR / f"breach_cm_epoch_{epoch:03d}.png"
                map_path = ARTIFACT_DIR / f"error_map_epoch_{epoch:03d}.png"
                if cm_path.exists():
                    mlflow.log_artifact(str(cm_path), "confusion_matrices")
                if map_path.exists():
                    mlflow.log_artifact(str(map_path), "error_maps")

        logger.info(
            "Epoch %3d | Train total=%.4f  Val MAE=%.4f  LR=%.2e",
            epoch, epoch_losses["total"], val_mae, lr,
        )

        # ─── Early stopping ─────────────────────────────
        if val_mae < best_val_mae:
            best_val_mae = val_mae
            torch.save(model.state_dict(), MODEL_OUTPUT)
            logger.info("  → Best model saved (val MAE=%.4f)", best_val_mae)

        if early_stopper.step(val_mae):
            logger.info("Early stopping triggered at epoch %d.", epoch)
            break

    # ── Test evaluation ──────────────────────────────────
    logger.info("Training complete. Running final test evaluation…")
    model.load_state_dict(torch.load(MODEL_OUTPUT, map_location=device))
    test_metrics = evaluate(model, test_dl, criterion, device, epoch=None, label="test")

    logger.info("Test results:")
    for k, v in test_metrics.items():
        logger.info("  %s: %.4f", k, v)

    if HAS_MLFLOW:
        mlflow.log_metrics({f"test_{k}": v for k, v in test_metrics.items()})
        mlflow.pytorch.log_model(model, "model")
        mlflow.end_run()

    logger.info("Final model saved to %s", MODEL_OUTPUT)
    return model, train_history, test_metrics


def evaluate(
    model: SindioFoundationModel,
    dataloader: DataLoader,
    criterion: SindioLoss,
    device: torch.device,
    epoch: Optional[int] = None,
    label: str = "val",
) -> Dict[str, float]:
    """Run full evaluation: loss, per-type MAE, breach CM, error map."""
    model.eval()
    total_losses = {"total": 0.0}
    all_stress_pred, all_stress_gt = [], []
    all_breach_logits, all_breach_gt = [], []
    all_cell_ids: List[str] = []
    all_wards: List[str] = []
    steps = 0

    with torch.no_grad():
        for batch in tqdm(dataloader, desc=f"{label} eval", leave=False):
            satellite = batch["satellite"].to(device)
            graph_batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch["graph_batch"].items()}
            time_series = batch["time_series"].to(device)
            stress_gt = batch["stress_gt"].to(device)
            breach_gt = batch["breach_gt"].to(device)
            forecast_gt = batch["forecast_gt"].to(device)

            outputs = model(
                satellite=satellite,
                graph_batch=graph_batch,
                time_series=time_series,
                return_embeddings=True,
            )

            loss, components = criterion(
                stress_pred=outputs["stress"],
                stress_gt=stress_gt,
                breach_logits=outputs["breach_logits"],
                breach_gt=breach_gt,
                vision_emb=outputs["vision_emb"],
                graph_emb=outputs["graph_emb"],
                temporal_emb=outputs["temporal_emb"],
                forecast_pred=outputs.get("forecast"),
                forecast_gt=forecast_gt,
            )

            total_losses["total"] += loss.item()
            for k, v in components.items():
                if k not in total_losses:
                    total_losses[k] = 0.0
                total_losses[k] += v.item()

            all_stress_pred.append(outputs["stress"].cpu())
            all_stress_gt.append(stress_gt.cpu())
            all_breach_logits.append(outputs["breach_logits"].cpu())
            all_breach_gt.append(breach_gt.cpu())
            all_cell_ids.extend(batch.get("cell_ids", []))
            all_wards.extend(batch.get("wards", []))

            steps += 1

    for k in total_losses:
        total_losses[k] /= max(steps, 1)

    # Per-type MAE
    stress_pred_cat = torch.cat(all_stress_pred, dim=0)
    stress_gt_cat = torch.cat(all_stress_gt, dim=0)
    per_type = compute_per_type_mae(stress_pred_cat, stress_gt_cat)

    # Breach confusion matrix
    breach_cat = torch.cat(all_breach_logits, dim=0)
    breach_gt_cat = torch.cat(all_breach_gt, dim=0)
    cm, breach_m = confusion_matrix_breach(breach_cat, breach_gt_cat)

    # Geospatial error map
    if epoch is not None and all_cell_ids:
        map_path = save_error_map(all_cell_ids, stress_pred_cat, stress_gt_cat, all_wards, epoch)
    if epoch is not None:
        save_breach_cm(cm, epoch)

    metrics: Dict[str, float] = {
        "mae_power": per_type.get("power", float("nan")),
        "mae_water": per_type.get("water", float("nan")),
        "mae_road": per_type.get("road", float("nan")),
        "mae_mean": np.nanmean(list(per_type.values())),
        "breach_accuracy": breach_m["accuracy"],
        "breach_precision": breach_m["precision"],
        "breach_recall": breach_m["recall"],
        "breach_f1": breach_m["f1"],
        **total_losses,
    }

    return metrics


if __name__ == "__main__":
    main()
