"""
Long-Window Stress Classifier
==============================

Replaces ``stress_classifier.StressClassifier`` with minimum 6-month
historical windows using proper seasonal decomposition (STL) and
rolling Spearman correlation.

Categories
----------
* **recurring_only** — no density correlation, clear temporal pattern
  → next_check_interval = minimum × recurring_multiplier (e.g. 180 → 360 days)

* **density_driven_only** — strong correlation (ρ > 0.6 over 18+ months),
  no temporal pattern → next_check_interval = minimum

* **mixed** — both present → next_check_interval = minimum × 1.3

* **unstable** — insufficient data (< 12 months) or no clear pattern
  → next_check_interval = minimum × 1.5

Data requirements
-----------------
* Recurring detection: ≥ 18 months hourly data (≥ 3 seasonal cycles).
* Density-driven detection: ≥ 12 months population data.
* Fallback: < 12 months → ``unstable`` with minimum × 1.5 interval.

Persistence
-----------
Every classification run is stored in TimescaleDB ``classification_history``
for trend/shift detection (e.g. recurring → density_driven over 2 years).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("sindio.long_window_classifier")

# ======================================================================
# Constants
# ======================================================================

# ======================================================================
# Per-type data-collection windows (months)
#
# The recurring-stress and density-driven classifications require
# at least the minimum number of months of historical data for
# that infrastructure type. Shorter windows → "unstable".
# ======================================================================
MIN_DATA_WINDOWS: Dict[str, int] = {
    "water": 6,            # pipe burst patterns detectable in 6 months
    "power": 6,            # load patterns emerge quickly
    "roads": 9,            # seasonal traffic needs ≥ 9 months
    "solid_waste": 8,      # collection patterns over 8 months
    "sidewalks": 12,       # pedestrian flow changes very slowly
    "lrt": 6,              # train schedules create clear patterns
    "sgr": 6,              # SGR schedules are regular and predictable
    "airports": 12,        # flight schedules change seasonally — need full year
}

# Minimum months for recurring classification (per type).
MIN_MONTHS_RECURRING = MIN_DATA_WINDOWS

# Minimum months for density-driven detection.
MIN_MONTHS_DENSITY: Dict[str, int] = {
    k: v for k, v in MIN_DATA_WINDOWS.items()
}

# Below this many months → classify as "unstable".
MIN_MONTHS_UNSTABLE: Dict[str, int] = {
    k: max(v // 2, 3) for k, v in MIN_DATA_WINDOWS.items()
}

HOURS_PER_MONTH = 730         # Approximate (365.25 / 12 * 24)

# ======================================================================
# Per-type STL and Spearman thresholds
#
# Different infrastructure types exhibit different signal-to-noise
# characteristics.  Heavy-rail (sgr) has tight schedules with very
# stable peaks, so a stricter CoV is appropriate.  Pedestrian patterns
# (sidewalks) are inherently noisier, so a looser CoV is needed.
# ======================================================================

# STL seasonal strength — minimum fraction of variance explained by
# the seasonal component for a pattern to be considered "recurring".
SEASONAL_STRENGTH_MIN: Dict[str, float] = {
    "water": 0.20,
    "power": 0.25,
    "roads": 0.25,
    "solid_waste": 0.20,
    "sidewalks": 0.15,      # pedestrian flow has high residual noise
    "lrt": 0.20,            # train schedules are regular
    "sgr": 0.25,            # SGR is highly scheduled — tight threshold
    "airports": 0.20,       # flight schedules seasonal but variable
}

# Coefficient of variation of peak timing — must be below this for
# a peak to be considered "stable across cycles".
RECURRING_PEAK_CV_MAX: Dict[str, float] = {
    "water": 0.15,
    "power": 0.15,
    "roads": 0.18,          # traffic peaks shift with events
    "solid_waste": 0.20,    # collection days shift with holidays
    "sidewalks": 0.25,      # pedestrian flow highly variable
    "lrt": 0.12,            # train headways are fixed
    "sgr": 0.10,            # SGR schedules nearly invariant
    "airports": 0.18,       # seasonal but weather-dependent variance
}

# Spearman ρ threshold — above this, stress is classified as
# density-driven.  Lower for types where population growth dominates,
# higher for types where operational factors dominate.
DENSITY_RHO_THRESHOLD: Dict[str, float] = {
    "water": 0.55,          # water demand weakly tracks population
    "power": 0.65,          # power load strongly tracks population
    "roads": 0.60,          # congestion tracks density
    "solid_waste": 0.50,    # waste volume directly proportional to pop
    "sidewalks": 0.70,      # foot traffic strongly density-driven
    "lrt": 0.55,            # ridership tracks population growth
    "sgr": 0.45,            # freight demand tied to economic activity, not just pop
    "airports": 0.55,       # passenger numbers partially density-driven, partially tourism
}

# Interval multipliers (applied to per-type minimum).
# The long_interval_scheduler per-type recurring_multiplier takes
# precedence; these are the classifier-level defaults.
MULTIPLIER_RECURRING: Dict[str, float] = {
    t: 2.0 for t in MIN_DATA_WINDOWS
}
MULTIPLIER_RECURRING.update({
    "sidewalks": 2.2,  # pedestrian patterns very slow — longer waits ok
    "sgr": 1.5,        # SGR stress demands faster follow-up
    "lrt": 1.6,
    "airports": 1.9,
})

MULTIPLIER_DENSITY: Dict[str, float] = {
    t: 1.0 for t in MIN_DATA_WINDOWS
}

MULTIPLIER_MIXED: Dict[str, float] = {
    t: 1.3 for t in MIN_DATA_WINDOWS
}

MULTIPLIER_UNSTABLE: Dict[str, float] = {
    t: 1.5 for t in MIN_DATA_WINDOWS
}

# ======================================================================
# Output
# ======================================================================


@dataclass
class LongWindowClassification:
    asset_id: str
    asset_type: str
    ward: str
    classification_type: str  # recurring_only | density_driven_only | mixed | unstable
    confidence: float
    dominant_period_days: Optional[float]
    peak_timing_cv: Optional[float]
    spearman_rho: float
    data_window_months: int
    next_check_interval_days: int
    stl_seasonal_strength: Optional[float]
    stl_trend_strength: Optional[float]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "ward": self.ward,
            "classification_type": self.classification_type,
            "confidence": round(self.confidence, 4),
            "dominant_period_days": (
                round(self.dominant_period_days, 2)
                if self.dominant_period_days is not None else None
            ),
            "peak_timing_cv": (
                round(self.peak_timing_cv, 4)
                if self.peak_timing_cv is not None else None
            ),
            "spearman_rho": round(self.spearman_rho, 4),
            "data_window_months": self.data_window_months,
            "next_check_interval_days": self.next_check_interval_days,
            "stl_seasonal_strength": (
                round(self.stl_seasonal_strength, 4)
                if self.stl_seasonal_strength is not None else None
            ),
            "stl_trend_strength": (
                round(self.stl_trend_strength, 4)
                if self.stl_trend_strength is not None else None
            ),
        }

    def to_geojson_properties(self) -> Dict[str, Any]:
        """Return a flat dict suitable for GeoJSON feature properties."""
        return {
            "classification_type": self.classification_type,
            "confidence": self.confidence,
            "data_window_months": self.data_window_months,
            "next_check_interval_days": self.next_check_interval_days,
            "spearman_rho": round(self.spearman_rho, 4),
            "dominant_period_days": self.dominant_period_days,
            "peak_timing_cv": self.peak_timing_cv,
        }


# ======================================================================
# STL-based recurring detection
# ======================================================================


def _detect_recurring_stl(
    stress_history: np.ndarray,
    asset_type: str = "water",
    sample_rate_hours: float = 1.0,
) -> Tuple[bool, float, Optional[float], Optional[float], Optional[float]]:
    """Detect recurring patterns using STL decomposition.

    Requires ≥ 3 complete seasonal cycles (≥ 3 years of data with yearly period).

    Returns
    -------
    (is_recurring, confidence, dominant_period_days, peak_timing_cv, seasonal_strength)
    """
    try:
        from statsmodels.tsa.seasonal import STL
    except ImportError:
        logger.warning("statsmodels not available — falling back to FFT")
        return _detect_recurring_fft_fallback(stress_history, asset_type, sample_rate_hours)

    N = len(stress_history)
    hours_per_year = 8760
    min_hours = hours_per_year * 3  # ≥ 3 years

    if N < min_hours:
        logger.debug("Insufficient data for STL: %d hours < %d minimum", N, min_hours)
        return False, 0.0, None, None, None

    # Use yearly period for STL
    period = int(hours_per_year / sample_rate_hours)
    if period < 2 or period > N // 2:
        return False, 0.0, None, None, None

    try:
        stl = STL(stress_history, period=period, seasonal=13, trend=25, robust=True)
        result = stl.fit()
    except Exception as exc:
        logger.warning("STL fit failed: %s — falling back to FFT", exc)
        return _detect_recurring_fft_fallback(stress_history, asset_type, sample_rate_hours)

    seasonal = result.seasonal
    trend = result.trend

    # ── Seasonal strength ───────────────────────────────────
    var_residual = np.var(result.resid[~np.isnan(result.resid)])
    var_seasonal = np.var(seasonal[~np.isnan(seasonal)])
    seasonal_strength = max(0.0, min(1.0, 1.0 - var_residual / (var_residual + var_seasonal + 1e-12)))
    trend_strength = max(0.0, min(1.0, 1.0 - var_residual / (var_residual + np.var(trend[~np.isnan(trend)]) + 1e-12)))

    # ── Peak timing extraction (year over year) ──────────────
    n_years = N // period
    if n_years < 3:
        logger.debug("Fewer than 3 complete cycles in data")
        return False, 0.0, None, None, None

    peak_positions: List[int] = []
    for yr in range(n_years):
        start = yr * period
        end = start + period
        if end > N:
            break
        seg = seasonal[start:end]
        if len(seg) < period // 2:
            continue
        peak_idx = int(np.argmax(seg))
        peak_positions.append(peak_idx)

    if len(peak_positions) < 2:
        return False, 0.0, None, None, None

    # ── Stability: coefficient of variation of peak timing ───
    mean_peak = np.mean(peak_positions)
    std_peak = np.std(peak_positions)
    cv = std_peak / (mean_peak + 1e-8)
    peak_timing_cv = float(cv)

    # ── Dominant period: average spacing between consecutive peaks ──
    spacings = np.diff(peak_positions)
    if len(spacings) > 0:
        dominant_period_hours = float(np.mean(spacings)) * sample_rate_hours
    else:
        dominant_period_hours = float(period) * sample_rate_hours
    dominant_period_days = dominant_period_hours / 24.0

    # ── Classification (per-type thresholds) ──────────────────
    cv_max = RECURRING_PEAK_CV_MAX.get(asset_type, 0.15)
    strength_min = SEASONAL_STRENGTH_MIN.get(asset_type, 0.25)

    is_recurring = (
        seasonal_strength > strength_min
        and peak_timing_cv < cv_max
    )

    # Confidence combines seasonal strength and inverse CV
    confidence = seasonal_strength * (1.0 - min(peak_timing_cv / cv_max, 1.0))
    confidence = max(0.0, min(1.0, float(confidence)))

    logger.debug(
        "STL: recurring=%s seasonal_strength=%.3f cv=%.4f period=%.1fd confidence=%.3f",
        is_recurring, seasonal_strength, peak_timing_cv,
        dominant_period_days, confidence,
    )

    return is_recurring, confidence, dominant_period_days, peak_timing_cv, seasonal_strength


def _detect_recurring_fft_fallback(
    stress_history: np.ndarray,
    asset_type: str = "water",
    sample_rate_hours: float = 1.0,
) -> Tuple[bool, float, Optional[float], Optional[float], Optional[float]]:
    """FFT-based fallback when statsmodels is unavailable."""
    from app.services.stress_classifier import StressClassifier

    classifier = StressClassifier()
    pop_dummy = np.random.normal(0, 0.1, len(stress_history))
    result = classifier._fourier_classify(stress_history, sample_rate_hours)

    if result["is_recurring"] and result["dominant_period"] is not None:
        return True, result["confidence"], result["dominant_period"] / 24.0, None, None
    return False, result["confidence"], None, None, None


# ======================================================================
# Rolling Spearman correlation (density-driven detection)
# ======================================================================


def _detect_density_driven(
    stress_history: np.ndarray,
    population_history: np.ndarray,
    asset_type: str = "water",
    min_months: int = 12,
) -> Tuple[bool, float, float]:
    """Detect density-driven stress via rolling Spearman correlation.

    Uses per-type rho threshold from DENSITY_RHO_THRESHOLD dict.

    Computes ρ over sliding windows, returns whether any
    sustained period has ρ > threshold for that type.

    Returns
    -------
    (is_density_driven, max_rho, mean_rho_over_18m)
    """
    rho_threshold = DENSITY_RHO_THRESHOLD.get(asset_type, 0.6)
    from scipy import stats

    n = min(len(stress_history), len(population_history))
    min_hours = min_months * HOURS_PER_MONTH

    if n < min_hours:
        return False, 0.0, 0.0

    s = np.asarray(stress_history[:n], dtype=np.float64)
    p = np.asarray(population_history[:n], dtype=np.float64)

    # Population growth rate (first difference, then 7-day smoothed)
    pop_growth = np.diff(p, prepend=p[0])
    smooth_window = 168  # 7 days hourly
    pop_growth = np.convolve(pop_growth, np.ones(smooth_window) / smooth_window, mode="same")

    # Skip first 24 hours (settling)
    s = s[24:]
    pg = pop_growth[24:]

    window_size = 12 * HOURS_PER_MONTH  # 12 months in hours
    step = HOURS_PER_MONTH              # Slide by 1 month

    rolling_rhos: List[float] = []
    for start in range(0, len(s) - int(window_size), int(step)):
        end = start + int(window_size)
        if end > len(s):
            break
        seg_s = s[start:end]
        seg_p = pg[start:end]

        # Remove linear trend before correlation
        seg_s_detrend = seg_s - np.polyval(np.polyfit(np.arange(len(seg_s)), seg_s, 1), np.arange(len(seg_s)))
        seg_p_detrend = seg_p - np.polyval(np.polyfit(np.arange(len(seg_p)), seg_p, 1), np.arange(len(seg_p)))

        rho, pval = stats.spearmanr(seg_s_detrend, seg_p_detrend)
        if not np.isnan(rho):
            rolling_rhos.append(float(rho))

    if not rolling_rhos:
        return False, 0.0, 0.0

    max_rho = max(rolling_rhos)

    # Check sustained 18-month window
    n_18m = min(18, len(rolling_rhos))
    if len(rolling_rhos) >= n_18m:
        last_18 = rolling_rhos[-n_18m:]
        mean_rho_18m = float(np.mean(last_18))
    else:
        mean_rho_18m = float(np.mean(rolling_rhos))

    is_density = max_rho > rho_threshold and mean_rho_18m > 0.4
    max_rho_val = float(max_rho)

    logger.debug(
        "Density: rho_max=%.3f rho_18m=%.3f (threshold %.2f) → %s",
        max_rho_val, mean_rho_18m, rho_threshold, is_density,
    )

    return is_density, max_rho_val, mean_rho_18m


# ======================================================================
# Main classifier
# ======================================================================


class LongWindowClassifier:
    """Classify asset stress root cause using long historical windows.

    Uses STL seasonal decomposition for recurring detection and rolling
    Spearman ρ for density-driven detection.  Each infrastructure type
    has its own minimum data-collection window:

    - water / power / lrt / sgr : 6 months
    - roads : 9 months
    - solid_waste : 8 months
    - sidewalks / airports : 12 months

    Persists every classification to TimescaleDB ``classification_history``
    for trend/shift detection.
    """

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.getenv(
            "DATABASE_URL",
            f"postgresql://{os.getenv('DB_USER', 'sindio_user')}:"
            f"{os.getenv('DB_PASSWORD', 'sindio_pass')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'sindio')}",
        )

    def classify(
        self,
        asset_id: str,
        asset_type: str,
        ward: str,
        stress_history: np.ndarray,
        population_history: np.ndarray,
        sample_rate_hours: float = 1.0,
        base_interval_days: int = 180,
        persist: bool = True,
    ) -> LongWindowClassification:
        """Classify a single asset and compute next_check_interval_days.

        Parameters
        ----------
        asset_id : str
        asset_type : str  — water, power, roads, solid_waste, sidewalks,
                            lrt, sgr, airports
        ward : str
        stress_history : ndarray  — hourly stress values [0–1]
        population_history : ndarray  — hourly population values
        sample_rate_hours : float  — hours between samples (default 1)
        base_interval_days : int  — per-type minimum interval
        persist : bool  — store in TimescaleDB

        Returns LongWindowClassification
        """
        data_months = len(stress_history) / HOURS_PER_MONTH
        data_months_int = int(data_months)

        # Per-type minimum window (default 6 months)
        min_unstable = MIN_MONTHS_UNSTABLE.get(asset_type, 6)
        min_recurring = MIN_MONTHS_RECURRING.get(asset_type, 6)
        min_density = MIN_MONTHS_DENSITY.get(asset_type, 6)

        # ── Below minimum data → unstable ────────────────────
        if data_months_int < min_unstable:
            result = LongWindowClassification(
                asset_id=asset_id,
                asset_type=asset_type,
                ward=ward,
                classification_type="unstable",
                confidence=0.1,
                dominant_period_days=None,
                peak_timing_cv=None,
                spearman_rho=0.0,
                data_window_months=data_months_int,
                next_check_interval_days=int(base_interval_days * MULTIPLIER_UNSTABLE.get(asset_type, 1.5)),
                stl_seasonal_strength=None,
                stl_trend_strength=None,
                metadata={
                    "reason": "insufficient_data",
                    "months_available": data_months_int,
                    "min_required": min_unstable,
                },
            )
            if persist:
                self._persist(result)
            return result

        # ── Recurring detection ───────────────────────────────
        is_recurring = False
        recurring_confidence = 0.0
        dominant_period_days: Optional[float] = None
        peak_timing_cv: Optional[float] = None
        seasonal_strength: Optional[float] = None

        if data_months_int >= min_recurring:
            is_recurring, recurring_confidence, dominant_period_days, peak_timing_cv, seasonal_strength = (
                _detect_recurring_stl(stress_history, asset_type, sample_rate_hours)
            )

        # ── Density-driven detection ───────────────────────────
        is_density, max_rho, mean_rho = _detect_density_driven(
            stress_history, population_history,
            asset_type=asset_type,
            min_months=min_density,
        )

        # ── Combine into category ─────────────────────────────
        if is_recurring and is_density:
            class_type = "mixed"
            confidence = (recurring_confidence + min(max_rho, 1.0)) / 2.0
            multiplier = MULTIPLIER_MIXED.get(asset_type, 1.3)
        elif is_recurring and not is_density:
            class_type = "recurring_only"
            confidence = recurring_confidence
            multiplier = MULTIPLIER_RECURRING.get(asset_type, 2.0)
        elif is_density and not is_recurring:
            class_type = "density_driven_only"
            confidence = min(max_rho, 1.0)
            multiplier = MULTIPLIER_DENSITY.get(asset_type, 1.0)
        else:
            class_type = "unstable"
            confidence = max(0.1, min(recurring_confidence, max_rho))
            multiplier = MULTIPLIER_UNSTABLE.get(asset_type, 1.5)

        next_interval = int(base_interval_days * multiplier)

        result = LongWindowClassification(
            asset_id=asset_id,
            asset_type=asset_type,
            ward=ward,
            classification_type=class_type,
            confidence=confidence,
            dominant_period_days=dominant_period_days,
            peak_timing_cv=peak_timing_cv,
            spearman_rho=max_rho,
            data_window_months=data_months_int,
            next_check_interval_days=next_interval,
            stl_seasonal_strength=seasonal_strength,
            stl_trend_strength=None,
            metadata={
                "is_recurring": is_recurring,
                "is_density": is_density,
                "max_rho_12m": max_rho,
                "mean_rho_18m": mean_rho,
                "multiplier": multiplier,
            },
        )

        if persist:
            self._persist(result)

        return result

    def classify_batch(
        self,
        assets: List[Dict[str, Any]],
        stress_histories: Dict[str, np.ndarray],
        population_histories: Dict[str, np.ndarray],
        base_interval_days: int = 180,
    ) -> List[LongWindowClassification]:
        """Classify a batch of assets."""
        results = []
        for asset in assets:
            aid = asset["asset_id"]
            result = self.classify(
                asset_id=aid,
                asset_type=asset.get("asset_type", "water"),
                ward=asset.get("ward", "unknown"),
                stress_history=stress_histories.get(aid, np.array([0.5])),
                population_history=population_histories.get(aid, np.array([100.0])),
                base_interval_days=base_interval_days,
            )
            results.append(result)
        return results

    # ── TimescaleDB persistence ──────────────────────────────

    def _persist(self, result: LongWindowClassification) -> None:
        """Store classification in TimescaleDB hypertable."""
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(self.db_url)
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO classification_history
                            (asset_id, asset_type, ward, classification_type,
                             confidence, dominant_period_days, peak_timing_cv,
                             spearman_rho, data_window_months,
                             next_check_interval_days,
                             recurring_multiplier, density_multiplier,
                             stl_seasonal_strength, stl_trend_strength,
                             classification_metadata, created_at)
                        VALUES
                            (:asset_id, :asset_type, :ward, :class_type,
                             :confidence, :period_days, :peak_cv,
                             :rho, :window_months,
                             :interval_days,
                             :recurring_mul, :density_mul,
                             :seasonal_str, :trend_str,
                             :meta::jsonb, NOW())
                    """),
                    {
                        "asset_id": result.asset_id,
                        "asset_type": result.asset_type,
                        "ward": result.ward,
                        "class_type": result.classification_type,
                        "confidence": result.confidence,
                        "period_days": result.dominant_period_days,
                        "peak_cv": result.peak_timing_cv,
                        "rho": result.spearman_rho,
                        "window_months": result.data_window_months,
                        "interval_days": result.next_check_interval_days,
                        "recurring_mul": result.metadata.get("multiplier", 1.0),
                        "density_mul": result.metadata.get("max_rho_12m", 0.0),
                        "seasonal_str": result.stl_seasonal_strength,
                        "trend_str": result.stl_trend_strength,
                        "meta": __import__("json").dumps(result.metadata, default=str),
                    },
                )
            logger.debug("Persisted classification for %s: %s", result.asset_id, result.classification_type)
        except Exception as exc:
            logger.warning("Failed to persist classification for %s: %s", result.asset_id, exc)


# ======================================================================
# Shift detection
# ======================================================================


def detect_classification_shifts(
    asset_id: str,
    lookback_months: int = 24,
    db_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Detect classification shifts (e.g. recurring → density_driven).

    Returns list of transitions with dates, types, and confidence.
    """
    url = db_url or os.getenv(
        "DATABASE_URL",
        f"postgresql://{os.getenv('DB_USER','sindio_user')}:"
        f"{os.getenv('DB_PASSWORD','sindio_pass')}@"
        f"{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT','5432')}/"
        f"{os.getenv('DB_NAME','sindio')}",
    )
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url)
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT classification_type, confidence, created_at
                    FROM classification_history
                    WHERE asset_id = :aid
                      AND created_at > NOW() - make_interval(months := :m)
                    ORDER BY created_at
                """),
                {"aid": asset_id, "m": lookback_months},
            ).fetchall()

        shifts: List[Dict[str, Any]] = []
        prev_type = None
        for r in rows:
            if prev_type is not None and r.classification_type != prev_type:
                shifts.append({
                    "from": prev_type,
                    "to": r.classification_type,
                    "at": r.created_at.isoformat(),
                    "confidence": float(r.confidence) if r.confidence else None,
                })
            prev_type = r.classification_type

        return shifts
    except Exception as exc:
        logger.warning("Shift detection failed for %s: %s", asset_id, exc)
        return []
