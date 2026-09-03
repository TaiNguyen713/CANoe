"""Giao diện backend đo (measurement) — điểm cắm cho Phase 2.

UI **chỉ** nói chuyện với lớp `MeasurementBackend` này. Muốn thay engine giả
lập bằng framework thật, chỉ cần kế thừa lớp này, hiện thực các phương thức
`_do_*` và phát đúng các signal đã khai báo — không cần sửa bất kỳ widget nào.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal


class MeasurementState(enum.Enum):
    STOPPED = "Stopped"
    RUNNING = "Running"
    PAUSED = "Paused"

    @property
    def label(self) -> str:
        return self.value


class EventKind(str, enum.Enum):
    CAN_FRAME = "CAN Frame"
    CAN_FD_FRAME = "CAN FD Frame"
    ERROR_FRAME = "Error Frame"
    LIN_FRAME = "LIN Frame"
    DIAG_REQUEST = "Diag Request"
    DIAG_RESPONSE = "Diag Response"
    CAPL_WRITE = "CAPL"
    SYSVAR = "System Variable"
    STATISTIC = "Statistic"
    BUS_STATE = "Bus State"


class Direction(str, enum.Enum):
    RX = "Rx"
    TX = "Tx"


@dataclass(slots=True)
class BusEvent:
    """Một dòng trong Trace window."""
    timestamp: float                 # giây kể từ khi bắt đầu measurement
    kind: EventKind
    channel: int = 1
    can_id: int = 0
    name: str = ""
    direction: Direction = Direction.RX
    dlc: int = 0
    data: bytes = b""
    node: str = ""
    detail: str = ""
    is_extended: bool = False

    @property
    def id_text(self) -> str:
        if self.kind in (EventKind.CAPL_WRITE, EventKind.SYSVAR,
                         EventKind.STATISTIC, EventKind.BUS_STATE):
            return ""
        return f"{self.can_id:08X}x" if self.is_extended else f"{self.can_id:03X}"

    @property
    def data_text(self) -> str:
        return " ".join(f"{b:02X}" for b in self.data)

    @property
    def time_text(self) -> str:
        return f"{self.timestamp:.6f}"


@dataclass
class BusStatistics:
    """Số liệu cho Statistics window, tính trên mỗi kênh."""
    channel: int = 1
    bus_load_percent: float = 0.0
    frames_total: int = 0
    frames_per_second: float = 0.0
    tx_count: int = 0
    rx_count: int = 0
    error_frames: int = 0
    peak_load_percent: float = 0.0
    baudrate: int = 500_000
    controller_state: str = "Error active"
    per_message: dict[int, int] = field(default_factory=dict)


class MeasurementBackend(QObject):
    """Lớp cơ sở trừu tượng cho engine đo.

    Signal phát ra:
      - `event_received`   : một dòng mới cho Trace/Write window
      - `statistics_updated`: số liệu bus mới (khoảng 500 ms/lần)
      - `sysvar_changed`   : system variable đổi giá trị
      - `state_changed`    : measurement chuyển trạng thái
      - `signal_updated`   : giá trị signal mới, cho Graphics/Data window
    """

    event_received = Signal(object)          # BusEvent
    events_received = Signal(list)           # list[BusEvent] — gộp để giảm tải UI
    statistics_updated = Signal(object)      # BusStatistics
    sysvar_changed = Signal(str, object)     # qualified_name, value
    signal_updated = Signal(str, float, float)   # "Msg::Signal", giá trị, thời điểm
    state_changed = Signal(object)           # MeasurementState

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = MeasurementState.STOPPED
        self._elapsed = 0.0

    # -- trạng thái ----------------------------------------------------
    @property
    def state(self) -> MeasurementState:
        return self._state

    @property
    def elapsed(self) -> float:
        """Thời gian measurement đã chạy, tính bằng giây."""
        return self._elapsed

    @property
    def is_running(self) -> bool:
        return self._state is MeasurementState.RUNNING

    def _set_state(self, state: MeasurementState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit(state)

    # -- điều khiển ------------------------------------------------------
    def start(self) -> None:
        if self._state is MeasurementState.RUNNING:
            return
        resumed = self._state is MeasurementState.PAUSED
        if not resumed:
            self._elapsed = 0.0
        self._do_start(resumed)
        self._set_state(MeasurementState.RUNNING)

    def pause(self) -> None:
        if self._state is not MeasurementState.RUNNING:
            return
        self._do_pause()
        self._set_state(MeasurementState.PAUSED)

    def stop(self) -> None:
        if self._state is MeasurementState.STOPPED:
            return
        self._do_stop()
        self._set_state(MeasurementState.STOPPED)

    # -- tương tác -------------------------------------------------------
    def send_frame(self, channel: int, can_id: int, data: bytes,
                   name: str = "", is_extended: bool = False) -> None:
        """Gửi một frame lên bus (từ nút Send của UI hoặc từ CAPL)."""
        raise NotImplementedError

    def send_diag_request(self, ecu: str, request: bytes) -> None:
        """Gửi một yêu cầu chẩn đoán tới ECU."""
        raise NotImplementedError

    def set_sysvar(self, qualified_name: str, value) -> None:
        raise NotImplementedError

    def get_sysvar(self, qualified_name: str):
        raise NotImplementedError

    def write_line(self, text: str, source: str = "CAPL") -> None:
        """Đẩy một dòng vào Write window (tương đương write() trong CAPL)."""
        raise NotImplementedError

    # -- phần lớp con phải hiện thực -----------------------------------------
    def _do_start(self, resumed: bool) -> None:
        raise NotImplementedError

    def _do_pause(self) -> None:
        raise NotImplementedError

    def _do_stop(self) -> None:
        raise NotImplementedError
