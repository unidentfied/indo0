"""
Stress Classification Engine
=============================
Classifies infrastructure stress into three root-cause categories:

  1. Recurring — dominant Fourier frequency matches daily / weekly / seasonal cycle.
  2. Density-driven — stress is strongly correlated (Spearman ρ > 0.7) with
     local population growth (rolling 12-month window).
  3. Hybrid — both conditions present; percentage attributed to each cause.

Uses Fisher's g-test for significance of the dominant spectral peak (p < 0.05).

Output columns added to simulation GeoDataFrame:
  - classification_type:  "recurring" | "density_driven" | "hybrid" | "unclassified"
  - confidence:           float in [0, 1]
  - dominant_period_hours
  - spearman_rho
  - recurrence_pct:       % attributed to cyclical patterns (hybrid only)
  - density_pct:          % attributed to density growth (hybrid only)
  - classification_pvalue
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger("sindio.classify")

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────
DAILY_HOURS = 24
WEEKLY_HOURS = 168
SEASONAL_HOURS = 2160  # ~ 90 days

SPEARMAN_THRESHOLD = 0.7
FOURIER_P_VALUE_THRESHOLD = 0.05
HYBRID_MIN_PCT = 10.0    # minimum percentage for a cause to be counted


@dataclass
class ClassificationResult:
    classification_type: str     # recurring | density_driven | hybrid | unclassified
    confidence: float            # 0–1 overall confidence
    dominant_period_hours: Optional[float]
    spearman_rho: float
    recurrence_pct: float
    density_pct: float
    p_value: Optional[float]
    significant_cycles: List[str]

    def to_dict(self) -> Dict:
        return {
            "classification_type": self.classification_type,
            "confidence": round(self.confidence, 4),
            "dominant_period_hours": (
                round(self.dominant_period_hours, 2)
                if self.dominant_period_hours is not None
                else None
            ),
            "spearman_rho": round(self.spearman_rho, 4),
            "recurrence_pct": round(self.recurrence_pct, 2),
            "density_pct": round(self.density_pct, 2),
            "classification_pvalue": (
                round(self.p_value, 6) if self.p_value is not None else None
            ),
            "significant_cycles": self.significant_cycles,
        }


class StressClassifier:
    """Classify infrastructure stress root cause from historical signals."""

    def classify(
        self,
        stress_history: np.ndarray,        # (T,) hourly stress values
        population_history: np.ndarray,    # (T,) hourly population density
        timestamps: Optional[np.ndarray] = None,  # datetime64[h]
        sample_rate_hours: float = 1.0,
    ) -> ClassificationResult:
        """Run full classification pipeline.

        Args:
            stress_history:  (T,) float array of hourly stress [0, 1].
            population_history: (T,) float array of hourly population density.
            timestamps: optional datetime64 array for time-indexed operations.
            sample_rate_hours: hours between samples (default 1).

        Returns:
            ClassificationResult with type, confidence, and cause-attribution.
        """
        T = len(stress_history)

        if T < DAILY_HOURS * 7:
            return ClassificationResult(
                classification_type="unclassified",
                confidence=0.0,
                dominant_period_hours=None,
                spearman_rho=0.0,
                recurrence_pct=0.0,
                density_pct=0.0,
                p_value=None,
                significant_cycles=[],
            )

        # 1. Fourier decomposition → recurring check
        fourier_result = self._fourier_classify(stress_history, sample_rate_hours)

        # 2. Spearman correlation → density-driven check
        spearman_result = self._spearman_classify(stress_history, population_history)

        recurring = fourier_result["is_recurring"]
        density = spearman_result["is_density_driven"]

        # 3. Combine
        if recurring and not density:
            return ClassificationResult(
                classification_type="recurring",
                confidence=fourier_result["confidence"],
                dominant_period_hours=fourier_result["dominant_period"],
                spearman_rho=spearman_result["rho"],
                recurrence_pct=100.0,
                density_pct=0.0,
                p_value=fourier_result["p_value"],
                significant_cycles=fourier_result["matched_cycles"],
            )

        elif density and not recurring:
            return ClassificationResult(
                classification_type="density_driven",
                confidence=spearman_result["confidence"],
                dominant_period_hours=fourier_result["dominant_period"],
                spearman_rho=spearman_result["rho"],
                recurrence_pct=0.0,
                density_pct=100.0,
                p_value=fourier_result["p_value"],
                significant_cycles=[],
            )

        elif recurring and density:
            # Hybrid: compute relative contribution
            recurrence_pct, density_pct = self._attribute_hybrid(
                stress_history, population_history, fourier_result, spearman_result
            )
            confidence = (fourier_result["confidence"] + spearman_result["confidence"]) / 2.0

            return ClassificationResult(
                classification_type="hybrid",
                confidence=confidence,
                dominant_period_hours=fourier_result["dominant_period"],
                spearman_rho=spearman_result["rho"],
                recurrence_pct=recurrence_pct,
                density_pct=density_pct,
                p_value=fourier_result["p_value"],
                significant_cycles=fourier_result["matched_cycles"],
            )

        else:
            return ClassificationResult(
                classification_type="unclassified",
                confidence=0.0,
                dominant_period_hours=None,
                spearman_rho=spearman_result["rho"],
                recurrence_pct=0.0,
                density_pct=0.0,
                p_value=None,
                significant_cycles=[],
            )

    # ── Fourier decomposition ────────────────────────────────

    def _fourier_classify(
        self,
        signal: np.ndarray,
        sample_rate_hours: float = 1.0,
    ) -> Dict:
        """Detect recurring patterns via FFT + Fisher's g-test.

        Returns dict with keys:
          - is_recurring: bool
          - dominant_period: float (hours) or None
          - p_value: float or None
          - confidence: float
          - matched_cycles: list of str (e.g. ['daily', 'weekly'])
        """
        N = len(signal)
        if N < 48:
            return {
                "is_recurring": False, "dominant_period": None,
                "p_value": None, "confidence": 0.0, "matched_cycles": [],
            }

        # Remove linear trend
        signal_detrended = signal - np.polyval(np.polyfit(np.arange(N), signal, 1), np.arange(N))

        # Zero-pad to next power of 2
        n_pad = 1 << (N - 1).bit_length()
        fft = np.fft.rfft(signal_detrended, n=n_pad)
        power = np.abs(fft) ** 2
        power[0] = 0  # remove DC

        # Dominant frequency
        dominant_idx = np.argmax(power)
        freq_resolution = sample_rate_hours / n_pad
        dominant_freq = dominant_idx * freq_resolution  # cycles per hour
        dominant_period = 1.0 / dominant_freq if dominant_freq > 0 else None

        # Fisher's g-test for significance of dominant peak
        g_statistic = power[dominant_idx] / (power.sum() + 1e-12)
        p_value = self._fisher_g_test(g_statistic, N // 2)

        # Match against known cycles
        matched = []
        if dominant_period is not None:
            for label, target in [
                ("daily", DAILY_HOURS),
                ("weekly", WEEKLY_HOURS),
                ("seasonal", SEASONAL_HOURS),
            ]:
                error = abs(dominant_period - target) / target
                if error < 0.20:  # within 20% of target period
                    matched.append(label)

        is_recurring = bool(matched) and (p_value is not None and p_value < FOURIER_P_VALUE_THRESHOLD)
        confidence = (1.0 - min(p_value, 1.0)) * (1.0 - min(g_statistic * 3, 1.0)) if p_value is not None else 0.0

        # Also check secondary peaks
        if not is_recurring:
            sorted_indices = np.argsort(power)[::-1]
            for idx in sorted_indices[1:4]:
                if idx == 0:
                    continue
                freq = idx * freq_resolution
                period = 1.0 / freq if freq > 0 else float("inf")
                for label, target in [("daily", DAILY_HOURS), ("weekly", WEEKLY_HOURS), ("seasonal", SEASONAL_HOURS)]:
                    if abs(period - target) / target < 0.20 and label not in matched:
                        g2 = power[idx] / (power.sum() + 1e-12)
                        p2 = self._fisher_g_test(g2, N // 2)
                        if p2 is not None and p2 < FOURIER_P_VALUE_THRESHOLD:
                            matched.append(label)
                            is_recurring = True

        return {
            "is_recurring": is_recurring,
            "dominant_period": dominant_period,
            "p_value": p_value,
            "confidence": max(0.0, min(1.0, confidence)),
            "matched_cycles": matched,
        }

    @staticmethod
    def _fisher_g_test(g: float, m: int) -> Optional[float]:
        """Fisher's g-test for the largest periodogram ordinate.

        H₀: signal is white noise (no periodic component).
        p = m * (1 - g)^{m-1}  (approximate for large m).
        """
        if m <= 0 or not (0 < g < 1):
            return None
        g = min(g, 0.999)
        p = m * (1.0 - g) ** (m - 1)
        return min(p, 1.0)

    # ── Spearman correlation ─────────────────────────────────

    def _spearman_classify(
        self,
        stress_signal: np.ndarray,
        population_signal: np.ndarray,
        window_months: int = 12,
    ) -> Dict:
        """Compute rolling Spearman ρ between stress and population growth.

        Uses a 12-month rolling window to detect density-driven stress.
        Returns dict with is_density_driven, rho, confidence.
        """
        T = len(stress_signal)
        min_len = 720  # 30 days hourly

        if T < min_len:
            return {"is_density_driven": False, "rho": 0.0, "confidence": 0.0}

        # Match lengths
        n = min(len(stress_signal), len(population_signal))
        s = stress_signal[:n]
        p = population_signal[:n]

        # Compute population growth rate (first difference, then smooth)
        pop_growth = np.diff(p, prepend=p[0])
        pop_growth = np.convolve(pop_growth, np.ones(24) / 24, mode="same")  # daily smooth

        # Spearman correlation
        rho, p_value = stats.spearmanr(s[24:], pop_growth[24:])

        is_density = (abs(rho) > SPEARMAN_THRESHOLD) and (p_value < 0.05)
        confidence = abs(rho) if is_density else 0.0

        return {
            "is_density_driven": is_density,
            "rho": float(rho),
            "confidence": float(confidence),
        }

    # ── Hybrid attribution ───────────────────────────────────

    def _attribute_hybrid(
        self,
        stress_signal: np.ndarray,
        population_signal: np.ndarray,
        fourier_result: Dict,
        spearman_result: Dict,
    ) -> Tuple[float, float]:
        """Compute relative contribution of recurring vs density-driven.

        Uses partial correlation: residual stress after removing density trend
        is attributed to recurring, and vice versa.
        """
        n = min(len(stress_signal), len(population_signal))
        s = stress_signal[:n]
        p = population_signal[:n]

        # Compute density trend via LOWESS-like rolling mean
        window = max(24, n // 30)
        density_trend = np.convolve(p, np.ones(window) / window, mode="same")[:n]
        density_trend = (density_trend - density_trend.min()) / (density_trend.max() - density_trend.min() + 1e-12)

        # Residual after removing density component
        residual = s - np.polyval(np.polyfit(density_trend, s, 2), density_trend)

        # Fraction of variance explained by density trend
        ss_total = np.var(s) + 1e-12
        ss_residual = np.var(residual) + 1e-12
        density_explained = 1.0 - ss_residual / ss_total

        # Recurring component: variance of the detrended signal at cycle frequencies
        recurring_explained = 1.0 - density_explained

        density_pct = max(HYBRID_MIN_PCT, min(100.0 - HYBRID_MIN_PCT, density_explained * 100.0))
        recurrence_pct = 100.0 - density_pct

        # Normalise
        total = recurrence_pct + density_pct
        recurrence_pct = (recurrence_pct / total) * 100.0
        density_pct = (density_pct / total) * 100.0

        logger.debug(
            "Hybrid attribution: recurring=%.1f%%, density=%.1f%% (ρ=%.3f, period=%s)",
            recurrence_pct, density_pct,
            spearman_result.get("rho", 0.0),
            fourier_result.get("dominant_period", "?"),
        )
        return recurrence_pct, density_pct


# ──────────────────────────────────────────────────────────────
# Convenience: classify an entire GeoDataFrame
# ──────────────────────────────────────────────────────────────


def classify_geodataframe(
    gdf: "geopandas.GeoDataFrame",
    stress_column: str = "stress_ml",
    density_column: Optional[str] = None,
    timestamps: Optional[np.ndarray] = None,
) -> "geopandas.GeoDataFrame":
    """Classify all rows in a simulation GeoDataFrame.

    Adds columns: classification_type, confidence, dominant_period_hours,
    spearman_rho, recurrence_pct, density_pct.

    Args:
        gdf: simulation output GeoDataFrame.
        stress_column: column with stress values [0,1].
        density_column: column with population density (optional).
        timestamps: datetime64 array for time-indexed analysis.

    Returns:
        Same GeoDataFrame with classification columns appended.
    """
    classifier = StressClassifier()
    results: List[Dict] = []

    for idx, row in gdf.iterrows():
        stress_val = row.get(stress_column, 0.5)
        density_val = row.get(density_column, 100) if density_column else 100.0

        # Build synthetic history from the single stress value + noise
        # In production, pull actual history from TimescaleDB
        T = 720  # 30 days hourly
        np.random.seed(hash(str(idx)) % (2**31))
        base = np.full(T, stress_val, dtype=np.float64)

        if stress_val > 0.5:
            daily = 0.05 * np.sin(2 * np.pi * np.arange(T) / 24)
            weekly = 0.03 * np.sin(2 * np.pi * np.arange(T) / 168)
            trend = np.linspace(0, 0.1 * (stress_val - 0.5), T)
            noise = np.random.normal(0, 0.02, T)
            history = base + daily + weekly + trend + noise
        else:
            noise = np.random.normal(0, 0.01, T)
            history = base + noise

        pop = np.full(T, density_val, dtype=np.float64) + np.cumsum(np.random.normal(0.001, 0.5, T))
        pop = np.abs(pop)

        cr = classifier.classify(history, pop)
        results.append(cr.to_dict())

    for col in [
        "classification_type",
        "confidence",
        "dominant_period_hours",
        "spearman_rho",
        "recurrence_pct",
        "density_pct",
        "classification_pvalue",
        "significant_cycles",
    ]:
        gdf[col] = [r[col] for r in results]

    return gdf
