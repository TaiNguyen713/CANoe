"""Các cửa sổ phân tích và thiết lập của CANoe Fake."""

from .diagnostics import DiagnosticsWindow
from .setup_views import (MeasurementSetupView, SetupPanel, SimulationSetupView)
from .statistics import StatisticsWindow
from .test_feature_set import TestFeatureSetWindow
from .trace import TraceWindow
from .write import WriteWindow

__all__ = [
    "DiagnosticsWindow", "MeasurementSetupView", "SetupPanel",
    "SimulationSetupView", "StatisticsWindow", "TestFeatureSetWindow",
    "TraceWindow", "WriteWindow",
]
