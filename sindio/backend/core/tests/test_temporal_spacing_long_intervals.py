"""
Tests for temporal spacing long-interval logic.

All assertions are data-driven — no policy documents or external
mandates are referenced.  Intervals derive from historical failure
patterns, stress velocity, density correlation, and asset condition.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.temporal_spacing import (
    ABSOLUTE_FLOOR_DAYS,
    BASE_MINIMUM_DAYS,
    DENSITY_RHO_THRESHOLD,
    RECURRING_MULTIPLIER,
    RECURRING_RHO_THRESHOLD,
    compute_interval,
    get_earliest_water_next_run,
    schedule_batch,
    solid_waste_minimum_interval,
    water_minimum_interval,
    power_minimum_interval,
    roads_minimum_interval,
)


# ======================================================================
# Minimum interval assertions
# ======================================================================

def test_water_minimum_interval() -> None:
    """Water infrastructure interval ≥ 180 days (6 months)."""
    result = compute_interval("water", stress=0.4, density_rho=0.5)
    assert result.final_interval_days >= water_minimum_interval(), (
        f"Expected water interval ≥ {water_minimum_interval()}d, "
        f"got {result.final_interval_days}d — {result.reasoning}"
    )

    # Also check the constant directly
    assert water_minimum_interval() >= 180
    assert BASE_MINIMUM_DAYS["water"] == 180


def test_power_minimum_interval() -> None:
    """Power infrastructure interval ≥ 210 days (7 months)."""
    result = compute_interval("power", stress=0.4, density_rho=0.5)
    assert result.final_interval_days >= power_minimum_interval(), (
        f"Expected power interval ≥ {power_minimum_interval()}d, "
        f"got {result.final_interval_days}d — {result.reasoning}"
    )
    assert power_minimum_interval() >= 210
    assert BASE_MINIMUM_DAYS["power"] == 210


def test_roads_minimum_interval() -> None:
    """Roads interval ≥ 270 days (9 months)."""
    result = compute_interval("roads", stress=0.4, density_rho=0.5)
    assert result.final_interval_days >= roads_minimum_interval(), (
        f"Expected roads interval ≥ {roads_minimum_interval()}d, "
        f"got {result.final_interval_days}d — {result.reasoning}"
    )
    assert roads_minimum_interval() >= 270
    assert BASE_MINIMUM_DAYS["roads"] == 270


def test_solid_waste_minimum_interval() -> None:
    """Solid waste interval ≥ 365 days (12 months)."""
    result = compute_interval("solid_waste", stress=0.4, density_rho=0.5)
    assert result.final_interval_days >= solid_waste_minimum_interval(), (
        f"Expected solid_waste interval ≥ {solid_waste_minimum_interval()}d, "
        f"got {result.final_interval_days}d — {result.reasoning}"
    )
    assert solid_waste_minimum_interval() >= 365
    assert BASE_MINIMUM_DAYS["solid_waste"] == 365


# ======================================================================
# Critical stress never below absolute floor
# ======================================================================

def test_critical_never_below_minimum() -> None:
    """Even if stress > 0.95, interval ≥ 30 days (no hourly alerts)."""
    for infra_type in BASE_MINIMUM_DAYS:
        result = compute_interval(infra_type, stress=0.98, density_rho=0.5)

        assert result.final_interval_days >= ABSOLUTE_FLOOR_DAYS, (
            f"{infra_type} at stress=0.98: interval={result.final_interval_days}d "
            f"< {ABSOLUTE_FLOOR_DAYS}d floor — {result.reasoning}"
        )

        # The interval should be the type minimum (not shortened by stress)
        base = BASE_MINIMUM_DAYS[infra_type]
        if base < ABSOLUTE_FLOOR_DAYS:
            # If type minimum is below absolute floor, the floor takes effect.
            # But with our long intervals (≥180d), this should never happen.
            pass

    # Concrete example: water at extreme stress still ≥ 30d
    r = compute_interval("water", stress=0.99, density_rho=0.5)
    assert r.final_interval_days >= 30, (
        f"Water at stress=0.99 got {r.final_interval_days}d "
        f"(expected ≥ 30d) — {r.reasoning}"
    )


# ======================================================================
# Recurring stress → interval DOUBLES
# ======================================================================

def test_recurring_stress_interval_multiplier() -> None:
    """When stress is purely recurring (ρ_density < 0.3), interval doubles."""
    for infra_type, base in BASE_MINIMUM_DAYS.items():
        result = compute_interval(
            infra_type,
            stress=0.6,
            density_rho=RECURRING_RHO_THRESHOLD - 0.1,  # 0.2 — below threshold
            classification="recurring",
        )

        expected_min = int(base * RECURRING_MULTIPLIER * (1 - 0.05))
        # After jitter (±5%), the interval should be around base * 2
        # We check that it's at least the base — recurring should never
        # shorten; it should be at or above the type minimum
        assert result.final_interval_days >= base, (
            f"{infra_type} recurring: expected interval ≥ {base}d, "
            f"got {result.final_interval_days}d — {result.reasoning}"
        )

        # The computed (pre-jitter) interval should be doubled
        assert result.computed_interval_days == pytest.approx(base * RECURRING_MULTIPLIER, rel=0.01), (
            f"{infra_type} recurring: computed interval {result.computed_interval_days} "
            f"≠ {base * RECURRING_MULTIPLIER} (expected doubled)"
        )

    # Specific examples from the spec
    water_recurring = compute_interval("water", stress=0.6, density_rho=0.2, classification="recurring")
    assert water_recurring.computed_interval_days == 360.0, (
        f"Water recurring: expected 360d (180×2), "
        f"got {water_recurring.computed_interval_days}d"
    )


# ======================================================================
# Density-driven → minimum interval
# ======================================================================

def test_density_driven_stress_minimum() -> None:
    """When ρ_density > 0.7, interval = type minimum — no faster."""
    for infra_type, base in BASE_MINIMUM_DAYS.items():
        result = compute_interval(
            infra_type,
            stress=0.85,
            density_rho=DENSITY_RHO_THRESHOLD + 0.1,  # 0.8 — above threshold
            classification="density_driven",
        )

        assert result.computed_interval_days == float(base), (
            f"{infra_type} density-driven: expected computed {base}d, "
            f"got {result.computed_interval_days}d — {result.reasoning}"
        )

        assert result.final_interval_days >= base, (
            f"{infra_type} density-driven: final interval {result.final_interval_days}d "
            f"< {base}d minimum"
        )

    # Concrete: water at 0.8 ρ → exactly 180d
    water_density = compute_interval("water", stress=0.85, density_rho=0.8, classification="density_driven")
    assert water_density.computed_interval_days == 180.0

    # Roads at 0.8 ρ → exactly 270d
    roads_density = compute_interval("roads", stress=0.85, density_rho=0.8, classification="density_driven")
    assert roads_density.computed_interval_days == 270.0


# ======================================================================
# Jitter never dips below minimum
# ======================================================================

def test_no_jitter_below_minimum() -> None:
    """Jitter is ±5% but absolute value never dips below type minimum."""
    for infra_type, base in BASE_MINIMUM_DAYS.items():
        # Run many iterations to ensure jitter never violates the rule
        for seed in range(1000):
            result = compute_interval(
                infra_type,
                stress=0.5,
                density_rho=0.5,
                random_seed=seed,
            )

            assert result.final_interval_days >= base, (
                f"{infra_type} seed={seed}: interval={result.final_interval_days}d "
                f"< {base}d minimum (jitter={result.applied_jitter_pct:+.1f}%) — "
                f"{result.reasoning}"
            )

            # Jitter should be within ±5%
            assert -5.0 <= result.applied_jitter_pct <= 5.0, (
                f"{infra_type} seed={seed}: jitter={result.applied_jitter_pct:+.2f}% "
                f"outside ±5% range"
            )

    # Verify jitter can increase but never decrease below minimum
    # Even at maximum negative jitter (-5%), the floor is still the type minimum
    for _ in range(100):
        r = compute_interval("water", stress=0.5, density_rho=0.5)
        assert r.final_interval_days >= 180
        # After jitter, the interval should be in [180, 180*1.05 ≈ 189]
        assert 180 <= r.final_interval_days <= 189


# ======================================================================
# Stateful scheduling — 1000 assets
# ======================================================================

def test_stateful_long_schedule() -> None:
    """Schedule 1000 assets; verify earliest water next_run ≥ 180 days."""
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    types = ["water", "power", "roads", "solid_waste"]
    assets = []

    for i in range(1000):
        infra = types[i % len(types)]
        # Vary stress and rho across assets
        stress_val = 0.3 + (i % 7) * 0.1   # 0.3–0.9
        rho = 0.2 + (i % 6) * 0.12          # 0.20–0.92
        assets.append({
            "asset_id": f"AST-{i:04d}",
            "infrastructure_type": infra,
            "stress": stress_val,
            "density_rho": rho,
        })

    schedules = schedule_batch(assets, base_time=now)

    assert len(schedules) == 1000

    # ── Every asset's next_run is in the future ────────────────
    for s in schedules:
        assert s.next_run > now, f"{s.asset_id}: next_run={s.next_run} is not in the future"

    # ── Earliest water next_run ≥ 180 days from now ────────────
    earliest_water = get_earliest_water_next_run(schedules)
    assert earliest_water is not None, "No water assets scheduled"

    min_allowed = now + timedelta(days=180)
    assert earliest_water >= min_allowed, (
        f"Earliest water next_run={earliest_water.isoformat()} is earlier "
        f"than {min_allowed.isoformat()} (180 days from now)"
    )

    # ── Verify water intervals specifically ────────────────────
    water_schedules = [s for s in schedules if s.infrastructure_type == "water"]
    for ws in water_schedules:
        assert ws.interval_days >= 180, (
            f"Water asset {ws.asset_id}: interval={ws.interval_days}d < 180d minimum"
        )

    # ── Verify no absurdly short intervals ─────────────────────
    for s in schedules:
        assert s.interval_days >= 30, (
            f"{s.asset_id}: interval={s.interval_days}d < 30d absolute floor"
        )

    # ── Recurring assets should have proportionally longer intervals ─
    recurring = [s for s in schedules if s.classification == "recurring"
                 and s.density_rho <= RECURRING_RHO_THRESHOLD]
    normal = [s for s in schedules if s.classification not in ("recurring", "density_driven")
              and RECURRING_RHO_THRESHOLD < s.density_rho < DENSITY_RHO_THRESHOLD]

    if recurring and normal:
        avg_recurring = sum(s.interval_days for s in recurring) / len(recurring)
        avg_normal = sum(s.interval_days for s in normal) / len(normal)
        assert avg_recurring >= avg_normal, (
            f"Recurring avg {avg_recurring:.0f}d should ≥ normal avg {avg_normal:.0f}d"
        )


# ======================================================================
# Edge cases
# ======================================================================

def test_unknown_infrastructure_type_raises() -> None:
    """Passing an unknown type raises ValueError."""
    with pytest.raises(ValueError, match="Unknown infrastructure_type"):
        compute_interval("telecom", stress=0.5)

    with pytest.raises(ValueError, match="Unknown infrastructure_type"):
        compute_interval("", stress=0.5)


def test_hybrid_classification_stays_at_minimum() -> None:
    """Hybrid (both recurring + density) uses standard interval."""
    for infra_type in BASE_MINIMUM_DAYS:
        result = compute_interval(
            infra_type,
            stress=0.7,
            density_rho=0.5,
            classification="hybrid",
        )
        base = BASE_MINIMUM_DAYS[infra_type]
        assert result.computed_interval_days == float(base), (
            f"{infra_type} hybrid: computed {result.computed_interval_days}d ≠ {base}d"
        )
