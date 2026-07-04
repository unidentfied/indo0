"""Sindio — Water Demand Forecast Model Training
==================================================
Trains an MLP for water demand forecasting across Nairobi wards.
Predicts consumption based on population, temperature, rainfall,
season, and day-of-week patterns.

Output: models/trained/water_demand_v1.pth
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

logger = logging.getLogger("sindio.training.water")
logging.basicConfig(level=logging.INFO)

_NAIROBI_WARDS_WATER = [
    {"name": "CBD", "population": 65000, "base_demand_m3": 39000},
    {"name": "Westlands", "population": 72000, "base_demand_m3": 43200},
    {"name": "Industrial_Area", "population": 28000, "base_demand_m3": 33600},
    {"name": "Eastleigh", "population": 95000, "base_demand_m3": 57000},
    {"name": "Karen", "population": 42000, "base_demand_m3": 25200},
    {"name": "Kibera", "population": 185000, "base_demand_m3": 111000},
    {"name": "Embakasi", "population": 125000, "base_demand_m3": 75000},
    {"name": "Kasarani", "population": 92000, "base_demand_m3": 55200},
    {"name": "Ruaraka", "population": 78000, "base_demand_m3": 46800},
    {"name": "Langata", "population": 58000, "base_demand_m3": 34800},
]

_SEASONAL_MULT = {
    1: 0.9, 2: 0.9, 3: 1.0, 4: 1.1, 5: 1.15,
    6: 1.1, 7: 1.05, 8: 1.0, 9: 1.0, 10: 1.05, 11: 1.0, 12: 0.95,
}


class WaterDataset(Dataset):
    def __init__(self, n_samples: int = 5000):
        self.samples = []
        rng = np.random.RandomState(42)
        for _ in range(n_samples):
            ward_idx = rng.randint(0, len(_NAIROBI_WARDS_WATER))
            ward = _NAIROBI_WARDS_WATER[ward_idx]
            month = rng.randint(1, 13)
            hour = rng.randint(0, 24)
            temp_c = rng.normal(22 + (month - 6) * 0.5, 3)
            rainfall_mm = max(0, rng.exponential(_SEASONAL_MULT[month] * 3))
            is_weekend = rng.random() < 2 / 7

            demand = ward["base_demand_m3"] * _SEASONAL_MULT[month]
            if hour in (6, 7, 8, 18, 19, 20):
                demand *= 1.3
            if temp_c > 28:
                demand *= 1.15
            if rainfall_mm > 5:
                demand *= 0.95
            if is_weekend:
                demand *= 0.9

            x = [
                ward_idx / len(_NAIROBI_WARDS_WATER),
                month / 12.0,
                hour / 24.0,
                temp_c / 40.0,
                rainfall_mm / 20.0,
                float(is_weekend),
            ]
            self.samples.append((x, demand / 150000.0))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        x, y = self.samples[idx]
        return torch.tensor(x, dtype=torch.float32), torch.tensor([y], dtype=torch.float32)


class WaterDemandMLP(nn.Module):
    def __init__(self, input_dim: int = 6, hidden: int = 128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden, hidden // 2),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden // 2, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        return self.net(x)


def train(output_dir: Path, n_samples: int = 5000, epochs: int = 30, device: str = "cpu") -> Dict[str, Any]:
    torch.manual_seed(42)
    np.random.seed(42)

    ds = WaterDataset(n_samples)
    train_size = int(0.8 * len(ds))
    train_ds, val_ds = torch.utils.data.random_split(ds, [train_size, len(ds) - train_size])

    train_dl = DataLoader(train_ds, batch_size=32, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=32)

    model = WaterDemandMLP().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    criterion = nn.MSELoss()

    best_loss = float("inf")
    best_state = None

    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        for x, y in train_dl:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            pred = model(x)
            loss = criterion(pred, y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for x, y in val_dl:
                x, y = x.to(device), y.to(device)
                val_loss += criterion(model(x), y).item()
        val_loss /= len(val_dl)

        logger.info("Epoch %d/%d | train_loss=%.4f | val_loss=%.4f", epoch + 1, epochs, total_loss / len(train_dl), val_loss)

        if val_loss < best_loss:
            best_loss = val_loss
            best_state = model.state_dict().copy()

    if best_state:
        model.load_state_dict(best_state)

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "water_demand_v1.pth"
    torch.save({
        "model_state_dict": model.state_dict(),
        "config": {"input_dim": 6, "hidden": 128},
        "val_loss": best_loss,
    }, path)
    logger.info("Model saved to %s (val_loss=%.4f)", path, best_loss)

    return {"model_path": str(path), "val_loss": best_loss}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--output-dir", type=str, default="../../models/trained")
    args = parser.parse_args()

    result = train(Path(args.output_dir), args.samples, args.epochs)
    print(json.dumps(result, indent=2))
