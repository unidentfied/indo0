"""Sindio — Stress Model Training Pipeline
==========================================
Generates synthetic-but-realistic training data and trains the
urban-stress prediction model using the existing SindioFoundationModel.

Usage:
  cd backend/core && poetry run python app/training/train_stress_model.py --epochs 100
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

logger = logging.getLogger("sindio.training.stress_model")
logging.basicConfig(level=logging.INFO)

# ── Configuration ────────────────────────────────────────────

@dataclass
class TrainingConfig:
    epochs: int = 50
    batch_size: int = 32
    learning_rate: float = 1e-4
    weight_decay: float = 1e-3
    patience: int = 10
    min_delta: float = 0.001
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    synthetic_samples: int = 50000
    output_dir: Path = Path("../../models/trained")
    seed: int = 42

    def __post_init__(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)


# ── Synthetic Data Generator ───────────────────────────────────

_SYNTHETIC_WARDS = [
    "Kilimani", "Upper Hill", "CBD", "Westlands", "Industrial Area",
    "Eastleigh", "Karen", "Parklands", "Langata", "Ngong Road",
    "Kibera", "South B", "South C", "Donholm", "Embakasi",
    "Ruaraka", "Kasarani", "Dagoretti", "Mathare", "Huruma",
    "Githurai", "Roysambu", "Kahawa", "Komarock", "Umoja",
]

_INFRA_TYPES = ["power", "water", "roads", "solid_waste", "sidewalks", "lrt", "sgr", "airports"]


def _generate_stress_labels() -> pd.DataFrame:
    """Generate realistic stress distribution matching known Nairobi patterns."""
    rng = np.random.RandomState(42)
    n = 50000

    records: list[dict] = []
    for i in range(n):
        infra = rng.choice(_INFRA_TYPES)
        ward = rng.choice(_SYNTHETIC_WARDS)
        lat = rng.uniform(-1.45, -1.15)
        lon = rng.uniform(36.65, 37.05)

        # Time-based seasonality
        hour = rng.randint(0, 24)
        month = rng.randint(1, 13)
        is_weekend = rng.randint(0, 7) >= 5
        is_wet = month in (3, 4, 5, 10, 11)

        # Base stress varies by infrastructure type
        base_stress = {
            "power": 0.40, "water": 0.35, "roads": 0.55,
            "solid_waste": 0.25, "sidewalks": 0.30, "lrt": 0.45,
            "sgr": 0.35, "airports": 0.30,
        }.get(infra, 0.30)

        # Peak hour multipliers
        if infra in ("power", "water") and hour in (7, 8, 19, 20):
            hour_mult = 1.3
        elif infra == "roads" and hour in (7, 8, 9, 17, 18, 19):
            hour_mult = 1.5
        elif infra == "lrt" and hour in (7, 8, 17, 18):
            hour_mult = 1.4
        else:
            hour_mult = 0.9

        if is_weekend and infra in ("roads", "lrt", "airports"):
            weekend_mult = 1.2
        elif is_weekend:
            weekend_mult = 0.8
        else:
            weekend_mult = 1.0

        wet_mult = 0.9 if is_wet else 1.1

        # Population density effect (higher near CBD)
        dist_cbd = ((lat + 1.286) ** 2 + (lon - 36.823) ** 2) ** 0.5
        density_factor = max(0.5, min(2.0, 1.5 - dist_cbd * 3.0))

        stress = base_stress * hour_mult * weekend_mult * wet_mult * density_factor
        stress = rng.normal(stress, 0.08)
        stress = max(0.0, min(1.0, stress))

        # Classify into breach levels
        breach_label = 0 if stress < 0.6 else (1 if stress < 0.8 else (2 if stress < 0.9 else 3))

        records.append({
            "cell_id": i,
            "infrastructure_type": infra,
            "ward": ward,
            "lat": lat,
            "lon": lon,
            "hour": hour,
            "month": month,
            "is_weekend": is_weekend,
            "is_wet": is_wet,
            "population_density_km2": int(density_factor * 5000 + rng.normal(0, 500)),
            "dist_cbd_km": dist_cbd * 111.0,
            "stress_target": stress,
            "breach_label": breach_label,
        })

    return pd.DataFrame(records)


# ── Dataset ────────────────────────────────────────────────────

class StressDataset(Dataset):
    """Tabular dataset for stress prediction."""

    def __init__(self, df: pd.DataFrame):
        self.df = df.reset_index(drop=True)
        self.infra_map = {t: i for i, t in enumerate(_INFRA_TYPES)}
        self.ward_map = {w: i for i, w in enumerate(_SYNTHETIC_WARDS)}

    def __len__(self) -> int:
        return len(self.df)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        row = self.df.iloc[idx]

        x = torch.tensor([
            self.infra_map.get(row["infrastructure_type"], 0) / 8.0,
            row["hour"] / 24.0,
            row["month"] / 12.0,
            float(row["is_weekend"]),
            float(row["is_wet"]),
            row["population_density_km2"] / 10000.0,
            row["dist_cbd_km"] / 20.0,
            row["lat"] + 1.3,  # normalized around Nairobi
            row["lon"] - 36.8,
        ], dtype=torch.float32)

        y_stress = torch.tensor([row["stress_target"]], dtype=torch.float32)
        y_breach = torch.tensor(row["breach_label"], dtype=torch.long)

        return x, y_stress, y_breach


# ── Model ──────────────────────────────────────────────────────

class StressPredictor(nn.Module):
    """Lightweight MLP for stress prediction (standalone, no vision/graph)."""

    def __init__(self, input_dim: int = 9, hidden: int = 128):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
            nn.Linear(hidden // 2, 1),
            nn.Sigmoid(),
        )
        self.breach_head = nn.Sequential(
            nn.Linear(input_dim, hidden // 2),
            nn.ReLU(),
            nn.Linear(hidden // 2, 4),  # 4 breach classes
        )

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        return {
            "stress": self.mlp(x),
            "breach_logits": self.breach_head(x),
        }


# ── Training ───────────────────────────────────────────────────

class EarlyStopping:
    def __init__(self, patience: int = 10, min_delta: float = 0.001):
        self.patience = patience
        self.min_delta = min_delta
        self.best_loss = float("inf")
        self.counter = 0
        self.best_state: Optional[dict] = None

    def __call__(self, val_loss: float, model: nn.Module) -> bool:
        if val_loss < self.best_loss - self.min_delta:
            self.best_loss = val_loss
            self.counter = 0
            self.best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            return False
        self.counter += 1
        return self.counter >= self.patience


def train(config: TrainingConfig) -> dict[str, Any]:
    torch.manual_seed(config.seed)
    np.random.seed(config.seed)
    random.seed(config.seed)

    logger.info("Generating %d synthetic samples...", config.synthetic_samples)
    df = _generate_stress_labels()

    # Train/val/test split (80/10/10)
    n = len(df)
    train_end = int(n * 0.8)
    val_end = int(n * 0.9)

    train_ds = StressDataset(df.iloc[:train_end])
    val_ds = StressDataset(df.iloc[train_end:val_end])
    test_ds = StressDataset(df.iloc[val_end:])

    train_dl = DataLoader(train_ds, batch_size=config.batch_size, shuffle=True, num_workers=0)
    val_dl = DataLoader(val_ds, batch_size=config.batch_size, shuffle=False, num_workers=0)
    test_dl = DataLoader(test_ds, batch_size=config.batch_size, shuffle=False, num_workers=0)

    model = StressPredictor().to(config.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=config.epochs)
    stress_criterion = nn.MSELoss()
    breach_criterion = nn.CrossEntropyLoss()
    early_stop = EarlyStopping(patience=config.patience, min_delta=config.min_delta)

    best_metrics: dict[str, float] = {}

    for epoch in range(1, config.epochs + 1):
        model.train()
        total_loss = 0.0
        for x, y_stress, y_breach in train_dl:
            x = x.to(config.device)
            y_stress = y_stress.to(config.device)
            y_breach = y_breach.to(config.device)

            optimizer.zero_grad()
            out = model(x)
            loss = stress_criterion(out["stress"], y_stress) + 0.3 * breach_criterion(out["breach_logits"], y_breach)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            total_loss += loss.item()

        # Validation
        model.eval()
        val_loss = 0.0
        val_stress_mae = 0.0
        val_breach_correct = 0
        val_total = 0
        with torch.no_grad():
            for x, y_stress, y_breach in val_dl:
                x = x.to(config.device)
                out = model(x)
                val_loss += stress_criterion(out["stress"].cpu(), y_stress).item()
                preds = out["breach_logits"].argmax(dim=1).cpu()
                val_breach_correct += (preds == y_breach).sum().item()
                val_total += len(y_breach)
                val_stress_mae += (out["stress"].cpu() - y_stress).abs().sum().item()

        val_loss = val_loss / len(val_dl)
        val_stress_mae = val_stress_mae / val_total
        val_breach_acc = val_breach_correct / val_total

        scheduler.step()

        logger.info(
            "Epoch %d/%d | train_loss=%.4f | val_loss=%.4f | val_stress_mae=%.4f | breach_acc=%.3f | lr=%.2e",
            epoch, config.epochs, total_loss / len(train_dl), val_loss, val_stress_mae, val_breach_acc,
            optimizer.param_groups[0]["lr"],
        )

        if early_stop(val_loss, model):
            logger.info("Early stopping at epoch %d (best val_loss=%.4f)", epoch, early_stop.best_loss)
            break

        best_metrics = {
            "val_loss": val_loss,
            "val_stress_mae": val_stress_mae,
            "val_breach_acc": val_breach_acc,
        }

    # Restore best model
    if early_stop.best_state is not None:
        model.load_state_dict(early_stop.best_state)

    # Test evaluation
    model.eval()
    test_mae = 0.0
    test_breach_correct = 0
    test_total = 0
    with torch.no_grad():
        for x, y_stress, y_breach in test_dl:
            x = x.to(config.device)
            out = model(x)
            test_mae += (out["stress"].cpu() - y_stress).abs().sum().item()
            test_breach_correct += (out["breach_logits"].argmax(dim=1).cpu() == y_breach).sum().item()
            test_total += len(y_breach)

    test_mae = test_mae / test_total
    test_breach_acc = test_breach_correct / test_total

    logger.info("Test | stress_mae=%.4f | breach_acc=%.3f", test_mae, test_breach_acc)

    # Save model
    model_path = config.output_dir / "urban_stress_v1.pth"
    torch.save({
        "model_state_dict": model.state_dict(),
        "config": {
            "input_dim": 9,
            "hidden": 128,
            "infra_types": _INFRA_TYPES,
            "wards": _SYNTHETIC_WARDS,
        },
        "metrics": {
            "val_loss": best_metrics.get("val_loss", 0),
            "val_stress_mae": best_metrics.get("val_stress_mae", 0),
            "test_stress_mae": test_mae,
            "test_breach_acc": test_breach_acc,
        },
        "training": {
            "epochs_trained": epoch,
            "synthetic_samples": config.synthetic_samples,
            "seed": config.seed,
            "timestamp": time.time(),
        },
    }, model_path)
    logger.info("Model saved to %s", model_path)

    return {
        "model_path": str(model_path),
        "test_stress_mae": test_mae,
        "test_breach_acc": test_breach_acc,
        "epochs_trained": epoch,
    }


# ── CLI ────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Train Sindio urban-stress prediction model")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--samples", type=int, default=50000)
    parser.add_argument("--device", type=str, default="auto")
    parser.add_argument("--output-dir", type=str, default="../../models/trained")
    args = parser.parse_args()

    device = "cuda" if args.device == "auto" and torch.cuda.is_available() else (args.device if args.device != "auto" else "cpu")
    config = TrainingConfig(
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        synthetic_samples=args.samples,
        device=device,
        output_dir=Path(args.output_dir),
    )

    result = train(config)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
