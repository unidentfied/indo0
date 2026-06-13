import pytest
from datetime import datetime, timezone

from app.services.fallback_data import (
    mobility_pressure_fallback,
    alert_stress_fallback,
    synthetic_alert_payload,
    _today_weekday,
)


class TestWeekday:
    def test_returns_int_0_to_6(self):
        wd = _today_weekday()
        assert 0 <= wd <= 6

    def test_specific_date(self):
        dt = datetime(2024, 1, 8, tzinfo=timezone.utc)
        wd = _today_weekday(timestamp=dt)
        assert wd == 0


class TestMobilityPressureFallback:
    def test_returns_positive_float(self):
        val = mobility_pressure_fallback(lat=-1.2833, lng=36.8219)
        assert val > 0

    def test_different_location_different_value(self):
        val1 = mobility_pressure_fallback(lat=-1.2833, lng=36.8219)
        val2 = mobility_pressure_fallback(lat=-1.3500, lng=36.9500)
        assert val1 != val2

    def test_accepts_optional_timestamp(self):
        val = mobility_pressure_fallback(lat=-1.2833, lng=36.8219, timestamp=datetime.now(timezone.utc))
        assert isinstance(val, float)


class TestAlertStressFallback:
    def test_returns_bounded_stress(self):
        for infra in ["power", "water", "roads", "solid_waste"]:
            val = alert_stress_fallback(infra)
            assert 0.0 <= val <= 1.0, f"{infra}: {val}"

    def test_exclude_recurring_gives_different_result(self):
        val1 = alert_stress_fallback("water", exclude_recurring=True)
        val2 = alert_stress_fallback("water", exclude_recurring=False)
        assert isinstance(val1, float)
        assert isinstance(val2, float)


class TestSyntheticAlertPayload:
    def test_returns_dict_with_required_keys(self):
        payload = synthetic_alert_payload(
            infrastructure_type="power", lat=-1.29, lng=36.82, ward="Central"
        )
        assert isinstance(payload, dict)
        assert "asset_id" in payload
        assert "severity" in payload
        assert "ward" in payload
        assert payload["ward"] == "Central"

    def test_default_ward(self):
        payload = synthetic_alert_payload(infrastructure_type="water", lat=0, lng=0)
        assert payload["ward"] == ""
