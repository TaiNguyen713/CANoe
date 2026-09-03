"""Lớp backend đo — ranh giới giữa UI và engine thực thi.

Phase 2: hiện thực `MeasurementBackend` bằng framework thật rồi truyền vào
`MainWindow(backend=...)`; UI không cần thay đổi.
"""

from .base import (BusEvent, BusStatistics, Direction, EventKind,
                   MeasurementBackend, MeasurementState)
from .simulated import SimulatedBackend

__all__ = [
    "BusEvent", "BusStatistics", "Direction", "EventKind",
    "MeasurementBackend", "MeasurementState", "SimulatedBackend",
]
