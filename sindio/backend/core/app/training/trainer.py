"""
Distributed training loop for SindioFoundationModel using Hugging Face Accelerate.

Supports:
  - 4 GPU data-parallel training
  - Gradient accumulation
  - Mixed-precision (fp16 / bf16)
  - WandB logging
  - LR warmup + cosine decay
  - Checkpoint save / resume
"""

import json
import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingWarmRestarts, LinearLR, SequentialLR
from torch.utils.data import DataLoader

from accelerate import Accelerator
from accelerate.utils import (
    GradientAccumulationPlugin,
    ProjectConfiguration,
    set_seed,
)

from app.models.sindio_foundation import SindioFoundationModel
from app.models.losses import SindioLoss

logger = logging.getLogger("sindio.trainer")


@dataclass
class TrainingConfig:
    """Hyperparameters for Sindio model training."""

    # Optimiser
    learning_rate: float = 1e-4
    weight_decay: float = 1e-2
    betas: tuple = (0.9, 0.98)

    # Scheduling
    warmup_steps: int = 2000
    lr_min: float = 1e-7
    T_0: int = 10_000  # CosineAnnealingWarmRestarts cycle length

    # Training
    max_steps: int = 100_000
    gradient_accumulation_steps: int = 8
    max_grad_norm: float = 5.0
    mixed_precision: str = "fp16"

    # Loss weights
    lambda_stress: float = 1.0
    lambda_breach: float = 2.0
    lambda_contrastive: float = 0.1
    lambda_forecast: float = 1.5

    # Checkpointing
    save_every_steps: int = 2500
    eval_every_steps: int = 5000
    log_every_steps: int = 50
    output_dir: str = "models/trained/sindio_foundation"
    resume_from: Optional[str] = None

    # Data
    batch_size: int = 64
    num_workers: int = 4

    # Reproducibility
    seed: int = 42


class SindioTrainer:
    """Distributed trainer for SindioFoundationModel."""

    def __init__(
        self,
        model: SindioFoundationModel,
        config: TrainingConfig,
        train_dataloader: DataLoader,
        val_dataloader: Optional[DataLoader] = None,
    ):
        self.config = config
        self.model = model
        self.train_dl = train_dataloader
        self.val_dl = val_dataloader

        # Accelerator setup — handles device placement, DDP, mixed-precision
        proj_config = ProjectConfiguration(
            project_dir=config.output_dir,
            logging_dir=os.path.join(config.output_dir, "logs"),
        )
        gradient_plugin = GradientAccumulationPlugin(
            num_steps=config.gradient_accumulation_steps,
            adjust_scheduler=False,
        )

        self.accelerator = Accelerator(
            mixed_precision=config.mixed_precision,
            gradient_accumulation_plugin=gradient_plugin,
            project_config=proj_config,
            log_with="wandb",
        )

        set_seed(config.seed)
        self.device = self.accelerator.device

        # Trackers
        self.accelerator.init_trackers(
            project_name="sindio-foundation",
            config={
                **vars(config),
                "model_params": sum(p.numel() for p in model.parameters()),
                "trainable_params": sum(p.numel() for p in model.parameters() if p.requires_grad),
            },
        )

        # Optimiser
        no_decay = ["bias", "LayerNorm.weight", "layer_norm.weight"]
        optim_groups = [
            {
                "params": [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay) and p.requires_grad],
                "weight_decay": config.weight_decay,
            },
            {
                "params": [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay) and p.requires_grad],
                "weight_decay": 0.0,
            },
        ]
        self.optimiser = AdamW(
            optim_groups, lr=config.learning_rate, betas=config.betas
        )

        # LR scheduler: warmup → cosine restarts
        warmup_sched = LinearLR(
            self.optimiser,
            start_factor=0.01,
            total_iters=config.warmup_steps,
        )
        cosine_sched = CosineAnnealingWarmRestarts(
            self.optimiser, T_0=config.T_0, T_mult=2, eta_min=config.lr_min
        )
        self.scheduler = SequentialLR(
            self.optimiser,
            schedulers=[warmup_sched, cosine_sched],
            milestones=[config.warmup_steps],
        )

        # Loss
        self.criterion = SindioLoss(
            lambda_stress=config.lambda_stress,
            lambda_breach=config.lambda_breach,
            lambda_contrastive=config.lambda_contrastive,
            lambda_forecast=config.lambda_forecast,
        )

        # Prepare with accelerator
        self.model, self.optimiser, self.train_dl, self.scheduler = self.accelerator.prepare(
            self.model, self.optimiser, self.train_dl, self.scheduler
        )

        if self.val_dl is not None:
            self.val_dl = self.accelerator.prepare(self.val_dl)

        self.global_step = 0
        self.best_val_loss = float("inf")

        # Resume if requested
        if config.resume_from:
            self._resume(config.resume_from)

    def train(self):
        """Main training loop."""
        model = self.model
        optimiser = self.optimiser
        scheduler = self.scheduler

        model.train()

        while self.global_step < self.config.max_steps:
            for batch in self.train_dl:
                with self.accelerator.accumulate(model):
                    outputs = model(
                        satellite=batch.get("satellite"),
                        graph_batch=batch.get("graph_batch"),
                        time_series=batch.get("time_series"),
                        return_embeddings=True,
                    )

                    loss, components = self.criterion(
                        stress_pred=outputs["stress"],
                        stress_gt=batch["stress_gt"],
                        breach_logits=outputs["breach_logits"],
                        breach_gt=batch["breach_gt"],
                        vision_emb=outputs["vision_emb"],
                        graph_emb=outputs["graph_emb"],
                        temporal_emb=outputs["temporal_emb"],
                        forecast_pred=outputs.get("forecast"),
                        forecast_gt=batch.get("forecast_gt"),
                        stress_mask=batch.get("stress_mask"),
                        breach_mask=batch.get("breach_mask"),
                        forecast_mask=batch.get("forecast_mask"),
                    )

                    self.accelerator.backward(loss)

                    if self.accelerator.sync_gradients:
                        self.accelerator.clip_grad_norm_(
                            model.parameters(), self.config.max_grad_norm
                        )

                    optimiser.step()
                    scheduler.step()
                    optimiser.zero_grad()

                if self.accelerator.sync_gradients:
                    self.global_step += 1

                    # Logging
                    if self.global_step % self.config.log_every_steps == 0:
                        self._log(components, scheduler.get_last_lr()[0])

                    # Checkpoint
                    if self.global_step % self.config.save_every_steps == 0:
                        self._save_checkpoint()

                    # Validation
                    if (
                        self.val_dl is not None
                        and self.global_step % self.config.eval_every_steps == 0
                    ):
                        val_loss = self._validate()
                        self.accelerator.log({"val/loss": val_loss}, step=self.global_step)
                        if val_loss < self.best_val_loss:
                            self.best_val_loss = val_loss
                            self._save_checkpoint(tag="best")

                        model.train()

                if self.global_step >= self.config.max_steps:
                    break

        self.accelerator.wait_for_everyone()
        self._save_checkpoint(tag="final")
        self.accelerator.end_training()
        logger.info("Training complete at step %d.", self.global_step)

    def _validate(self) -> float:
        """Run one validation epoch, return average total loss."""
        model = self.model
        model.eval()
        total = 0.0
        count = 0

        with torch.no_grad():
            for batch in self.val_dl:
                outputs = model(
                    satellite=batch.get("satellite"),
                    graph_batch=batch.get("graph_batch"),
                    time_series=batch.get("time_series"),
                    return_embeddings=True,
                )

                loss, _ = self.criterion(
                    stress_pred=outputs["stress"],
                    stress_gt=batch["stress_gt"],
                    breach_logits=outputs["breach_logits"],
                    breach_gt=batch["breach_gt"],
                    vision_emb=outputs["vision_emb"],
                    graph_emb=outputs["graph_emb"],
                    temporal_emb=outputs["temporal_emb"],
                    forecast_pred=outputs.get("forecast"),
                    forecast_gt=batch.get("forecast_gt"),
                    stress_mask=batch.get("stress_mask"),
                    breach_mask=batch.get("breach_mask"),
                    forecast_mask=batch.get("forecast_mask"),
                )

                gathered = self.accelerator.gather(loss.unsqueeze(0))
                if self.accelerator.is_main_process:
                    total += gathered.sum().item()
                    count += gathered.numel()

        return total / count if count > 0 else float("inf")

    def _log(self, components: dict, lr: float):
        metrics = {
            "train/loss_total": components["total"].item(),
            "train/lr": lr,
        }
        for k, v in components.items():
            if k != "total":
                metrics[f"train/loss_{k}"] = v.item()
        self.accelerator.log(metrics, step=self.global_step)

        if self.accelerator.is_main_process:
            parts = ", ".join(f"{k}={v.item():.4f}" for k, v in components.items())
            logger.info("[step %d] %s  |  lr=%.2e", self.global_step, parts, lr)

    def _save_checkpoint(self, tag: Optional[str] = None):
        if not self.accelerator.is_main_process:
            return

        suffix = f"-{tag}" if tag else ""
        step = self.global_step
        out = Path(self.config.output_dir) / f"checkpoint-{step}{suffix}"
        out.mkdir(parents=True, exist_ok=True)

        unwrapped = self.accelerator.unwrap_model(self.model)
        config = {}

        state = {
            "model": unwrapped.state_dict(),
            "optimiser": self.optimiser.state_dict(),
            "scheduler": self.scheduler.state_dict(),
            "global_step": step,
            "best_val_loss": self.best_val_loss,
            "config": config,
        }

        torch.save(state, out / "pytorch_model.bin")
        (out / "model_config.json").write_text(
            json.dumps({"latent_dim": unwrapped.latent_dim}, indent=2)
        )
        logger.info("Saved checkpoint to %s", out)

    def _resume(self, path: str):
        ckpt = torch.load(os.path.join(path, "pytorch_model.bin"), map_location="cpu")
        unwrapped = self.accelerator.unwrap_model(self.model)
        unwrapped.load_state_dict(ckpt["model"])
        self.optimiser.load_state_dict(ckpt["optimiser"])
        self.scheduler.load_state_dict(ckpt["scheduler"])
        self.global_step = ckpt.get("global_step", 0)
        self.best_val_loss = ckpt.get("best_val_loss", float("inf"))
        self.accelerator.print(f"Resumed from step {self.global_step}")
