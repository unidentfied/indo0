import os
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger("sindio.model_registry")

class ModelRegistry:
    def __init__(self):
        self.models: Dict[str, Any] = {}
        self.model_path = os.getenv("MODEL_PATH", "../../models/trained")
        self.embeddings_path = os.getenv("EMBEDDINGS_PATH", "../../models/embeddings")

    async def load_models(self):
        """Load PyTorch checkpoints and verify embedding configs on startup."""
        import asyncio
        try:
            import torch
        except ImportError:
            torch = None

        model_files = {
            "urban_stress": "urban_stress_v1.pth",
            "mobility_forecast": "mobility_v2.pth",
            "water_demand": "water_demand_v1.pth",
        }

        loop = asyncio.get_event_loop()

        for name, filename in model_files.items():
            path = Path(self.model_path) / filename
            if path.exists() and torch is not None:
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

        embedding_config = Path(self.embeddings_path) / "all-MiniLM-L6-v2" / "config.json"
        embedding_weights = Path(self.embeddings_path) / "all-MiniLM-L6-v2" / "model.safetensors"
        if embedding_config.exists():
            if embedding_weights.exists():
                self.models["embeddings"] = {
                    "status": "loaded",
                    "path": str(embedding_weights),
                }
                logger.info("Embedding model ready at %s", embedding_weights)
            else:
                self.models["embeddings"] = {
                    "status": "pending",
                    "path": str(embedding_config),
                    "note": "weights not present — will download from HuggingFace at first use",
                }
                logger.info(
                    "Embedding config found at %s — weights will download from HuggingFace at runtime",
                    embedding_config,
                )
        else:
            self.models["embeddings"] = {
                "status": "unavailable",
                "path": str(embedding_config),
            }
            logger.warning("Embedding config missing at %s — sentence embeddings disabled", embedding_config)

    async def unload_models(self):
        self.models.clear()

    @property
    def loaded_count(self) -> int:
        return sum(1 for name, m in self.models.items()
                   if name != "embeddings" and m.get("status") == "loaded")

    @property
    def trained_total(self) -> int:
        return sum(1 for name in self.models if name != "embeddings")

    @property
    def embeddings_ready(self) -> bool:
        emb = self.models.get("embeddings", {})
        return emb.get("status") == "loaded"

    @property
    def total_count(self) -> int:
        return len(self.models)

    @property
    def summary(self) -> Dict[str, Any]:
        return {
            name: {"status": m.get("status", "unknown")}
            for name, m in self.models.items()
        }

    def get_model(self, name: str) -> Optional[Dict[str, Any]]:
        return self.models.get(name)
