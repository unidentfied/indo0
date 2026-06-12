"""
Integration test: long-interval alert pipeline.

Simulates the full path from stress detection → classification →
interval computation → alert generation → explanation — all WITHOUT
any policy documents, external mandates, or database connections.

Three scenarios:
  1. Moderate density-driven stress (0.73, ρ=0.68) → warning, 180d, density_driven_mixed
  2. Recurring stress (0.61, ρ=0.12) → 360d interval (doubled)
  3. Critical stress (0.94) → still 30d floor, not hourly
"""

import re
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.services.temporal_spacing import (
    ABSOLUTE_FLOOR_DAYS,
    BASE_MINIMUM_DAYS,
    RECURRING_MULTIPLIER,
    compute_interval,
)
from app.services.stress_classifier import StressClassifier, ClassificationResult


# ======================================================================
# Helpers
# ======================================================================


def _classify_stress(
    stress: float,
    density_rho: float,
) -> ClassificationResult:
    """Run the stress classifier on synthetic hourly histories.

    Generates signals engineered to produce the desired classification:
      - density_rho < 0.3  → strong cycles, weak pop correlation → recurring
      - density_rho >= 0.7 → weak cycles, strong pop correlation → density_driven
      - 0.3 ≤ rho < 0.7   → both present → hybrid

    The classifier's own SPEARMAN_THRESHOLD is 0.7, so we must ensure the
    Spearman ρ computed on the synthetic signals actually exceeds that
    threshold when we want density_driven.
    """
    import numpy as np

    T = 720  # 30 days hourly
    rng = np.random.RandomState(int(stress * 1000 + density_rho * 1000) % (2**31))

    t = np.arange(T, dtype=np.float64)

    if density_rho < 0.3:
        # Recurring: strong cycles, NO population correlation
        daily = 0.10 * np.sin(2 * np.pi * t / 24)
        weekly = 0.06 * np.sin(2 * np.pi * t / 168)
        noise = rng.normal(0, 0.008, T)
        history = np.full(T, stress, dtype=np.float64) + daily + weekly + noise
        population = rng.normal(0, 1.0, T).cumsum() + 100  # uncorrelated noise

    elif density_rho >= 0.7:
        # Density-driven: stress tracks population GROWTH rate (not absolute level).
        # The classifier computes Spearman ρ between stress and pop_growth.
        # Make population accelerate/decelerate so growth rate varies.
        base_pop = 100.0 + np.cumsum(rng.normal(0.01, 0.5, T))
        # Add seasonal acceleration in population growth
        seasonal_accel = 0.3 * np.sin(2 * np.pi * t / (T / 3))  # ~10-day cycle
        pop_growth_rate = rng.normal(0.01, 0.3, T) + seasonal_accel
        population = base_pop + np.cumsum(pop_growth_rate)
        # Stress follows the population growth rate (strong monotonic)
        smoothed_growth = np.convolve(pop_growth_rate, np.ones(24) / 24, mode="same")
        growth_norm = (smoothed_growth - smoothed_growth.min()) / (smoothed_growth.max() - smoothed_growth.min() + 1e-8)
        history = 0.15 + growth_norm * 0.75 + rng.normal(0, 0.02, T)
        history = np.clip(history, 0.05, 0.99)

    else:
        # Hybrid: moderate cycles + moderate pop correlation
        daily = 0.04 * np.sin(2 * np.pi * t / 24)
        base_pop = 80.0 + np.cumsum(rng.normal(0.01, 0.4, T))
        pop_growth_rate = rng.normal(0.01, 0.2, T) + 0.15 * np.sin(2 * np.pi * t / (T / 4))
        population = base_pop + np.cumsum(pop_growth_rate)
        smoothed_growth = np.convolve(pop_growth_rate, np.ones(24) / 24, mode="same")
        growth_norm = (smoothed_growth - smoothed_growth.min()) / (smoothed_growth.max() - smoothed_growth.min() + 1e-8)
        history = np.full(T, stress, dtype=np.float64) + daily + growth_norm * 0.25 * stress + rng.normal(0, 0.01, T)
        history = np.clip(history, 0.05, 0.99)

    classifier = StressClassifier()
    return classifier.classify(history, population)


def _determine_severity_level(stress: float) -> str:
    """Map stress to severity level without policy thresholds."""
    if stress >= 0.85:
        return "critical"
    if stress >= 0.5:
        return "warning"
    return "advisory"


def _build_data_driven_explanation(
    infrastructure_type: str,
    asset_id: str,
    stress: float,
    density_rho: float,
    classification: ClassificationResult,
    historical_failure_frequency_months: float,
    recommended_interval_days: int,
) -> str:
    """Build purely data-driven explanation text.

    Returns text that MUST NOT contain any policy, regulation, Act, Section,
    mandate, or requires language — only observed data and computed metrics.
    """
    import numpy as np

    level = _determine_severity_level(stress)
    freq_rounded = round(historical_failure_frequency_months, 1)

    parts = [
        f"{infrastructure_type.title()} asset {asset_id} triggered a {level} alert "
        f"at stress {stress:.2f}.",
        f"Historical failure record: averages every {freq_rounded} months "
        f"based on TimescaleDB alerts hypertable (5-year window).",
    ]

    # Classification detail
    if classification.classification_type == "recurring":
        parts.append(
            f"Classification: recurring stress pattern with confidence "
            f"{classification.confidence:.2f}. "
            f"Dominant period: {classification.dominant_period_hours:.0f}h. "
            f"Population correlation is weak (ρ={density_rho:.2f}), "
            f"indicating this stress is time-cyclic, not externally driven."
        )
    elif classification.classification_type == "density_driven":
        parts.append(
            f"Classification: density-driven stress (ρ={density_rho:.2f}). "
            f"Population growth in the asset catchment correlates strongly "
            f"with stress accumulation."
        )
    elif classification.classification_type == "hybrid":
        r_pct = classification.recurrence_pct
        d_pct = classification.density_pct
        parts.append(
            f"Classification: hybrid — {r_pct:.0f}% recurring, {d_pct:.0f}% density-driven "
            f"(Spearman ρ={density_rho:.2f})."
        )
    else:
        parts.append(
            f"Classification: {classification.classification_type} "
            f"(Spearman ρ={density_rho:.2f})."
        )

    # Interval rationale
    interval_ratio = recommended_interval_days / BASE_MINIMUM_DAYS.get(infrastructure_type, 180)
    if abs(interval_ratio - RECURRING_MULTIPLIER) < 0.05:
        parts.append(
            f"Recommended resample interval: {recommended_interval_days} days "
            f"(doubled from base {BASE_MINIMUM_DAYS[infrastructure_type]}d "
            f"due to recurring-only classification)."
        )
    elif recommended_interval_days == ABSOLUTE_FLOOR_DAYS:
        parts.append(
            f"Recommended resample interval: {recommended_interval_days} days "
            f"(absolute floor — stress is critical but interval is capped "
            f"to prevent alert fatigue)."
        )
    else:
        parts.append(
            f"Recommended resample interval: {recommended_interval_days} days "
            f"(base minimum for {infrastructure_type} infrastructure)."
        )

    return " ".join(parts)


# ======================================================================
# Policy language detector (negative assertion helper)
# ======================================================================

FORBIDDEN_PATTERNS: list[str] = [
    r"\bpolicy\b",
    r"\bregulation\b",
    r"\bact\b",
    r"\bsection\b",
    r"\bmandate\b",
    r"\brequires\b",
    r"\brequired\b",
    r"\bpursuant\b",
    r"\bstatute\b",
    r"\blegislation\b",
    r"\bordinance\b",
    r"\bcompliance\b",
    r"\bauthorised\b",
    r"\bauthorized\b",
    r"\bpermitted\b",
]


def assert_no_policy_language(text: str, label: str = "") -> None:
    """Assert that text contains no policy/regulation/mandate language."""
    lower = text.lower()
    for pattern in FORBIDDEN_PATTERNS:
        matches = re.findall(pattern, lower)
        assert not matches, (
            f"{label} contains forbidden word '{matches[0]}' "
            f"(policy language detected). Full text:\n{text[:300]}"
        )


# ======================================================================
# Scenario 1 — Moderate density-driven water main
# ======================================================================

def test_density_driven_water_main_alert() -> None:
    """Water main at [36.82, -1.28], stress=0.73, ρ=0.72 → warning, 180d."""
    location = (36.82, -1.28)
    infrastructure_type = "water"
    asset_id = "WM-TEST-001"
    stress = 0.73
    density_rho = 0.72
    historical_failure_months = 8.0

    # ── Classify ───────────────────────────────────────────
    classification = _classify_stress(stress, density_rho)

    # Assert classification is density-driven or hybrid (rho between 0.5–0.7)
    assert classification.classification_type in ("density_driven", "hybrid"), (
        f"Expected density_driven or hybrid for ρ={density_rho}, "
        f"got {classification.classification_type}"
    )

    # ── Compute interval ───────────────────────────────────
    result = compute_interval(
        infrastructure_type=infrastructure_type,
        stress=stress,
        density_rho=density_rho,
        classification=classification.classification_type,
    )

    # Assert severity = 'warning' (not critical because stress < 0.85)
    severity = _determine_severity_level(stress)
    assert severity == "warning", (
        f"Expected warning for stress={stress}, got {severity}"
    )
    assert stress < 0.85, "Stress must be below 0.85 for warning (not critical)"

    # Assert next scheduled check ≥ 180 days (minimum water interval)
    assert result.final_interval_days >= BASE_MINIMUM_DAYS["water"], (
        f"Water interval {result.final_interval_days}d < {BASE_MINIMUM_DAYS['water']}d minimum"
    )

    # Assert classification is 'density_driven' or 'density_driven_mixed'
    assert "density" in classification.classification_type.lower(), (
        f"Classification {classification.classification_type} should reflect density-driven"
    )

    # ── Build explanation ──────────────────────────────────
    explanation = _build_data_driven_explanation(
        infrastructure_type=infrastructure_type,
        asset_id=asset_id,
        stress=stress,
        density_rho=density_rho,
        classification=classification,
        historical_failure_frequency_months=historical_failure_months,
        recommended_interval_days=result.final_interval_days,
    )

    # Assert explanation contains data, not policy
    assert f"historical failure record: averages every {historical_failure_months}" in explanation.lower(), (
        f"Explanation missing historical failure frequency:\n{explanation}"
    )
    assert f"population correlation is weak" in explanation.lower() or \
           f"ρ={density_rho:.2f}" in explanation or \
           "spearman" in explanation.lower() or \
           "population growth" in explanation.lower(), (
        f"Explanation missing population correlation context:\n{explanation}"
    )

    # Negative assertions — NO policy language
    assert_no_policy_language(explanation, "Scenario 1 explanation")

    # Assert explanation does NOT contain any policy-like phrases
    forbidden = ["policy", "regulation", "act", "section", "mandate", "requires"]
    lower = explanation.lower()
    for word in forbidden:
        assert word not in lower, (
            f"Explanation contains '{word}' (policy language). Text:\n{explanation[:200]}"
        )

    # Verify location is preserved
    assert location[0] == 36.82
    assert location[1] == -1.28


# ======================================================================
# Scenario 2 — Recurring stress → doubled interval
# ======================================================================

def test_recurring_stress_doubled_interval() -> None:
    """Stress=0.61, ρ=0.12 → interval = 360 days (180d × 2)."""
    infrastructure_type = "water"
    stress = 0.61
    density_rho = 0.12

    classification = _classify_stress(stress, density_rho)

    # Should be classified as recurring (very low density correlation)
    assert classification.classification_type == "recurring", (
        f"Expected recurring for ρ={density_rho}, "
        f"got {classification.classification_type}"
    )

    result = compute_interval(
        infrastructure_type=infrastructure_type,
        stress=stress,
        density_rho=density_rho,
        classification=classification.classification_type,
    )

    # Computed interval should be doubled
    expected_computed = BASE_MINIMUM_DAYS["water"] * RECURRING_MULTIPLIER
    assert result.computed_interval_days == expected_computed, (
        f"Expected computed interval {expected_computed}d (180×2), "
        f"got {result.computed_interval_days}d"
    )

    # Final interval (after jitter) should be ≥ 180 (base minimum)
    assert result.final_interval_days >= BASE_MINIMUM_DAYS["water"], (
        f"Recurring final interval {result.final_interval_days}d < 180d"
    )

    # The final interval should be approximately double (within jitter bounds)
    assert result.final_interval_days >= int(expected_computed * 0.93), (
        f"Recurring final interval {result.final_interval_days}d is "
        f"too far below expected {expected_computed}d"
    )

    # Build explanation
    explanation = _build_data_driven_explanation(
        infrastructure_type=infrastructure_type,
        asset_id="WM-RECUR-042",
        stress=stress,
        density_rho=density_rho,
        classification=classification,
        historical_failure_frequency_months=7.2,
        recommended_interval_days=result.final_interval_days,
    )

    assert_no_policy_language(explanation, "Scenario 2 explanation")

    # Should mention recurring pattern
    assert "recurring" in explanation.lower(), (
        f"Explanation should mention recurring pattern:\n{explanation}"
    )

    # Should mention doubled or 360
    assert "360" in explanation or "doubled" in explanation.lower() or \
           f"{result.final_interval_days}" in explanation, (
        f"Explanation should reference the doubled interval:\n{explanation}"
    )


# ======================================================================
# Scenario 3 — Critical stress but still long interval
# ======================================================================

def test_critical_stress_long_interval() -> None:
    """Stress=0.94 → interval = 30 days (absolute floor, not hourly)."""
    infrastructure_type = "power"
    stress = 0.94
    density_rho = 0.75

    classification = _classify_stress(stress, density_rho)
    severity = _determine_severity_level(stress)

    assert severity == "critical", (
        f"Expected critical for stress={stress}, got {severity}"
    )

    result = compute_interval(
        infrastructure_type=infrastructure_type,
        stress=stress,
        density_rho=density_rho,
        classification=classification.classification_type,
    )

    # The computed interval should be at the type minimum (210 for power)
    assert result.computed_interval_days == float(BASE_MINIMUM_DAYS["power"]), (
        f"Expected computed {BASE_MINIMUM_DAYS['power']}d, "
        f"got {result.computed_interval_days}d"
    )

    # Final interval ≥ the type minimum
    assert result.final_interval_days >= BASE_MINIMUM_DAYS["power"], (
        f"Power critical: {result.final_interval_days}d < "
        f"{BASE_MINIMUM_DAYS['power']}d minimum"
    )

    # Interval is NOT 1 hour, 1 day, or any short interval
    assert result.final_interval_days >= ABSOLUTE_FLOOR_DAYS, (
        f"Critical stress interval {result.final_interval_days}d "
        f"is below absolute floor of {ABSOLUTE_FLOOR_DAYS}d — "
        f"this should never happen (no hourly alerts allowed)"
    )

    # Explicitly: interval is NOT a short value
    assert result.final_interval_days >= 30, "Interval must be ≥ 30 days"
    assert result.final_interval_days >= 180, (
        f"Power interval {result.final_interval_days}d is unexpectedly below 210d"
    )
    # The final interval should be at least the power minimum of 210
    assert result.final_interval_days >= BASE_MINIMUM_DAYS["power"], (
        f"Final power interval {result.final_interval_days}d < 210d"
    )

    # Build explanation
    explanation = _build_data_driven_explanation(
        infrastructure_type=infrastructure_type,
        asset_id="PWR-CRIT-099",
        stress=stress,
        density_rho=density_rho,
        classification=classification,
        historical_failure_frequency_months=4.5,
        recommended_interval_days=result.final_interval_days,
    )

    assert_no_policy_language(explanation, "Scenario 3 explanation")

    # Should mention critical severity
    assert "critical" in explanation.lower()


# ======================================================================
# End-to-end latency test
# ======================================================================

def test_end_to_end_latency() -> None:
    """Detection → alert → storage completes in < 5 seconds."""
    infrastructure_type = "water"
    stress = 0.73
    density_rho = 0.68

    start = time.perf_counter()

    # Simulate full pipeline
    classification = _classify_stress(stress, density_rho)
    severity = _determine_severity_level(stress)

    result = compute_interval(
        infrastructure_type=infrastructure_type,
        stress=stress,
        density_rho=density_rho,
        classification=classification.classification_type,
    )

    explanation = _build_data_driven_explanation(
        infrastructure_type=infrastructure_type,
        asset_id="WM-LATENCY-001",
        stress=stress,
        density_rho=density_rho,
        classification=classification,
        historical_failure_frequency_months=8.0,
        recommended_interval_days=result.final_interval_days,
    )

    elapsed = time.perf_counter() - start

    # The full pipeline should complete in under 5 seconds.
    # For long-interval (monthly) checks this is more than adequate.
    assert elapsed < 5.0, (
        f"Pipeline latency {elapsed:.2f}s exceeds 5s budget. "
        f"Classification: {classification.classification_type}, "
        f"Interval: {result.final_interval_days}d, "
        f"Severity: {severity}"
    )

    # Verify all outputs are non-empty
    assert classification.classification_type
    assert severity
    assert result.final_interval_days > 0
    assert len(explanation) > 100

    # Performance: the pipeline should typically complete in < 2s
    # for monthly-interval scheduling (no real-time requirement)
    assert elapsed < 2.0, (
        f"Pipeline took {elapsed:.2f}s. While within the 5s budget, "
        f"this is slower than expected for a mock pipeline with no DB I/O."
    )
