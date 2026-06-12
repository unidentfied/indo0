"""
Temporal Spacing Logic
=======================

Long-interval asset-check scheduling for Sindio.  These rules are
data-driven — no policy documents or external mandates are referenced.

Business rules
--------------

* **Base minimum intervals** (no check runs more often than this):
    water       ≥ 180 days  (6 months)
    power       ≥ 210 days  (7 months)
    roads       ≥ 270 days  (9 months)
    solid_waste ≥ 365 days  (12 months)

* **Absolute floor**: even if stress exceeds 0.95, the interval never drops
  below 30 days.  No hourly or daily alert spam.

* **Recurring-stress multiplier**: when the stress is classified as
  *purely recurring* (Spearman ρ_density < 0.3), the interval is **doubled**
  because recurring peaks are predictable and do not need frequent checks.

* **Density-driven minimum**: when ρ_density > 0.7 the interval is set to
  the *type minimum* and not reduced further — density changes are slow.

* **Jitter**: ±5 % of the computed interval, but the *absolute* value
  never falls below the type minimum.  Prevents thundering-herd.

* **Stateful scheduling**: ``schedule_batch()`` generates next_run timestamps
  for many assets while guaranteeing that no water asset is scheduled
  earlier than 180 days from now.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Base minimums (days) for recurring-stress / density-driven alert intervals.
# SHORT intervals are handled by alert_scheduler.py (frequent alerts).
# These LONG intervals apply specifically to recurring-stress and
# density-driven recurrence alerts that use ≥6 months of historical data.
# ---------------------------------------------------------------------------
BASE_MINIMUM_DAYS: Dict[str, int] = {
    "water":       180,
    "power":       210,
    "roads":       270,
    "solid_waste": 365,
    "sidewalks":   180,
    "lrt":         150,
    "sgr":         150,
    "airports":    210,
}

# Absolute hard floor — interval never goes below this for any type.
ABSOLUTE_FLOOR_DAYS = 30

# Recurring-stress interval multiplier.
RECURRING_MULTIPLIER = 2.0

# Density-driven ρ threshold above which the interval is type minimum.
DENSITY_RHO_THRESHOLD = 0.7

# Recurring ρ threshold below which the interval is doubled.
RECURRING_RHO_THRESHOLD = 0.3

# Jitter fraction (±5 %).
JITTER_FRACTION = 0.05

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SpacingResult:
    infrastructure_type: str
    base_interval_days: int
    computed_interval_days: float
    final_interval_days: int
    applied_jitter_pct: float
    reasoning: str


@dataclass
class AssetSchedule:
    asset_id: str
    infrastructure_type: str
    next_run: datetime
    interval_days: int
    classification: str          # "recurring" | "density_driven" | "hybrid" | "normal"
    density_rho: float
    stress: float


# ---------------------------------------------------------------------------
# Core interval computation
# ---------------------------------------------------------------------------


def compute_interval(
    infrastructure_type: str,
    stress: float = 0.5,
    density_rho: Optional[float] = None,
    classification: Optional[str] = None,
    random_seed: Optional[int] = None,
) -> SpacingResult:
    """Compute the temporal spacing interval for one asset.

    Parameters
    ----------
    infrastructure_type : str
        One of ``water``, ``power``, ``roads``, ``solid_waste``.
    stress : float
        Current stress value [0, 1].
    density_rho : float or None
        Spearman ρ between stress and population density.
    classification : str or None
        Pre-computed classification: ``recurring``, ``density_driven``,
        ``hybrid``, or ``None`` (auto-determined from ρ).
    random_seed : int or None
        Seed for reproducible jitter.

    Returns
    -------
    SpacingResult
    """
    base = BASE_MINIMUM_DAYS.get(infrastructure_type)
    if base is None:
        raise ValueError(f"Unknown infrastructure_type: {infrastructure_type}")

    # ── Determine classification if not given ──────────────────
    if classification is None and density_rho is not None:
        if density_rho <= RECURRING_RHO_THRESHOLD:
            classification = "recurring"
        elif density_rho >= DENSITY_RHO_THRESHOLD:
            classification = "density_driven"

    reasons: List[str] = []
    interval = float(base)

    # ── Recurring → double the interval ────────────────────────
    if classification == "recurring":
        interval = base * RECURRING_MULTIPLIER
        reasons.append(f"recurring stress (ρ≤{RECURRING_RHO_THRESHOLD}) → interval doubled to {int(interval)}d")

    # ── Density-driven → keep at minimum ───────────────────────
    elif classification == "density_driven":
        interval = float(base)
        reasons.append(f"density-driven (ρ>{DENSITY_RHO_THRESHOLD}) → interval at type minimum {base}d")

    else:
        reasons.append(f"standard interval for {infrastructure_type}: {base}d")

    # ── Absolute floor check ───────────────────────────────────
    if interval < ABSOLUTE_FLOOR_DAYS:
        interval = float(ABSOLUTE_FLOOR_DAYS)
        reasons.append(f"absolute floor applied: {ABSOLUTE_FLOOR_DAYS}d")

    # ── High-stress never pushes below minimum ─────────────────
    # The interval is the *maximum* of the computed value and the
    # base minimum.  High stress does NOT shorten it.
    if stress > 0.95:
        reasons.append(f"stress={stress:.2f}>0.95 but interval stays at {int(interval)}d (no hourly alerts)")

    # ── Jitter (±5%, but absolute floor respected) ────────────
    rng = random.Random(random_seed) if random_seed is not None else random.Random()
    jitter_factor = rng.uniform(1.0 - JITTER_FRACTION, 1.0 + JITTER_FRACTION)
    jittered = interval * jitter_factor
    jitter_pct = (jitter_factor - 1.0) * 100

    # Clamp to *type minimum*, not absolute floor
    clamped = max(jittered, base)
    final = int(math.floor(clamped))

    return SpacingResult(
        infrastructure_type=infrastructure_type,
        base_interval_days=base,
        computed_interval_days=round(interval, 2),
        final_interval_days=final,
        applied_jitter_pct=round(jitter_pct, 2),
        reasoning="; ".join(reasons),
    )


# ---------------------------------------------------------------------------
# Getters for minimum intervals (assertions in tests)
# ---------------------------------------------------------------------------


def water_minimum_interval() -> int:
    return BASE_MINIMUM_DAYS["water"]


def power_minimum_interval() -> int:
    return BASE_MINIMUM_DAYS["power"]


def roads_minimum_interval() -> int:
    return BASE_MINIMUM_DAYS["roads"]


def solid_waste_minimum_interval() -> int:
    return BASE_MINIMUM_DAYS["solid_waste"]


# ---------------------------------------------------------------------------
# Stateful batch scheduling
# ---------------------------------------------------------------------------


def schedule_batch(
    assets: List[Dict[str, any]],
    base_time: Optional[datetime] = None,
) -> List[AssetSchedule]:
    """Schedule ``next_run`` for a batch of assets, respecting minimums.

    Parameters
    ----------
    assets : list of dict
        Each dict must have keys: ``asset_id``, ``infrastructure_type``.
        Optional keys: ``stress``, ``density_rho``, ``classification``.
    base_time : datetime or None
        Reference "now" for computing next_run (default: UTC now).

    Returns
    -------
    list of AssetSchedule
    """
    now = base_time or datetime.now(timezone.utc)
    results: List[AssetSchedule] = []

    for i, asset in enumerate(assets):
        sp = compute_interval(
            infrastructure_type=asset["infrastructure_type"],
            stress=float(asset.get("stress", 0.5)),
            density_rho=asset.get("density_rho"),
            classification=asset.get("classification"),
            random_seed=i + hash(asset["asset_id"]) % 10000,
        )

        # Stagger next_run: add a small per-asset offset (0–5 % of interval)
        # to avoid all assets of the same type landing on the same day.
        stagger_sec = random.Random(i).randint(0, int(sp.final_interval_days * 86400 * 0.05))
        next_run = now + timedelta(days=sp.final_interval_days, seconds=stagger_sec)

        results.append(AssetSchedule(
            asset_id=asset["asset_id"],
            infrastructure_type=asset["infrastructure_type"],
            next_run=next_run,
            interval_days=sp.final_interval_days,
            classification=asset.get("classification", "normal"),
            density_rho=float(asset.get("density_rho", 0.5)),
            stress=float(asset.get("stress", 0.5)),
        ))

    return results


def get_earliest_water_next_run(schedules: List[AssetSchedule]) -> Optional[datetime]:
    """Return the earliest next_run among water assets."""
    water = [s for s in schedules if s.infrastructure_type == "water"]
    if not water:
        return None
    return min(s.next_run for s in water)
