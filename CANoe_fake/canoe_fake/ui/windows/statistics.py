"""Statistics Window — bus load, frame counts, errors, and a load-over-time chart."""

from __future__ import annotations

from collections import defaultdict, deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel,
                               QSplitter, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ...backend.base import BusStatistics
from ..theme import PALETTE, mono_font, ui_font

HISTORY_POINTS = 240      # ~2 minutes at a 500 ms tick


class BusLoadChart(QWidget):
    """A hand-drawn (QPainter) line chart of bus load over time."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(110)
        self._series: dict[int, deque[float]] = defaultdict(
            lambda: deque(maxlen=HISTORY_POINTS))
        self._colors = [PALETTE.accent, PALETTE.running, PALETTE.paused, "#7d5aa0"]

    def push(self, channel: int, load: float) -> None:
        self._series[channel].append(load)
        self.update()

    def clear(self) -> None:
        self._series.clear()
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(34, 8, -8, -18)

        painter.fillRect(self.rect(), QColor(PALETTE.surface))
        painter.setPen(QPen(QColor(PALETTE.canvas_grid), 1))
        painter.setFont(ui_font(7))
        for i in range(5):
            y = rect.bottom() - rect.height() * i / 4
            painter.setPen(QPen(QColor(PALETTE.canvas_grid), 1))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(QColor(PALETTE.text_muted))
            painter.drawText(QRectF(0, y - 7, 30, 14),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{i * 25}%")

        painter.setPen(QPen(QColor(PALETTE.border), 1))
        painter.drawRect(rect)

        if not self._series:
            painter.setPen(QColor(PALETTE.text_disabled))
            painter.setFont(ui_font(9))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             "No data yet — start the measurement to see bus load")
            return

        for index, (channel, values) in enumerate(sorted(self._series.items())):
            if len(values) < 2:
                continue
            color = QColor(self._colors[index % len(self._colors)])
            path = QPainterPath()
            step = rect.width() / max(1, HISTORY_POINTS - 1)
            start = rect.width() - step * (len(values) - 1)
            for i, value in enumerate(values):
                x = rect.left() + start + step * i
                y = rect.bottom() - rect.height() * min(100.0, value) / 100.0
                if i == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.setPen(QPen(color, 1.6))
            painter.drawPath(path)

            fill = QPainterPath(path)
            fill.lineTo(rect.right(), rect.bottom())
            fill.lineTo(rect.left() + start, rect.bottom())
            fill.closeSubpath()
            color.setAlpha(38)
            painter.fillPath(fill, color)

            painter.setPen(QColor(self._colors[index % len(self._colors)]))
            painter.setFont(ui_font(7, bold=True))
            painter.drawText(QPointF(rect.left() + 6 + index * 66, rect.top() + 12),
                             f"CAN {channel}: {values[-1]:.1f}%")


class StatisticsWindow(QWidget):
    """Bus statistics table + load chart."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([
            "Channel", "Bus load", "Peak", "Frames/s", "Total Frames",
            "Tx", "Rx", "Error Frames", "Baudrate", "Controller State",
        ])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setFont(ui_font(9))
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        splitter.addWidget(self.tree)

        chart_box = QWidget()
        chart_layout = QVBoxLayout(chart_box)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(0)
        caption = QLabel("  Bus Load Over Time")
        caption.setFont(ui_font(9, bold=True))
        caption.setStyleSheet(
            f"background: {PALETTE.panel_header}; color: {PALETTE.text_muted};"
            f" border-top: 1px solid {PALETTE.border};"
            f" border-bottom: 1px solid {PALETTE.border_light}; padding: 4px;")
        chart_layout.addWidget(caption)
        self.chart = BusLoadChart()
        chart_layout.addWidget(self.chart, 1)
        splitter.addWidget(chart_box)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self._rows: dict[int, QTreeWidgetItem] = {}

    # ------------------------------------------------------------------
    def update_statistics(self, stat: BusStatistics) -> None:
        item = self._rows.get(stat.channel)
        if item is None:
            item = QTreeWidgetItem()
            item.setFont(0, ui_font(9, bold=True))
            for column in range(1, 10):
                item.setFont(column, mono_font(9))
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(item)
            self._rows[stat.channel] = item

        item.setText(0, f"CAN {stat.channel}")
        item.setText(1, f"{stat.bus_load_percent:6.2f} %")
        item.setText(2, f"{stat.peak_load_percent:6.2f} %")
        item.setText(3, f"{stat.frames_per_second:7.1f}")
        item.setText(4, f"{stat.frames_total:,}")
        item.setText(5, f"{stat.tx_count:,}")
        item.setText(6, f"{stat.rx_count:,}")
        item.setText(7, str(stat.error_frames))
        item.setText(8, f"{stat.baudrate // 1000} kBaud")
        item.setText(9, stat.controller_state)

        load_color = (PALETTE.error if stat.bus_load_percent > 70
                      else PALETTE.warning if stat.bus_load_percent > 45
                      else PALETTE.running)
        item.setForeground(1, QColor(load_color))
        item.setForeground(7, QColor(PALETTE.error if stat.error_frames else
                                     PALETTE.text_muted))
        item.setForeground(9, QColor(PALETTE.running if stat.controller_state ==
                                     "Error active" else PALETTE.warning))
        self.chart.push(stat.channel, stat.bus_load_percent)

    def reset(self) -> None:
        self.tree.clear()
        self._rows.clear()
        self.chart.clear()
