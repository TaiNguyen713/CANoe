"""Measurement Setup and Simulation Setup — CANoe's two signature diagrams.

Both are built on QGraphicsScene, which gives selection, dragging, and
Ctrl + wheel zoom for free.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsScene, QGraphicsView,
                               QLabel, QVBoxLayout, QWidget)

from ...model.database import Configuration, NetworkDef, NodeDef
from ..theme import PALETTE, ui_font

NODE_W, NODE_H = 132.0, 52.0
BLOCK_W, BLOCK_H = 128.0, 46.0


# ---------------------------------------------------------------------------
# Base item
# ---------------------------------------------------------------------------

class _BoxItem(QGraphicsItem):
    """A rounded box with a title, subtitle, and letter badge — shared by both diagrams."""

    def __init__(self, title: str, subtitle: str = "", accent: str = PALETTE.accent,
                 width: float = NODE_W, height: float = NODE_H,
                 badge: str = "", payload=None) -> None:
        super().__init__()
        self.title = title
        self.subtitle = subtitle
        self.accent = accent
        self.width = width
        self.height = height
        self.badge = badge
        self.payload = payload
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._hover = False
        self.setToolTip(f"{title}\n{subtitle}" if subtitle else title)

    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, self.width + 4, self.height + 4)

    def anchor_left(self) -> QPointF:
        return self.pos() + QPointF(0, self.height / 2)

    def anchor_right(self) -> QPointF:
        return self.pos() + QPointF(self.width, self.height / 2)

    def anchor_bottom(self) -> QPointF:
        return self.pos() + QPointF(self.width / 2, self.height)

    def anchor_top(self) -> QPointF:
        return self.pos() + QPointF(self.width / 2, 0)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter: QPainter, _option, _widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, self.width, self.height)

        grad = QLinearGradient(0, 0, 0, self.height)
        grad.setColorAt(0.0, QColor(PALETTE.node_fill))
        grad.setColorAt(1.0, QColor(PALETTE.node_fill_alt))
        painter.setBrush(QBrush(grad))

        selected = self.isSelected()
        pen_color = QColor(self.accent if (selected or self._hover)
                           else PALETTE.node_border)
        painter.setPen(QPen(pen_color, 2.0 if selected else 1.0))
        painter.drawRoundedRect(rect, 4, 4)

        # colored strip on the left to categorize the block
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.accent))
        strip = QPainterPath()
        strip.addRoundedRect(QRectF(0, 0, 5, self.height), 3, 3)
        strip.addRect(QRectF(3, 0, 2, self.height))
        painter.drawPath(strip)

        if self.badge:
            painter.setBrush(QColor(self.accent).lighter(170))
            painter.setPen(QPen(QColor(self.accent), 1))
            painter.drawRoundedRect(QRectF(self.width - 24, 6, 18, 14), 3, 3)
            painter.setPen(QColor(self.accent).darker(140))
            painter.setFont(ui_font(7, bold=True))
            painter.drawText(QRectF(self.width - 24, 6, 18, 14),
                             Qt.AlignmentFlag.AlignCenter, self.badge)

        painter.setPen(QColor(PALETTE.text))
        painter.setFont(ui_font(9, bold=True))
        text_rect = QRectF(12, 6, self.width - 38, 18)
        elided = painter.fontMetrics().elidedText(
            self.title, Qt.TextElideMode.ElideRight, int(text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, elided)

        if self.subtitle:
            painter.setPen(QColor(PALETTE.text_muted))
            painter.setFont(ui_font(8))
            sub_rect = QRectF(12, 24, self.width - 20, self.height - 28)
            elided = painter.fontMetrics().elidedText(
                self.subtitle, Qt.TextElideMode.ElideRight, int(sub_rect.width()))
            painter.drawText(sub_rect, Qt.AlignmentFlag.AlignTop, elided)


class _SetupScene(QGraphicsScene):
    """A scene with a faint grid background, like CANoe's design canvas."""

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor(PALETTE.canvas))
        painter.setPen(QPen(QColor(PALETTE.canvas_grid), 1))
        step = 20
        left = int(rect.left()) - int(rect.left()) % step
        top = int(rect.top()) - int(rect.top()) % step
        x = left
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        y = top
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step


class _SetupView(QGraphicsView):
    """Shared view: zoom with Ctrl + wheel, pan the background with the middle mouse button."""

    item_activated = Signal(object)      # payload of the double-clicked item

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(_SetupScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundBrush(QColor(PALETTE.canvas))

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        while item is not None and not isinstance(item, _BoxItem):
            item = item.parentItem()
        if isinstance(item, _BoxItem) and item.payload is not None:
            self.item_activated.emit(item.payload)
        super().mouseDoubleClickEvent(event)

    def reset_zoom(self) -> None:
        self.resetTransform()

    # -- drawing helpers ------------------------------------------------
    def _connect(self, a: QPointF, b: QPointF, color: str = PALETTE.bus_line,
                 width: float = 1.6, dashed: bool = False,
                 arrow: bool = True) -> None:
        """Connect two points with an orthogonal (block-diagram style) line."""
        scene = self.scene()
        pen = QPen(QColor(color), width)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        mid_x = (a.x() + b.x()) / 2
        path = QPainterPath(a)
        if abs(a.y() - b.y()) < 0.5:
            path.lineTo(b)
        else:
            path.lineTo(QPointF(mid_x, a.y()))
            path.lineTo(QPointF(mid_x, b.y()))
            path.lineTo(b)
        scene.addPath(path, pen)

        if arrow:
            head = QPainterPath()
            head.moveTo(b)
            head.lineTo(b + QPointF(-7, -4))
            head.lineTo(b + QPointF(-7, 4))
            head.closeSubpath()
            scene.addPath(head, QPen(QColor(color), 1), QBrush(QColor(color)))

    def _caption(self, text: str, pos: QPointF, color: str = PALETTE.text_muted,
                 size: int = 8, bold: bool = False) -> None:
        item = self.scene().addText(text, ui_font(size, bold))
        item.setDefaultTextColor(QColor(color))
        item.setPos(pos)


# ---------------------------------------------------------------------------
# Measurement Setup
# ---------------------------------------------------------------------------

class MeasurementSetupView(_SetupView):
    """Data flow diagram: bus → filter → analysis windows."""

    open_window_requested = Signal(str)   # analysis window name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.item_activated.connect(self._on_activated)

    def rebuild(self, config: Configuration) -> None:
        scene = self.scene()
        scene.clear()

        y = 40.0
        bus_anchors: list[QPointF] = []

        for net in config.networks:
            bus = _BoxItem(net.name, f"{net.bus_type} · {net.baudrate_text}",
                           PALETTE.accent, NODE_W + 26, NODE_H, badge="BUS")
            bus.setPos(30, y)
            scene.addItem(bus)

            filt = _BoxItem("Filter", "Pass all messages", PALETTE.info,
                            BLOCK_W, BLOCK_H, badge="F")
            filt.setPos(230, y + 3)
            scene.addItem(filt)

            self._connect(bus.anchor_right(), filt.anchor_left())
            bus_anchors.append(filt.anchor_right())
            y += 92

        if not bus_anchors:
            self._caption("The configuration has no bus channels yet.", QPointF(40, 40))
            scene.setSceneRect(scene.itemsBoundingRect().adjusted(-30, -30, 30, 30))
            return

        # a shared rail before branching out to the analysis windows
        rail_x = 420.0
        top = min(p.y() for p in bus_anchors)
        bottom = max(p.y() for p in bus_anchors)
        scene.addLine(rail_x, top - 14, rail_x, bottom + 118,
                      QPen(QColor(PALETTE.bus_line), 2.4))
        for anchor in bus_anchors:
            self._connect(anchor, QPointF(rail_x, anchor.y()), arrow=False)
        self._caption("Measurement bus", QPointF(rail_x - 46, top - 34),
                      PALETTE.text_muted, 8, True)

        analysis = [
            ("Trace", "List of bus events", PALETTE.accent, "T"),
            ("Statistics", "Bus load, frame count, errors", PALETTE.running, "S"),
            ("Write", "CAPL write() output", PALETTE.info, "W"),
            ("Logging", "Write to .blf / .asc", PALETTE.paused, "L"),
        ]
        block_y = top - 14
        for title, subtitle, color, badge in analysis:
            block = _BoxItem(title, subtitle, color, NODE_W + 34, BLOCK_H,
                             badge=badge, payload=title)
            block.setPos(rail_x + 92, block_y)
            scene.addItem(block)
            self._connect(QPointF(rail_x, block_y + BLOCK_H / 2), block.anchor_left())
            block_y += 64

        self._caption("Double-click an analysis block to open the matching window.",
                      QPointF(30, bottom + 132), PALETTE.text_disabled, 8)
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-30, -40, 40, 40))

    def _on_activated(self, payload) -> None:
        if isinstance(payload, str):
            self.open_window_requested.emit(payload)


# ---------------------------------------------------------------------------
# Simulation Setup
# ---------------------------------------------------------------------------

class SimulationSetupView(_SetupView):
    """Network diagram: ECU / simulated nodes hanging off the bus line."""

    node_activated = Signal(object)       # NodeDef

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.item_activated.connect(self._on_activated)

    _KIND_COLOR = {
        "ECU": PALETTE.node_border,
        "Simulated": PALETTE.accent,
        "Tester": "#7d5aa0",
        "Gateway": PALETTE.paused,
    }

    def rebuild(self, config: Configuration) -> None:
        scene = self.scene()
        scene.clear()
        y = 46.0

        for net in config.networks:
            self._build_network(net, y)
            y += 240

        if not config.networks:
            self._caption("The configuration has no networks yet.", QPointF(40, 40))
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-40, -40, 40, 40))

    def _build_network(self, net: NetworkDef, y: float) -> None:
        scene = self.scene()
        spacing = 176.0
        left = 60.0
        count = max(1, len(net.nodes))
        bus_y = y + NODE_H + 54
        bus_right = left + spacing * count + 40

        # network label
        self._caption(net.name, QPointF(left, y - 26), PALETTE.text, 10, True)
        self._caption(f"{net.bus_type} · {net.baudrate_text} · DB: {net.database or '—'}",
                      QPointF(left, y - 8), PALETTE.text_muted, 8)

        # bus line
        pen = QPen(QColor(PALETTE.bus_line), 3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        scene.addLine(left - 20, bus_y, bus_right, bus_y, pen)
        # 120 Ω termination resistors at both ends
        for x in (left - 20, bus_right):
            scene.addLine(x, bus_y - 8, x, bus_y + 8,
                          QPen(QColor(PALETTE.bus_line), 2.0))
        self._caption("120 Ω", QPointF(left - 34, bus_y + 10), PALETTE.text_disabled, 7)
        self._caption("120 Ω", QPointF(bus_right - 6, bus_y + 10),
                      PALETTE.text_disabled, 7)

        for index, node in enumerate(net.nodes):
            color = self._KIND_COLOR.get(node.kind, PALETTE.node_border)
            subtitle = node.capl_file or node.description or node.kind
            badge = {"Simulated": "SIM", "ECU": "HW", "Tester": "TST",
                     "Gateway": "GW"}.get(node.kind, "")
            item = _BoxItem(node.name, subtitle, color, NODE_W, NODE_H,
                            badge=badge, payload=node)
            item.setPos(left + index * spacing, y)
            scene.addItem(item)

            stem = QPen(QColor(PALETTE.bus_line), 1.8)
            scene.addLine(item.anchor_bottom().x(), item.anchor_bottom().y(),
                          item.anchor_bottom().x(), bus_y, stem)
            scene.addEllipse(item.anchor_bottom().x() - 3, bus_y - 3, 6, 6,
                             QPen(QColor(PALETTE.bus_line), 1),
                             QBrush(QColor(PALETTE.bus_line)))

            # truncate so labels of adjacent nodes don't overlap
            tx = ", ".join(node.tx_messages) or "—"
            if len(tx) > 22:
                tx = tx[:21] + "…"
            caption = self.scene().addText(f"Tx: {tx}", ui_font(7))
            caption.setDefaultTextColor(QColor(PALETTE.text_muted))
            caption.setPos(left + index * spacing, bus_y + 12)
            caption.setToolTip(", ".join(node.tx_messages))

        self._caption("Double-click a node to open its CAPL file in CAPL Browser.",
                      QPointF(left, bus_y + 46), PALETTE.text_disabled, 8)

    def _on_activated(self, payload) -> None:
        if isinstance(payload, NodeDef):
            self.node_activated.emit(payload)


# ---------------------------------------------------------------------------

class SetupPanel(QWidget):
    """Wraps a view with a header line — used as a desktop's content."""

    def __init__(self, view: _SetupView, caption: str, parent=None) -> None:
        super().__init__(parent)
        self.view = view
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        label = QLabel("  " + caption)
        label.setFont(ui_font(9, bold=True))
        label.setStyleSheet(
            f"background: {PALETTE.panel_header}; color: {PALETTE.text_muted};"
            f" border-bottom: 1px solid {PALETTE.border}; padding: 5px;")
        layout.addWidget(label)
        layout.addWidget(view, 1)
