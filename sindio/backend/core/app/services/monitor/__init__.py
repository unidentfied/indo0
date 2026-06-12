"""
Sindio — Unified Infrastructure Monitoring
============================================

Single parameterized system for ALL infrastructure types.
Infrastructure type is just a config key.

Usage:
    from app.services.monitor import InfrastructureMonitor, get_all_stressed_assets

    # Single type
    mon = InfrastructureMonitor("power")
    result = mon.run()

    # All types at once
    all_stressed = get_all_stressed_assets()
"""

from .registry import (
    INFRA_REGISTRY,
    InfraConfig,
    InfraThresholds,
    InfraSchedule,
    InfraActions,
    InfraDataSource,
    PhysicsEngine,
    get_config,
    get_all_configs,
    get_names,
    get_by_physics_engine,
)
from .monitor import InfrastructureMonitor, AssetState, MonitorResult, get_all_stressed_assets
from .ingestion import DataIngestor
from .baseline import BaselineComparator
from .reports import ReportIntegrator
from .stress import StressCalculator

__all__ = [
    "INFRA_REGISTRY",
    "InfraConfig",
    "InfraThresholds",
    "InfraSchedule",
    "InfraActions",
    "InfraDataSource",
    "PhysicsEngine",
    "get_config",
    "get_all_configs",
    "get_names",
    "get_by_physics_engine",
    "InfrastructureMonitor",
    "AssetState",
    "MonitorResult",
    "get_all_stressed_assets",
    "DataIngestor",
    "BaselineComparator",
    "ReportIntegrator",
    "StressCalculator",
]
