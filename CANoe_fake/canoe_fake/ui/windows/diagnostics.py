"""Diagnostic Console — send/receive UDS services like the CANoe diagnostics window."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ...backend.base import BusEvent, EventKind
from ...model.codec import format_payload, parse_payload
from ...model.database import Configuration, DiagEcu, DiagService
from ..icons import icon
from ..theme import PALETTE, mono_font, ui_font

_NRC_TEXT = {
    0x10: "General reject", 0x11: "Service not supported",
    0x12: "Sub-function not supported", 0x13: "Incorrect message length or format",
    0x14: "Response too long", 0x21: "Busy repeat request",
    0x22: "Conditions not correct", 0x24: "Request sequence error",
    0x31: "Request out of range", 0x33: "Security access denied",
    0x35: "Invalid key", 0x36: "Exceeded number of attempts",
    0x37: "Required time delay not expired", 0x78: "Response pending",
    0x7E: "Sub-function not supported in active session",
    0x7F: "Service not supported in active session",
}


class DiagnosticsWindow(QWidget):
    """Pick an ECU + service, send the request, view the decoded response."""

    send_requested = Signal(str, bytes)     # ECU name, payload

    def __init__(self, config: Configuration, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self._current_ecu: DiagEcu | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_service_tree())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([340, 620])
        layout.addWidget(splitter, 1)

        self.reload(config)

    # ==================================================================
    def _build_service_tree(self) -> QWidget:
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        header = QLabel("  Diagnostic Service Tree (CDD)")
        header.setFont(ui_font(9, bold=True))
        header.setStyleSheet(
            f"background: {PALETTE.panel_header}; color: {PALETTE.text_muted};"
            f" border-bottom: 1px solid {PALETTE.border}; padding: 5px;")
        box.addWidget(header)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Service", "Request"])
        self.tree.setFont(ui_font(9))
        self.tree.setColumnWidth(0, 210)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.itemClicked.connect(self._on_service_selected)
        self.tree.itemDoubleClicked.connect(lambda *_: self.send_request())
        box.addWidget(self.tree, 1)
        return container

    def _build_right_panel(self) -> QWidget:
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(8)

        # -- Request ------------------------------------------------------
        req_group = QGroupBox("Request")
        req_layout = QVBoxLayout(req_group)

        row = QHBoxLayout()
        row.addWidget(QLabel("Target ECU:"))
        self.ecu_combo = QComboBox()
        self.ecu_combo.currentTextChanged.connect(self._on_ecu_changed)
        row.addWidget(self.ecu_combo, 1)
        self.addr_label = QLabel()
        self.addr_label.setFont(mono_font(9))
        self.addr_label.setStyleSheet(f"color: {PALETTE.text_muted};")
        row.addWidget(self.addr_label)
        req_layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Bytes (hex):"))
        self.request_edit = QLineEdit("22 F1 90")
        self.request_edit.setFont(mono_font(10))
        self.request_edit.returnPressed.connect(self.send_request)
        row2.addWidget(self.request_edit, 1)

        self.send_button = QPushButton("Send")
        self.send_button.setIcon(icon("start", 14))
        self.send_button.setDefault(True)
        self.send_button.clicked.connect(self.send_request)
        row2.addWidget(self.send_button)
        req_layout.addLayout(row2)

        self.request_hint = QLabel("Pick a service from the tree on the left, or type bytes directly.")
        self.request_hint.setFont(ui_font(8))
        self.request_hint.setStyleSheet(f"color: {PALETTE.text_muted};")
        self.request_hint.setWordWrap(True)
        req_layout.addWidget(self.request_hint)
        box.addWidget(req_group)

        # -- Response ------------------------------------------------------
        resp_group = QGroupBox("Response")
        resp_layout = QVBoxLayout(resp_group)
        self.response_label = QLabel("— no response yet —")
        self.response_label.setFont(mono_font(11))
        self.response_label.setStyleSheet(f"color: {PALETTE.text_muted};")
        resp_layout.addWidget(self.response_label)

        self.response_detail = QLabel("")
        self.response_detail.setFont(ui_font(9))
        self.response_detail.setWordWrap(True)
        resp_layout.addWidget(self.response_detail)
        box.addWidget(resp_group)

        # -- History --------------------------------------------------------
        hist_group = QGroupBox("Diagnostic Trace")
        hist_layout = QVBoxLayout(hist_group)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setFont(mono_font(9))
        self.history.setMaximumBlockCount(2000)
        self.history.setStyleSheet(
            f"QPlainTextEdit {{ background: {PALETTE.surface};"
            f" border: 1px solid {PALETTE.border}; }}")
        hist_layout.addWidget(self.history)
        box.addWidget(hist_group, 1)
        return container

    # ==================================================================
    def reload(self, config: Configuration) -> None:
        self.config = config
        self.tree.clear()
        self.ecu_combo.blockSignals(True)
        self.ecu_combo.clear()

        for ecu in config.diag_ecus:
            self.ecu_combo.addItem(ecu.name)
            root = QTreeWidgetItem([ecu.name,
                                    f"0x{ecu.request_id:03X} → 0x{ecu.response_id:03X}"])
            root.setIcon(0, icon("diagnostics", 14))
            root.setFont(0, ui_font(9, bold=True))
            root.setToolTip(0, ecu.description)
            self.tree.addTopLevelItem(root)

            groups: dict[int, QTreeWidgetItem] = {}
            for service in ecu.services:
                group = groups.get(service.sid)
                if group is None:
                    group = QTreeWidgetItem([f"SID 0x{service.sid:02X}", ""])
                    group.setForeground(0, QColor(PALETTE.text_muted))
                    root.addChild(group)
                    groups[service.sid] = group
                item = QTreeWidgetItem([service.name, service.request_text])
                item.setFont(1, mono_font(9))
                item.setToolTip(0, service.description)
                item.setData(0, Qt.ItemDataRole.UserRole, (ecu, service))
                group.addChild(item)
            root.setExpanded(True)
            for group in groups.values():
                group.setExpanded(True)

        self.ecu_combo.blockSignals(False)
        if config.diag_ecus:
            self._on_ecu_changed(config.diag_ecus[0].name)

    def _on_ecu_changed(self, name: str) -> None:
        self._current_ecu = next((e for e in self.config.diag_ecus if e.name == name), None)
        if self._current_ecu is not None:
            self.addr_label.setText(
                f"Req 0x{self._current_ecu.request_id:03X} · "
                f"Res 0x{self._current_ecu.response_id:03X}")
        else:
            self.addr_label.setText("")

    def _on_service_selected(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        ecu, service = payload
        self.ecu_combo.setCurrentText(ecu.name)
        self.request_edit.setText(service.request_text)
        self.request_hint.setText(
            service.description or f"Service {service.name} (SID 0x{service.sid:02X})")

    # ==================================================================
    def send_request(self) -> None:
        if self._current_ecu is None:
            self._append_history("No target ECU selected.", PALETTE.warning)
            return
        payload = parse_payload(self.request_edit.text())
        if not payload:
            self._append_history("Invalid byte string — example of a valid one: 22 F1 90",
                                 PALETTE.error)
            return
        self.response_label.setText("… waiting for response")
        self.response_label.setStyleSheet(f"color: {PALETTE.text_muted};")
        self.response_detail.setText("")
        self._append_history(
            f"→ {self._current_ecu.name}  {format_payload(payload)}", PALETTE.tx)
        self.send_requested.emit(self._current_ecu.name, payload)

    def handle_event(self, event: BusEvent) -> None:
        """Receive a diagnostic event from the backend to update the Response section."""
        if event.kind is EventKind.DIAG_RESPONSE:
            self._show_response(event.data, event.detail)
            self._append_history(f"← {event.name}  {event.data_text}", PALETTE.rx)
        elif event.kind is EventKind.DIAG_REQUEST and event.node != "Tester":
            self._append_history(f"→ {event.name}  {event.data_text}", PALETTE.tx)

    def _show_response(self, data: bytes, detail: str) -> None:
        if not data:
            self.response_label.setText("— no data —")
            return
        text = format_payload(data)
        negative = data[0] == 0x7F
        color = PALETTE.error if negative else PALETTE.running
        self.response_label.setText(text)
        self.response_label.setStyleSheet(f"color: {color}; font-weight: 600;")

        lines = [detail] if detail else []
        if negative and len(data) >= 3:
            nrc = data[2]
            lines.append(f"NRC 0x{nrc:02X} — {_NRC_TEXT.get(nrc, 'unknown error code')}")
        elif len(data) > 1:
            printable = "".join(chr(b) if 32 <= b < 127 else "." for b in data[1:])
            lines.append(f"ASCII: {printable}")
        self.response_detail.setText("\n".join(lines))
        self.response_detail.setStyleSheet(f"color: {PALETTE.text};")

    def _append_history(self, text: str, color: str) -> None:
        cursor = self.history.textCursor()
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(color))
        font = QFont(mono_font(9))
        fmt.setFont(font)
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        self.history.verticalScrollBar().setValue(
            self.history.verticalScrollBar().maximum())

    def clear_history(self) -> None:
        self.history.clear()
        self.response_label.setText("— no response yet —")
        self.response_label.setStyleSheet(f"color: {PALETTE.text_muted};")
        self.response_detail.setText("")
