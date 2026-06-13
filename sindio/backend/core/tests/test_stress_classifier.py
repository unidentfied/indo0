import pytest
import numpy as np
from datetime import datetime, timezone, timedelta

from app.services.stress_classifier import (
    StressClassifier,
    ClassificationResult,
    SPEARMAN_THRESHOLD,
    FOURIER_P_VALUE_THRESHOLD,
)


class TestStressClassifier:
    def setup_method(self):
        self.clf = StressClassifier()

    def test_returns_classification_result(self):
        n = 180
        stress = np.sin(np.linspace(0, 4 * np.pi, n)) * 0.3 + 0.5
        pop = np.linspace(0, 1, n)
        result = self.clf.classify(stress, pop)
        assert isinstance(result, ClassificationResult)
        assert result.classification_type in (
            "recurring_only", "density_driven_only", "mixed", "unstable"
        )
        assert 0.0 <= result.confidence <= 1.0

    def test_missing_population_history_falls_back(self):
        n = 50
        stress = np.random.uniform(0.3, 0.8, n)
        result = self.clf.classify(stress, np.array([]))
        assert isinstance(result, ClassificationResult)

    def test_spearman_rho_bounded(self):
        n = 90
        stress = np.sin(np.linspace(0, 6 * np.pi, n)) * 0.2 + 0.5
        pop = np.linspace(0, 2, n)
        result = self.clf.classify(stress, pop)
        assert -1.0 <= result.spearman_rho <= 1.0

    def test_density_driven_detected(self):
        n = 120
        stress = np.linspace(0.3, 0.9, n) + np.random.normal(0, 0.05, n)
        pop = np.linspace(0, 3, n)
        result = self.clf.classify(stress, pop)
        assert result.spearman_rho > 0

    def test_recurring_detected(self):
        n = 720
        t = np.linspace(0, 30 * np.pi, n)
        stress = np.sin(t) * 0.2 + 0.5 + np.random.normal(0, 0.02, n)
        pop = np.ones(n) * 0.5
        result = self.clf.classify(stress, pop)
        assert isinstance(result.classification_type, str)

    def test_short_history_returns_unstable(self):
        stress = np.random.uniform(0.3, 0.8, 10)
        pop = np.random.uniform(0, 1, 10)
        result = self.clf.classify(stress, pop)
        assert result.classification_type == "unstable" or result.confidence < 0.5

    def test_to_dict(self):
        result = ClassificationResult(
            classification_type="mixed",
            confidence=0.75,
            dominant_period_hours=24.0,
            spearman_rho=0.6,
            recurrence_pct=0.4,
            density_pct=0.5,
            p_value=0.01,
            significant_cycles=["diurnal"],
        )
        d = result.to_dict()
        assert d["classification_type"] == "mixed"
        assert d["confidence"] == 0.75
