"""Trace Window — a real-time list of bus events.

Uses a model/view with a ring buffer to stay smooth under high traffic: the
UI only paints the rows currently visible, never one widget per row.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QHeaderView, QLabel, QLineEdit, QTableView,
                               QToolBar, QVBoxLayout, QWidget)

from ...backend.base import BusEvent, Direction, EventKind
from ..icons import icon
from ..theme import PALETTE, mono_font, ui_font

MAX_ROWS = 20_000

_COLUMNS = ("Time", "Chn", "ID", "Name", "Dir", "DLC", "Data", "Node / Detail")
_COLUMN_WIDTH = (96, 42, 78, 168, 42, 42, 232, 300)

_KIND_COLOR = {
    EventKind.ERROR_FRAME: PALETTE.error,
    EventKind.CAPL_WRITE: PALETTE.info,
    EventKind.SYSVAR: PALETTE.statistic,
    EventKind.STATISTIC: PALETTE.statistic,
    EventKind.DIAG_REQUEST: "#7d5aa0",
    EventKind.DIAG_RESPONSE: "#5a3d80",
    EventKind.BUS_STATE: PALETTE.warning,
}


class TraceModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._events: deque[BusEvent] = deque(maxlen=MAX_ROWS)
        self._mono = mono_font(9)
        self._bold = QFont(self._mono)
        self._bold.setBold(True)

    # -- Qt model API ---------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._events)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    # LƯU Ý: Qt truyền `role` xuống dưới dạng int, không phải thành viên enum,
    # nên phải so sánh bằng `==`. Dùng `is` sẽ khiến model trả None cho mọi ô.
    def headerData(self, section: int, orientation: Qt.Orientation,
                   role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section] if 0 <= section < len(_COLUMNS) else None
        return section + 1

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        event = self._events[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._cell(event, column)
        if role == Qt.ItemDataRole.FontRole:
            return self._bold if column == 3 else self._mono
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(self._color(event))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (1, 4, 5):
                return int(Qt.AlignmentFlag.AlignCenter)
            if column in (0, 2):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(event)
        if role == Qt.ItemDataRole.UserRole:
            return event
        return None

    # -- cell content ------------------------------------------------------
    @staticmethod
    def _cell(event: BusEvent, column: int) -> str:
        if column == 0:
            return event.time_text
        if column == 1:
            return str(event.channel) if event.kind not in (
                EventKind.CAPL_WRITE, EventKind.SYSVAR) else ""
        if column == 2:
            return event.id_text
        if column == 3:
            return event.name
        if column == 4:
            return event.direction.value if event.kind not in (
                EventKind.CAPL_WRITE, EventKind.SYSVAR) else ""
        if column == 5:
            return str(event.dlc) if event.dlc else ""
        if column == 6:
            return event.data_text
        return event.detail or event.node

    @staticmethod
    def _color(event: BusEvent) -> str:
        if event.kind in _KIND_COLOR:
            return _KIND_COLOR[event.kind]
        return PALETTE.tx if event.direction is Direction.TX else PALETTE.rx

    @staticmethod
    def _tooltip(event: BusEvent) -> str:
        lines = [f"{event.kind.value} @ {event.time_text} s"]
        if event.name:
            lines.append(f"Name: {event.name}")
        if event.id_text:
            lines.append(f"ID: 0x{event.id_text}")
        if event.data:
            lines.append(f"Data: {event.data_text}")
        if event.node:
            lines.append(f"Node: {event.node}")
        if event.detail:
            lines.append(event.detail)
        return "\n".join(lines)

    # -- updates --------------------------------------------------------
    def append_many(self, events: list[BusEvent]) -> None:
        if not events:
            return
        overflow = max(0, len(self._events) + len(events) - MAX_ROWS)
        if overflow:
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            for _ in range(overflow):
                self._events.popleft()
            self.endRemoveRows()
        start = len(self._events)
        self.beginInsertRows(QModelIndex(), start, start + len(events) - 1)
        self._events.extend(events)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._events.clear()
        self.endResetModel()

    def event_at(self, row: int) -> BusEvent | None:
        return self._events[row] if 0 <= row < len(self._events) else None

    def all_events(self) -> list[BusEvent]:
        return list(self._events)


class TraceWindow(QWidget):
    """Trace window with a toolbar for filtering, freezing, and clearing."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._buffer: list[BusEvent] = []
        self._frozen = False
        self._autoscroll = True
        self._filter_text = ""
        self._filter_kind = "All"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())

        self.model = TraceModel(self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setFont(mono_font(9))
        self.view.setShowGrid(False)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(18)
        self.view.horizontalHeader().setHighlightSections(False)
        for i, width in enumerate(_COLUMN_WIDTH):
            self.view.setColumnWidth(i, width)
        self.view.horizontalHeader().setSectionResizeMode(
            len(_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.view, 1)

        self.status = QLabel("  0 events")
        self.status.setFont(ui_font(8))
        self.status.setStyleSheet(
            f"background: {PALETTE.panel_header}; color: {PALETTE.text_muted};"
            f" border-top: 1px solid {PALETTE.border_light}; padding: 2px;")
        layout.addWidget(self.status)

        # batch updates at 10 Hz so the UI never gets swamped
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(100)
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.start()

    # ------------------------------------------------------------------
    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar()
        bar.setIconSize(bar.iconSize() * 0.85)

        self.act_freeze = bar.addAction(icon("pause"), "Freeze Display")
        self.act_freeze.setCheckable(True)
        self.act_freeze.toggled.connect(self._set_frozen)

        bar.addAction(icon("clear"), "Clear All", self.clear)
        bar.addSeparator()

        bar.addWidget(QLabel(" Filter: "))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("name, ID, or data...")
        self.filter_edit.setMaximumWidth(190)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        bar.addWidget(self.filter_edit)

        self.kind_combo = QComboBox()
        self.kind_combo.addItem("All")
        self.kind_combo.addItems([k.value for k in EventKind])
        self.kind_combo.setMaximumWidth(150)
        self.kind_combo.currentTextChanged.connect(self._on_kind_changed)
        bar.addWidget(self.kind_combo)

        bar.addSeparator()
        self.autoscroll_box = QCheckBox("Auto-scroll")
        self.autoscroll_box.setChecked(True)
        self.autoscroll_box.toggled.connect(self._set_autoscroll)
        bar.addWidget(self.autoscroll_box)
        return bar

    # ------------------------------------------------------------------
    def add_event(self, event: BusEvent) -> None:
        self._buffer.append(event)

    def add_events(self, events: list[BusEvent]) -> None:
        self._buffer.extend(events)

    def clear(self) -> None:
        self._buffer.clear()
        self.model.clear()
        self._update_status()

    def _flush(self) -> None:
        if not self._buffer:
            return
        batch = [e for e in self._buffer if self._passes(e)]
        self._buffer.clear()
        if self._frozen or not batch:
            self._update_status()
            return
        at_bottom = self._at_bottom()
        self.model.append_many(batch)
        if self._autoscroll and at_bottom:
            self.view.scrollToBottom()
        self._update_status()

    def _at_bottom(self) -> bool:
        bar = self.view.verticalScrollBar()
        return bar.value() >= bar.maximum() - 2

    def _passes(self, event: BusEvent) -> bool:
        if self._filter_kind != "All" and event.kind.value != self._filter_kind:
            return False
        if not self._filter_text:
            return True
        needle = self._filter_text.lower()
        return (needle in event.name.lower()
                or needle in event.id_text.lower()
                or needle in event.data_text.lower()
                or needle in event.detail.lower()
                or needle in event.node.lower())

    def _set_frozen(self, frozen: bool) -> None:
        self._frozen = frozen
        self._update_status()

    def _set_autoscroll(self, enabled: bool) -> None:
        self._autoscroll = enabled
        if enabled:
            self.view.scrollToBottom()

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text.strip()

    def _on_kind_changed(self, text: str) -> None:
        self._filter_kind = text

    def _update_status(self) -> None:
        parts = [f"{self.model.rowCount()} events"]
        if self._frozen:
            parts.append("FROZEN")
        if self._filter_text or self._filter_kind != "All":
            parts.append("filtered")
        self.status.setText("  " + " · ".join(parts))

    def selected_event(self) -> BusEvent | None:
        rows = self.view.selectionModel().selectedRows()
        return self.model.event_at(rows[0].row()) if rows else None
