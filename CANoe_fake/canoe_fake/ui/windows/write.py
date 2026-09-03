"""Write Window — where CAPL `write()` output is shown.

Like CANoe: multiple tabs (System, CAPL, Diagnostics...), auto-scroll, clear, save to file.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QPlainTextEdit, QTabWidget,
                               QToolBar, QVBoxLayout, QWidget)

from ..icons import icon
from ..theme import PALETTE, mono_font

MAX_LINES = 5_000

_LEVEL_COLOR = {
    "info": PALETTE.text,
    "capl": PALETTE.text,
    "system": PALETTE.info,
    "warning": PALETTE.warning,
    "error": PALETTE.error,
    "success": PALETTE.running,
    "diag": "#7d5aa0",
}


class _WriteTab(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(mono_font(9))
        self.setMaximumBlockCount(MAX_LINES)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {PALETTE.surface}; color: {PALETTE.text};"
            f" border: none; selection-background-color: {PALETTE.selection}; }}")

    def append_line(self, text: str, level: str, timestamp: str) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = cursor.charFormat()
        fmt.setForeground(QColor(PALETTE.text_muted))
        cursor.setCharFormat(fmt)
        cursor.insertText(f"{timestamp}  ")

        fmt.setForeground(QColor(_LEVEL_COLOR.get(level, PALETTE.text)))
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")


class WriteWindow(QWidget):
    """A multi-tab Write window."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._autoscroll = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.South)
        layout.addWidget(self.tabs, 1)

        self._tabs: dict[str, _WriteTab] = {}
        for name in ("System", "CAPL", "Diagnostics", "Test"):
            self._ensure_tab(name)
        self.tabs.setCurrentIndex(0)

        self.log(
            "CANoe Fake started — Write Window ready. "
            "All CAPL write() output will appear here.", "system", "System")

    # ------------------------------------------------------------------
    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar()
        bar.setIconSize(bar.iconSize() * 0.85)
        bar.addAction(icon("clear"), "Clear Current Tab", self.clear_current)
        bar.addAction(icon("save"), "Save to File...", self.save_current)
        bar.addSeparator()
        self.autoscroll_box = QCheckBox("Auto-scroll")
        self.autoscroll_box.setChecked(True)
        self.autoscroll_box.toggled.connect(self._set_autoscroll)
        bar.addWidget(self.autoscroll_box)
        return bar

    def _ensure_tab(self, name: str) -> _WriteTab:
        if name not in self._tabs:
            tab = _WriteTab(self)
            self._tabs[name] = tab
            self.tabs.addTab(tab, name)
        return self._tabs[name]

    # ------------------------------------------------------------------
    def log(self, text: str, level: str = "info", tab: str = "CAPL",
            timestamp: str | None = None) -> None:
        widget = self._ensure_tab(tab)
        stamp = timestamp or datetime.now().strftime("%H:%M:%S.%f")[:-3]
        widget.append_line(text, level.lower(), stamp)
        if self._autoscroll:
            widget.verticalScrollBar().setValue(widget.verticalScrollBar().maximum())

    def log_measurement(self, elapsed: float, text: str, level: str = "info",
                        tab: str = "CAPL") -> None:
        """Log a line using measurement time instead of the system clock."""
        self.log(text, level, tab, timestamp=f"{elapsed:10.6f}")

    def clear_current(self) -> None:
        widget = self.tabs.currentWidget()
        if isinstance(widget, _WriteTab):
            widget.clear()

    def clear_all(self) -> None:
        for widget in self._tabs.values():
            widget.clear()

    def save_current(self) -> None:
        widget = self.tabs.currentWidget()
        if not isinstance(widget, _WriteTab):
            return
        name = self.tabs.tabText(self.tabs.currentIndex())
        path_text, _ = QFileDialog.getSaveFileName(
            self, "Save Write Window Contents",
            str(Path.home() / f"WriteWindow_{name}.txt"), "Text (*.txt)")
        if path_text:
            Path(path_text).write_text(widget.toPlainText(), encoding="utf-8")
            self.log(f"Saved tab '{name}' contents to {path_text}", "success", "System")

    def _set_autoscroll(self, enabled: bool) -> None:
        self._autoscroll = enabled

    def focus_tab(self, name: str) -> None:
        widget = self._tabs.get(name)
        if widget is not None:
            self.tabs.setCurrentWidget(widget)
