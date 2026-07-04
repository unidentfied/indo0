"""Sindio — Mobility Forecast Model Training
==============================================
Trains a lightweight RNN/LSTM for Nairobi commuter mobility forecasting.
Predicts traffic volume, congestion, and public transit ridership
based on time-of-day, day-of-week, weather, and event data.

Output: models/trained/mobility_v2.pth
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
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

logger = logging.getLogger("sindio.training.mobility")
logging.basicConfig(level=logging.INFO)

_NAIROBI_WARDS = [
    "Kilimani", "Upper Hill", "CBD", "Westlands", "Industrial Area",
    "Eastleigh", "Karen", "Parklands", "Langata", "Ngong Road",
    "Kibera", "South B", "South C", "Donholm", "Embakasi",
]

_WEEKDAY_MULT = {
    "Monday": 1.0, "Tuesday": 1.05, "Wednesday": 1.0,
    "Thursday": 1.1, "Friday": 1.3, "Saturday": 0.8, "Sunday": 0.6,
}


class MobilityDataset(Dataset):
    def __init__(self, n_samples: int = 10000):
        self.samples = []
        rng = np.random.RandomState(42)
        for _ in range(n_samples):
            hour = rng.randint(0, 24)
            weekday = rng.choice(list(_WEEKDAY_MULT.keys()))
            ward = rng.choice(_NAIROBI_WARDS)
            is_rainy = rng.random() < 0.25
            is_event = rng.random() < 0.05

            base_volume = 500
            if hour in (7, 8, 17, 18, 19):
                base_volume = 2500
            elif hour in (9, 16):
                base_volume = 1500
            elif hour in (12, 13):
                base_volume = 1200
            elif 0 <= hour <= 5:
                base_volume = 100

            volume = base_volume * _WEEKDAY_MULT[weekday] * rng.uniform(0.8, 1.2)
            if is_rainy:
                volume *= 0.7
            if is_event:
                volume *= 1.5

            x = [
                hour / 24.0,
                list(_WEEKDAY_MULT.keys()).index(weekday) / 7.0,
                _NAIROBI_WARDS.index(ward) / len(_NAIROBI_WARDS),
                float(is_rainy),
                float(is_event),
                rng.uniform(-1.45, -1.15),  # lat
                rng.uniform(36.65, 37.05),  # lon
            ]
            self.samples.append((x, volume))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        x, y = self.samples[idx]
        return torch.tensor(x, dtype=torch.float32), torch.tensor([y / 5000.0], dtype=torch.float32)


class MobilityRNN(nn.Module):
    def __init__(self, input_dim: int = 7, hidden: int = 64):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden, batch_first=True, num_layers=2, dropout=0.2)
        self.fc = nn.Sequential(
            nn.Linear(hidden, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        # x shape: (batch, seq_len, features) — we use single timestep as seq
        x = x.unsqueeze(1)
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :])


def train(output_dir: Path, n_samples: int = 10000, epochs: int = 30, device: str = "cpu") -> Dict[str, Any]:
    torch.manual_seed(42)
    np.random.seed(42)

    ds = MobilityDataset(n_samples)
    train_size = int(0.8 * len(ds))
    train_ds, val_ds = torch.utils.data.random_split(ds, [train_size, len(ds) - train_size])

    train_dl = DataLoader(train_ds, batch_size=64, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=64)

    model = MobilityRNN().to(device)
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

        # Validation
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for x, y in val_dl:
                x, y = x.to(device), y.to(device)
                pred = model(x)
                val_loss += criterion(pred, y).item()
        val_loss /= len(val_dl)

        logger.info("Epoch %d/%d | train_loss=%.4f | val_loss=%.4f", epoch + 1, epochs, total_loss / len(train_dl), val_loss)

        if val_loss < best_loss:
            best_loss = val_loss
            best_state = model.state_dict().copy()

    if best_state:
        model.load_state_dict(best_state)

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "mobility_v2.pth"
    torch.save({
        "model_state_dict": model.state_dict(),
        "config": {"input_dim": 7, "hidden": 64},
        "val_loss": best_loss,
    }, path)
    logger.info("Model saved to %s (val_loss=%.4f)", path, best_loss)

    return {"model_path": str(path), "val_loss": best_loss}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=10000)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--output-dir", type=str, default="../../models/trained")
    args = parser.parse_args()

    result = train(Path(args.output_dir), args.samples, args.epochs)
    print(json.dumps(result, indent=2))
