"""Icon vẽ bằng QPainter — không phụ thuộc file ảnh ngoài.

Mọi icon đều dựng từ hình học cơ bản nên app chạy được ngay sau khi clone,
không cần thư mục resources.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)

from .theme import PALETTE

_CACHE: dict[tuple[str, int], QIcon] = {}


def _pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def _painter(pm: QPixmap) -> QPainter:
    pt = QPainter(pm)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pt.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    return pt


# ---------------------------------------------------------------------------
# Từng hàm vẽ nhận (painter, kích thước) và vẽ trong hộp [0, s] x [0, s]
# ---------------------------------------------------------------------------

def _draw_start(p: QPainter, s: int) -> None:
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0.0, QColor(PALETTE.running))
    grad.setColorAt(1.0, QColor(PALETTE.running_dark))
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor(PALETTE.running_dark), 1))
    tri = QPolygonF([QPointF(s * 0.26, s * 0.16),
                     QPointF(s * 0.84, s * 0.50),
                     QPointF(s * 0.26, s * 0.84)])
    p.drawPolygon(tri)


def _draw_stop(p: QPainter, s: int) -> None:
    p.setBrush(QColor(PALETTE.stopped))
    p.setPen(QPen(QColor("#8e1b15"), 1))
    p.drawRoundedRect(QRectF(s * 0.22, s * 0.22, s * 0.56, s * 0.56), 2, 2)


def _draw_pause(p: QPainter, s: int) -> None:
    p.setBrush(QColor(PALETTE.paused))
    p.setPen(QPen(QColor("#9c6800"), 1))
    p.drawRoundedRect(QRectF(s * 0.26, s * 0.20, s * 0.18, s * 0.60), 2, 2)
    p.drawRoundedRect(QRectF(s * 0.56, s * 0.20, s * 0.18, s * 0.60), 2, 2)


def _draw_step(p: QPainter, s: int) -> None:
    p.setBrush(QColor(PALETTE.accent))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(QPolygonF([QPointF(s * 0.22, s * 0.20),
                             QPointF(s * 0.62, s * 0.50),
                             QPointF(s * 0.22, s * 0.80)]))
    p.drawRect(QRectF(s * 0.68, s * 0.20, s * 0.12, s * 0.60))


def _sheet(p: QPainter, s: int, fold: bool = True) -> QRectF:
    body = QRectF(s * 0.20, s * 0.10, s * 0.60, s * 0.80)
    p.setBrush(QColor(PALETTE.surface))
    p.setPen(QPen(QColor(PALETTE.node_border), 1))
    if fold:
        path = QPainterPath()
        path.moveTo(body.left(), body.top())
        path.lineTo(body.right() - s * 0.18, body.top())
        path.lineTo(body.right(), body.top() + s * 0.18)
        path.lineTo(body.right(), body.bottom())
        path.lineTo(body.left(), body.bottom())
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(body.right() - s * 0.18, body.top()),
                   QPointF(body.right() - s * 0.18, body.top() + s * 0.18))
        p.drawLine(QPointF(body.right() - s * 0.18, body.top() + s * 0.18),
                   QPointF(body.right(), body.top() + s * 0.18))
    else:
        p.drawRect(body)
    return body


def _draw_new(p: QPainter, s: int) -> None:
    _sheet(p, s)


def _draw_open(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor("#a07a2c"), 1))
    p.setBrush(QColor("#f2c761"))
    path = QPainterPath()
    path.moveTo(s * 0.12, s * 0.30)
    path.lineTo(s * 0.44, s * 0.30)
    path.lineTo(s * 0.52, s * 0.40)
    path.lineTo(s * 0.88, s * 0.40)
    path.lineTo(s * 0.88, s * 0.80)
    path.lineTo(s * 0.12, s * 0.80)
    path.closeSubpath()
    p.drawPath(path)


def _draw_save(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor("#3c5a80"), 1))
    p.setBrush(QColor("#5b82b5"))
    p.drawRect(QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68))
    p.setBrush(QColor(PALETTE.surface))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(s * 0.30, s * 0.16, s * 0.40, s * 0.26))
    p.drawRect(QRectF(s * 0.26, s * 0.54, s * 0.48, s * 0.30))


def _draw_capl(p: QPainter, s: int) -> None:
    body = _sheet(p, s)
    p.setPen(QPen(QColor(PALETTE.accent), max(1, int(s * 0.06))))
    y = body.top() + s * 0.30
    for width in (0.30, 0.24, 0.34, 0.20):
        p.drawLine(QPointF(body.left() + s * 0.08, y),
                   QPointF(body.left() + s * 0.08 + s * width, y))
        y += s * 0.13


def _draw_trace(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.node_border), 1))
    p.setBrush(QColor(PALETTE.surface))
    p.drawRect(QRectF(s * 0.12, s * 0.18, s * 0.76, s * 0.64))
    p.setPen(QPen(QColor(PALETTE.accent), max(1, int(s * 0.07))))
    for i in range(4):
        y = s * 0.30 + i * s * 0.13
        p.drawLine(QPointF(s * 0.20, y), QPointF(s * 0.20 + s * (0.14 + 0.12 * (i % 3)), y))


def _draw_write(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.node_border), 1))
    p.setBrush(QColor("#2b2f36"))
    p.drawRect(QRectF(s * 0.12, s * 0.20, s * 0.76, s * 0.60))
    p.setPen(QPen(QColor("#7fe08a"), max(1, int(s * 0.07))))
    p.drawLine(QPointF(s * 0.20, s * 0.38), QPointF(s * 0.30, s * 0.46))
    p.drawLine(QPointF(s * 0.30, s * 0.46), QPointF(s * 0.20, s * 0.54))
    p.drawLine(QPointF(s * 0.36, s * 0.58), QPointF(s * 0.58, s * 0.58))


def _draw_graphics(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.node_border), 1))
    p.setBrush(QColor(PALETTE.surface))
    p.drawRect(QRectF(s * 0.12, s * 0.18, s * 0.76, s * 0.64))
    p.setPen(QPen(QColor(PALETTE.accent), max(1, int(s * 0.08))))
    path = QPainterPath(QPointF(s * 0.18, s * 0.66))
    path.lineTo(s * 0.34, s * 0.38)
    path.lineTo(s * 0.50, s * 0.58)
    path.lineTo(s * 0.66, s * 0.30)
    path.lineTo(s * 0.82, s * 0.48)
    p.drawPath(path)


def _draw_statistics(p: QPainter, s: int) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    for i, (h, color) in enumerate(((0.30, PALETTE.accent),
                                    (0.52, PALETTE.running),
                                    (0.40, PALETTE.paused))):
        p.setBrush(QColor(color))
        x = s * (0.20 + i * 0.22)
        p.drawRect(QRectF(x, s * 0.82 - s * h, s * 0.15, s * h))
    p.setPen(QPen(QColor(PALETTE.node_border), 1))
    p.drawLine(QPointF(s * 0.12, s * 0.84), QPointF(s * 0.88, s * 0.84))


def _draw_bus(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.bus_line), max(2, int(s * 0.10))))
    p.drawLine(QPointF(s * 0.10, s * 0.62), QPointF(s * 0.90, s * 0.62))
    p.setPen(QPen(QColor(PALETTE.node_border), 1))
    p.setBrush(QColor(PALETTE.node_fill_alt))
    for x in (0.22, 0.50, 0.78):
        p.drawRect(QRectF(s * (x - 0.09), s * 0.22, s * 0.18, s * 0.24))
        p.setPen(QPen(QColor(PALETTE.bus_line), max(1, int(s * 0.06))))
        p.drawLine(QPointF(s * x, s * 0.46), QPointF(s * x, s * 0.62))
        p.setPen(QPen(QColor(PALETTE.node_border), 1))


def _draw_node(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.node_border), 1))
    p.setBrush(QColor(PALETTE.node_fill_alt))
    p.drawRoundedRect(QRectF(s * 0.16, s * 0.24, s * 0.68, s * 0.52), 3, 3)
    p.setPen(QPen(QColor(PALETTE.accent), 1))
    p.drawLine(QPointF(s * 0.24, s * 0.40), QPointF(s * 0.76, s * 0.40))
    p.drawLine(QPointF(s * 0.24, s * 0.52), QPointF(s * 0.60, s * 0.52))


def _draw_diagnostics(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor("#7d5aa0"), max(2, int(s * 0.09))))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(s * 0.16, s * 0.16, s * 0.46, s * 0.46))
    p.drawLine(QPointF(s * 0.58, s * 0.58), QPointF(s * 0.84, s * 0.84))
    p.setPen(QPen(QColor(PALETTE.accent), max(1, int(s * 0.07))))
    p.drawLine(QPointF(s * 0.26, s * 0.40), QPointF(s * 0.34, s * 0.40))
    p.drawLine(QPointF(s * 0.34, s * 0.40), QPointF(s * 0.38, s * 0.30))
    p.drawLine(QPointF(s * 0.38, s * 0.30), QPointF(s * 0.44, s * 0.48))
    p.drawLine(QPointF(s * 0.44, s * 0.48), QPointF(s * 0.52, s * 0.40))


def _draw_test(p: QPainter, s: int) -> None:
    _sheet(p, s)
    p.setPen(QPen(QColor(PALETTE.running), max(2, int(s * 0.10))))
    p.drawLine(QPointF(s * 0.30, s * 0.50), QPointF(s * 0.42, s * 0.64))
    p.drawLine(QPointF(s * 0.42, s * 0.64), QPointF(s * 0.70, s * 0.30))


def _draw_measurement(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.node_border), 1))
    p.setBrush(QColor(PALETTE.node_fill_alt))
    p.drawRect(QRectF(s * 0.08, s * 0.36, s * 0.24, s * 0.24))
    p.drawRect(QRectF(s * 0.66, s * 0.16, s * 0.26, s * 0.22))
    p.drawRect(QRectF(s * 0.66, s * 0.60, s * 0.26, s * 0.22))
    p.setPen(QPen(QColor(PALETTE.bus_line), max(1, int(s * 0.06))))
    p.drawLine(QPointF(s * 0.32, s * 0.48), QPointF(s * 0.50, s * 0.48))
    p.drawLine(QPointF(s * 0.50, s * 0.27), QPointF(s * 0.50, s * 0.71))
    p.drawLine(QPointF(s * 0.50, s * 0.27), QPointF(s * 0.66, s * 0.27))
    p.drawLine(QPointF(s * 0.50, s * 0.71), QPointF(s * 0.66, s * 0.71))


def _draw_filter(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.accent), 1))
    p.setBrush(QColor(PALETTE.accent_light))
    path = QPainterPath()
    path.moveTo(s * 0.14, s * 0.20)
    path.lineTo(s * 0.86, s * 0.20)
    path.lineTo(s * 0.58, s * 0.52)
    path.lineTo(s * 0.58, s * 0.84)
    path.lineTo(s * 0.42, s * 0.72)
    path.lineTo(s * 0.42, s * 0.52)
    path.closeSubpath()
    p.drawPath(path)


def _draw_clear(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.stopped), max(2, int(s * 0.11)),
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(s * 0.26, s * 0.26), QPointF(s * 0.74, s * 0.74))
    p.drawLine(QPointF(s * 0.74, s * 0.26), QPointF(s * 0.26, s * 0.74))


def _draw_search(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.text_muted), max(2, int(s * 0.09))))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(s * 0.18, s * 0.18, s * 0.44, s * 0.44))
    p.drawLine(QPointF(s * 0.58, s * 0.58), QPointF(s * 0.84, s * 0.84))


def _draw_compile(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.accent), max(2, int(s * 0.10)),
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(QPolygonF([QPointF(s * 0.36, s * 0.28),
                              QPointF(s * 0.18, s * 0.50),
                              QPointF(s * 0.36, s * 0.72)]))
    p.drawPolyline(QPolygonF([QPointF(s * 0.64, s * 0.28),
                              QPointF(s * 0.82, s * 0.50),
                              QPointF(s * 0.64, s * 0.72)]))


def _dot(color: str):
    def draw(p: QPainter, s: int) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(s * 0.22, s * 0.22, s * 0.56, s * 0.56))
    return draw


def _badge(letter: str, color: str):
    """Icon dạng chữ cái trong ô bo góc — dùng cho cây outline CAPL."""
    def draw(p: QPainter, s: int) -> None:
        p.setPen(QPen(QColor(color).darker(120), 1))
        p.setBrush(QColor(color).lighter(165))
        p.drawRoundedRect(QRectF(s * 0.10, s * 0.14, s * 0.80, s * 0.72), 3, 3)
        p.setPen(QColor(color).darker(150))
        font = p.font()
        font.setPointSizeF(max(6.0, s * 0.50))
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, letter)
    return draw


def _draw_error(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor("#8e1b15"), 1))
    p.setBrush(QColor(PALETTE.error))
    p.drawEllipse(QRectF(s * 0.14, s * 0.14, s * 0.72, s * 0.72))
    p.setPen(QPen(QColor("white"), max(2, int(s * 0.10)),
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(s * 0.34, s * 0.34), QPointF(s * 0.66, s * 0.66))
    p.drawLine(QPointF(s * 0.66, s * 0.34), QPointF(s * 0.34, s * 0.66))


def _draw_warning(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor("#8a5200"), 1))
    p.setBrush(QColor("#f2b21a"))
    p.drawPolygon(QPolygonF([QPointF(s * 0.50, s * 0.12),
                             QPointF(s * 0.92, s * 0.86),
                             QPointF(s * 0.08, s * 0.86)]))
    p.setPen(QPen(QColor("#4a2c00"), max(2, int(s * 0.10)),
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(s * 0.50, s * 0.40), QPointF(s * 0.50, s * 0.62))
    p.drawPoint(QPointF(s * 0.50, s * 0.74))


def _draw_info(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor("#065f5b"), 1))
    p.setBrush(QColor(PALETTE.info))
    p.drawEllipse(QRectF(s * 0.14, s * 0.14, s * 0.72, s * 0.72))
    p.setPen(QPen(QColor("white"), max(2, int(s * 0.11)),
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPoint(QPointF(s * 0.50, s * 0.32))
    p.drawLine(QPointF(s * 0.50, s * 0.46), QPointF(s * 0.50, s * 0.70))


def _draw_panel(p: QPainter, s: int) -> None:
    p.setPen(QPen(QColor(PALETTE.node_border), 1))
    p.setBrush(QColor(PALETTE.surface))
    p.drawRect(QRectF(s * 0.12, s * 0.18, s * 0.76, s * 0.64))
    p.setBrush(QColor(PALETTE.panel_header))
    p.drawRect(QRectF(s * 0.12, s * 0.18, s * 0.76, s * 0.16))
    p.setBrush(QColor(PALETTE.accent_light))
    p.setPen(QPen(QColor(PALETTE.accent), 1))
    p.drawRoundedRect(QRectF(s * 0.20, s * 0.44, s * 0.26, s * 0.16), 2, 2)
    p.drawEllipse(QRectF(s * 0.58, s * 0.44, s * 0.20, s * 0.20))


_DRAWERS = {
    "start": _draw_start,
    "stop": _draw_stop,
    "pause": _draw_pause,
    "step": _draw_step,
    "new": _draw_new,
    "open": _draw_open,
    "save": _draw_save,
    "capl": _draw_capl,
    "trace": _draw_trace,
    "write": _draw_write,
    "graphics": _draw_graphics,
    "statistics": _draw_statistics,
    "bus": _draw_bus,
    "node": _draw_node,
    "diagnostics": _draw_diagnostics,
    "test": _draw_test,
    "measurement": _draw_measurement,
    "filter": _draw_filter,
    "clear": _draw_clear,
    "search": _draw_search,
    "compile": _draw_compile,
    "error": _draw_error,
    "warning": _draw_warning,
    "info": _draw_info,
    "panel": _draw_panel,
    # cây outline CAPL
    "sym_function": _badge("F", "#0b64b8"),
    "sym_variable": _badge("V", "#1e9e4a"),
    "sym_handler": _badge("E", "#7b2fa0"),
    "sym_testcase": _badge("T", "#d18b00"),
    "sym_struct": _badge("S", "#8a5a00"),
    "sym_enum": _badge("K", "#0b7a75"),
    "sym_include": _badge("#", "#6a707a"),
    "sym_block": _badge("B", "#6a707a"),
    "sym_constant": _badge("C", "#7b2fa0"),
    # chấm trạng thái
    "dot_running": _dot(PALETTE.running),
    "dot_stopped": _dot(PALETTE.stopped),
    "dot_paused": _dot(PALETTE.paused),
    "dot_accent": _dot(PALETTE.accent),
}


def icon(name: str, size: int = 20) -> QIcon:
    """Trả về QIcon theo tên; tên lạ cho ra icon rỗng thay vì lỗi."""
    key = (name, size)
    if key in _CACHE:
        return _CACHE[key]
    drawer = _DRAWERS.get(name)
    pm = _pixmap(size)
    if drawer is not None:
        p = _painter(pm)
        try:
            drawer(p, size)
        finally:
            p.end()
    result = QIcon(pm)
    _CACHE[key] = result
    return result


def available() -> list[str]:
    return sorted(_DRAWERS)
