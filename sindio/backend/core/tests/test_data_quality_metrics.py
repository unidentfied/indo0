import pytest

from app.services.data_quality_metrics import DataQualityMetrics, metrics as dq_metrics


class TestDataQualityMetrics:
    def test_set_real_data_ratio(self):
        dq_metrics.set_real_data_ratio("power", 0.85)
        dq_metrics.set_real_data_ratio("water", 0.92)

    def test_set_mock_fallback_ratio(self):
        dq_metrics.set_mock_fallback_ratio("power", 0.15)
        dq_metrics.set_mock_fallback_ratio("water", 0.08)

    def test_set_model_confidence(self):
        dq_metrics.set_model_confidence("power", 0.78)
        dq_metrics.set_model_confidence("water", 0.83)

    def test_record_fallback_increments_counter(self):
        dq_metrics.record_fallback("power", "postgis_unreachable")
        dq_metrics.record_fallback("water", "api_timeout")

    def test_record_real_fetch_increments_counter(self):
        dq_metrics.record_real_fetch("power", "postgis")
        dq_metrics.record_real_fetch("water", "scada")

    def test_update_ratios_from_counts(self):
        dq_metrics.update_ratios_from_counts("roads", real_count=80, mock_count=20)
        dq_metrics.update_ratios_from_counts("roads", real_count=0, mock_count=0)

    def test_multiple_infra_types_independent(self):
        for infra in ["power", "water", "roads", "solid_waste", "sidewalks"]:
            dq_metrics.record_real_fetch(infra, "test_source")
            dq_metrics.set_real_data_ratio(infra, 0.5)
            dq_metrics.set_model_confidence(infra, 0.6)
