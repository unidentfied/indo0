import os
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger("sindio.model_registry")

class ModelRegistry:
    def __init__(self):
        self.models: Dict[str, Any] = {}
        self.model_path = os.getenv("MODEL_PATH", "../../models/trained")

    async def load_models(self):
        """Load PyTorch checkpoints and embedding models on startup (non-blocking)."""
        import asyncio
        import torch

        model_files = {
            "urban_stress": "urban_stress_v1.pth",
            "mobility_forecast": "mobility_v2.pth",
            "water_demand": "water_demand_v1.pth",
        }

        loop = asyncio.get_event_loop()

        for name, filename in model_files.items():
            path = Path(self.model_path) / filename
            if path.exists():
                try:
                    checkpoint = await loop.run_in_executor(
                        None, lambda p=str(path): torch.load(p, map_location="cpu", weights_only=True)
                    )
                    size_kb = await loop.run_in_executor(None, lambda p=path: p.stat().st_size / 1024)
                    self.models[name] = {
                        "status": "loaded",
                        "path": str(path),
                        "model": checkpoint,
                    }
                    logger.info("Loaded model '%s' from %s (%.0f KB)", name, path, size_kb)
                except Exception as exc:
                    logger.warning("Failed to load model '%s' from %s: %s", name, path, exc)
                    self.models[name] = {"status": "failed", "path": str(path), "error": str(exc)}
            else:
                logger.info("Model file not found for '%s' at %s — using heuristic fallback", name, path)
                self.models[name] = {"status": "unavailable", "path": str(path)}

    async def unload_models(self):
        self.models.clear()

    def get_model(self, name: str) -> Optional[Dict[str, Any]]:
        return self.models.get(name)
