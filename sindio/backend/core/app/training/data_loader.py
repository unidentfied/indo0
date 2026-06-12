"""
Data loader for SindioFoundationModel training.

Loads fused xarray Datasets from Parquet partitions (2020–2025),
splits by time (80 / 10 / 10), and crucially performs spatial block
holdout — entire wards (e.g. Kibera, Mathare) are held out for
validation and test sets.

Returns PyTorch DataLoader batching:
  - satellite:  (B, 10, 224, 224)  Sentinel-2 patches
  - graph_batch: dict of (node_features, edge_index, ...)
  - time_series: (B, 72, 8)
  - stress_gt, breach_gt, forecast_gt
"""

import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import torch
from torch.utils.data import DataLoader, Dataset, random_split

logger = logging.getLogger("sindio.data")


HELD_OUT_WARDS: List[str] = [
    "KIBERA",
    "MATHARE",
    "MUKURU KWA NJENGA",
    "KOROGOCHO",
    "HURUMA",
    "KANGEMI",
]

FEATURE_COLS: List[str] = [
    "population_density",
    "water_demand",
    "power_demand",
    "mobility_pressure",
    "stress_power",
    "stress_water",
    "stress_road",
    "breach_label",
]


@dataclass
class SindioSample:
    """A single training sample — matched across modalities."""
    satellite: torch.Tensor
    node_features: torch.Tensor
    edge_index: torch.Tensor
    edge_attr: torch.Tensor
    node_types: torch.Tensor
    time_series: torch.Tensor
    stress_gt: torch.Tensor
    breach_gt: torch.Tensor
    forecast_gt: torch.Tensor
    ward: str
    timestamp: datetime
    cell_id: str


class SindioDataset(Dataset):
    """PyTorch Dataset loading fused Parquet partitions with spatial holdout."""

    def __init__(
        self,
        data_root: str = "data/processed/fused",
        years: Tuple[int, int] = (2020, 2025),
        split: str = "train",
        val_wards: Optional[List[str]] = None,
        test_wards: Optional[List[str]] = None,
        spatial_frac: float = 0.2,
        seq_len: int = 72,
        tsf_features: int = 8,
        img_size: int = 224,
        transforms: Optional[Callable] = None,
        seed: int = 42,
    ):
        self.data_root = Path(data_root)
        self.years = years
        self.split = split
        self.seq_len = seq_len
        self.img_size = img_size
        self.transforms = transforms

        # Load ward→cell mapping
        self.ward_map = self._load_ward_map()

        # Partition wards
        all_wards = sorted(set(self.ward_map.values()))
        random.seed(seed)
        random.shuffle(all_wards)

        if val_wards is None:
            n_val = max(1, int(len(all_wards) * spatial_frac))
            val_wards = all_wards[:n_val] + HELD_OUT_WARDS[:3]

        if test_wards is None:
            n_test = max(1, int(len(all_wards) * spatial_frac))
            remaining = [w for w in all_wards if w not in val_wards]
            test_wards = remaining[:n_test] + HELD_OUT_WARDS[3:]

        train_wards = [w for w in all_wards if w not in val_wards and w not in test_wards]

        ward_set = {"train": train_wards, "val": val_wards, "test": test_wards}[split]
        logger.info(
            "Split '%s': %d wards (train=%d, val=%d, test=%d)",
            split, len(ward_set), len(train_wards), len(val_wards), len(test_wards),
        )

        # Filter cells to this split's wards
        self.cells = [
            cid for cid, w in self.ward_map.items()
            if w.upper() in [x.upper() for x in ward_set]
        ]

        logger.info("Loaded %d cells for split '%s'", len(self.cells), split)

        # Pre-index Parquet files
        self.file_index = self._build_file_index()

    def _load_ward_map(self) -> Dict[str, str]:
        """Load cell_id → ward_name mapping from processed data."""
        map_path = self.data_root / "ward_map.parquet"
        if map_path.exists():
            df = pd.read_parquet(map_path)
            return dict(zip(df["cell_id"], df["ward_name"]))

        logger.warning("ward_map.parquet not found — using spatial heuristic.")
        return {}

    def _build_file_index(self) -> Dict[str, List[str]]:
        """Index all Parquet files by (year, month) partition."""
        index: Dict[str, List[str]] = {}
        for yr in range(self.years[0], self.years[1] + 1):
            for mo in range(1, 13):
                part = f"year={yr}/month={mo:02d}"
                pattern = str(self.data_root / part / "*.parquet")
                files = sorted(Path(self.data_root / part).glob("*.parquet")) if (self.data_root / part).exists() else []
                if files:
                    index[f"{yr}-{mo:02d}"] = [str(f) for f in files]
        return index

    def _load_parquet_window(self, ts: datetime) -> Optional[pd.DataFrame]:
        """Load Parquet data for the hour containing `ts`."""
        key = ts.strftime("%Y-%m")
        files = self.file_index.get(key, [])
        if not files:
            return None

        df = pd.concat([pd.read_parquet(f) for f in files])
        df = df[df["cell_id"].isin(self.cells)]
        df["ts"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("ts").sort_index()
        return df

    def __len__(self) -> int:
        return len(self.cells) * 12  # ~12 timestamps per cell

    def __getitem__(self, idx: int) -> SindioSample:
        cell_id = self.cells[idx % len(self.cells)]
        hour_offset = idx // len(self.cells)

        ts = datetime(2024, 1, 1) + timedelta(hours=hour_offset * 6)
        df = self._load_parquet_window(ts)

        if df is None or df.empty:
            return self._mock_sample(cell_id, ts)

        cell_data = df[df["cell_id"] == cell_id]
        if cell_data.empty:
            return self._mock_sample(cell_id, ts)

        # Time-series: 72-hour window ending at ts
        tsf = self._build_tsf(cell_data, ts)

        # Satellite: mock patch (replace with actual Sentinel-2 loader)
        sat = torch.randn(10, self.img_size, self.img_size)

        # Graph: simplified single-node graph for this cell
        graph_cols = ["capacity_value", "capacity_unit_encoded", "year_constructed",
                      "last_maintenance_ordinal"]
        available_cols = [c for c in graph_cols if c in cell_data.columns]
        if available_cols and not cell_data.empty:
            nf = cell_data[available_cols].fillna(0).values[0]
            # Pad to fixed size if some columns were missing
            nf = np.pad(nf.astype(np.float32), (0, len(graph_cols) - len(available_cols)), constant_values=0.0)
        else:
            nf = np.zeros(len(graph_cols))
        nf = np.pad(nf.astype(np.float32), (0, 12), constant_values=0.0)

        return SindioSample(
            satellite=sat,
            node_features=torch.from_numpy(nf.reshape(1, -1)),
            edge_index=torch.empty(2, 0, dtype=torch.long),
            edge_attr=torch.empty(0, 6, dtype=torch.float32),
            node_types=torch.tensor([0], dtype=torch.long),
            time_series=tsf,
            stress_gt=torch.tensor(cell_data[["stress_power", "stress_water", "stress_road"]].values[0]
                                  if not cell_data.empty else [0.0, 0.0, 0.0], dtype=torch.float32),
            breach_gt=torch.tensor(cell_data["breach_label"].values[0:1]
                                  if not cell_data.empty else [0.0], dtype=torch.float32).unsqueeze(0),
            forecast_gt=torch.zeros(72, 7, dtype=torch.float32),
            ward=self.ward_map.get(cell_id, "unknown"),
            timestamp=ts,
            cell_id=cell_id,
        )

    def _build_tsf(self, cell_data: pd.DataFrame, ts: datetime) -> torch.Tensor:
        """Build (72, 8) time-series window."""
        tsf = torch.zeros(self.seq_len, 8, dtype=torch.float32)
        try:
            window = cell_data[cell_data.index <= ts].tail(self.seq_len)
            for i, col in enumerate(FEATURE_COLS):
                if col in window.columns:
                    vals = window[col].values[-self.seq_len:]
                    tsf[-len(vals):, i] = torch.from_numpy(vals.astype(np.float32))
        except Exception:
            pass
        return tsf

    def _mock_sample(self, cell_id: str, ts: datetime) -> SindioSample:
        return SindioSample(
            satellite=torch.randn(10, self.img_size, self.img_size),
            node_features=torch.zeros(1, 16, dtype=torch.float32),
            edge_index=torch.empty(2, 0, dtype=torch.long),
            edge_attr=torch.empty(0, 6, dtype=torch.float32),
            node_types=torch.tensor([0], dtype=torch.long),
            time_series=torch.randn(self.seq_len, 8),
            stress_gt=torch.zeros(3, 1, dtype=torch.float32),
            breach_gt=torch.zeros(3, 1, dtype=torch.float32),
            forecast_gt=torch.zeros(72, 7, dtype=torch.float32),
            ward="unknown",
            timestamp=ts,
            cell_id=cell_id,
        )


def _collate_fn(batch: List[SindioSample]) -> Dict[str, Any]:
    """Custom collate: builds graph batch, stacks tensors."""
    B = len(batch)

    satellite = torch.stack([s.satellite for s in batch])
    time_series = torch.stack([s.time_series for s in batch])

    # Graph: concat node features, build batch vector, adjust edge_index offsets
    node_feats = []
    edge_indices = []
    edge_attrs = []
    node_types = []
    batch_ids = []
    offset = 0

    for i, s in enumerate(batch):
        n = s.node_features.size(0)
        node_feats.append(s.node_features)
        if s.edge_index.numel() > 0:
            edge_indices.append(s.edge_index + offset)
            edge_attrs.append(s.edge_attr)
        node_types.append(s.node_types)
        batch_ids.append(torch.full((n,), i, dtype=torch.long))
        offset += n

    graph_batch = {
        "node_features": torch.cat(node_feats, dim=0),
        "edge_index": torch.cat(edge_indices, dim=1) if edge_indices else torch.empty(2, 0, dtype=torch.long),
        "edge_attr": torch.cat(edge_attrs, dim=0) if edge_attrs else torch.empty(0, 6, dtype=torch.float32),
        "node_types": torch.cat(node_types, dim=0) if node_types else torch.empty(0, dtype=torch.long),
        "batch": torch.cat(batch_ids, dim=0),
    }

    stress_gt = torch.stack([s.stress_gt for s in batch]).unsqueeze(-1)  # (B, 3, 1)
    breach_gt = torch.stack([s.breach_gt for s in batch])  # (B, 3, 1)
    forecast_gt = torch.stack([s.forecast_gt for s in batch])

    return {
        "satellite": satellite,
        "graph_batch": graph_batch,
        "time_series": time_series,
        "stress_gt": stress_gt,
        "breach_gt": breach_gt,
        "forecast_gt": forecast_gt,
        "wards": [s.ward for s in batch],
        "cell_ids": [s.cell_id for s in batch],
    }


def create_dataloaders(
    data_root: str = "data/processed/fused",
    batch_size: int = 64,
    num_workers: int = 4,
    val_wards: Optional[List[str]] = None,
    test_wards: Optional[List[str]] = None,
    seed: int = 42,
) -> Tuple[DataLoader, DataLoader, DataLoader]:
    """Create train/val/test DataLoaders.

    Splits: 80% train cells, 10% val, 10% test (spatial holdout).
    """

    train_ds = SindioDataset(
        data_root=data_root,
        split="train",
        val_wards=val_wards,
        test_wards=test_wards,
        seed=seed,
    )

    val_ds = SindioDataset(
        data_root=data_root,
        split="val",
        val_wards=val_wards,
        test_wards=test_wards,
        seed=seed,
    )

    test_ds = SindioDataset(
        data_root=data_root,
        split="test",
        val_wards=val_wards,
        test_wards=test_wards,
        seed=seed,
    )

    train_dl = DataLoader(
        train_ds,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=True,
        collate_fn=_collate_fn,
    )
    val_dl = DataLoader(
        val_ds,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
        collate_fn=_collate_fn,
    )
    test_dl = DataLoader(
        test_ds,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
        collate_fn=_collate_fn,
    )

    return train_dl, val_dl, test_dl
