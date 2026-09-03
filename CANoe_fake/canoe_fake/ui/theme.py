"""Bảng màu và stylesheet mô phỏng giao diện Vector CANoe.

CANoe dùng tông xám sáng kiểu Office với điểm nhấn xanh dương. Toàn bộ màu
được gom vào lớp `Palette` để các widget vẽ tay (Trace, sơ đồ Setup) dùng chung
đúng một bộ màu với stylesheet.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase


@dataclass(frozen=True)
class Palette:
    # nền
    window: str = "#f0f0f0"
    surface: str = "#ffffff"
    surface_alt: str = "#f7f8fa"
    panel_header: str = "#e4e7eb"
    toolbar: str = "#eef0f3"
    ribbon: str = "#dfe3e8"

    # đường viền
    border: str = "#c3c8ce"
    border_light: str = "#dadde1"
    grid: str = "#e6e8eb"

    # chữ
    text: str = "#1f2328"
    text_muted: str = "#6a707a"
    text_disabled: str = "#a3a8b0"
    text_inverse: str = "#ffffff"

    # điểm nhấn
    accent: str = "#0b64b8"          # xanh Vector
    accent_light: str = "#cfe4f7"
    accent_hover: str = "#dbeaf8"
    selection: str = "#cce4f7"

    # trạng thái measurement
    running: str = "#1e9e4a"
    running_dark: str = "#137a37"
    stopped: str = "#b3261e"
    paused: str = "#d18b00"

    # màu dòng Trace
    rx: str = "#1f2328"
    tx: str = "#0b64b8"
    error: str = "#c62828"
    warning: str = "#b26a00"
    info: str = "#0b7a75"
    statistic: str = "#6a707a"

    # sơ đồ Measurement / Simulation Setup
    node_fill: str = "#fdfdfe"
    node_fill_alt: str = "#eaf2fb"
    node_border: str = "#7d8790"
    node_selected: str = "#0b64b8"
    bus_line: str = "#3d4550"
    canvas: str = "#fbfbfc"
    canvas_grid: str = "#eaecef"

    # tô màu cú pháp CAPL
    syn_keyword: str = "#0000c0"
    syn_type: str = "#0b64b8"
    syn_event: str = "#7b2fa0"
    syn_builtin: str = "#8a5a00"
    syn_string: str = "#a31515"
    syn_char: str = "#a31515"
    syn_number: str = "#098658"
    syn_comment: str = "#3f8f3f"
    syn_preproc: str = "#808080"
    syn_operator: str = "#5a5f66"
    syn_sysvar: str = "#b8860b"
    syn_constant: str = "#7b2fa0"

    # phụ trợ editor
    line_number_bg: str = "#f3f4f6"
    line_number_fg: str = "#9aa0a8"
    line_number_active: str = "#1f2328"
    current_line: str = "#f4f7fb"
    error_underline: str = "#c62828"
    warning_underline: str = "#b26a00"
    info_underline: str = "#0b7a75"
    bracket_match: str = "#bfe3bf"

    def q(self, name: str) -> QColor:
        return QColor(getattr(self, name))


PALETTE = Palette()


def ui_font(point_size: int = 9, bold: bool = False) -> QFont:
    """Font giao diện — bám theo Segoe UI của CANoe trên Windows."""
    for family in ("Segoe UI", "Noto Sans", "DejaVu Sans", "Arial"):
        if family in QFontDatabase.families():
            font = QFont(family, point_size)
            font.setBold(bold)
            return font
    font = QFont()
    font.setPointSize(point_size)
    font.setBold(bold)
    return font


def mono_font(point_size: int = 10) -> QFont:
    """Font đơn cách cho Trace, Write window và editor CAPL."""
    for family in ("Cascadia Mono", "Consolas", "JetBrains Mono",
                   "DejaVu Sans Mono", "Courier New"):
        if family in QFontDatabase.families():
            font = QFont(family, point_size)
            font.setFixedPitch(True)
            return font
    font = QFont()
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    font.setPointSize(point_size)
    return font


def stylesheet(p: Palette = PALETTE) -> str:
    return f"""
/* ===================== nền chung ===================== */
QWidget {{
    background: {p.window};
    color: {p.text};
}}
QMainWindow::separator {{
    background: {p.border_light};
    width: 4px;
    height: 4px;
}}
QMainWindow::separator:hover {{ background: {p.accent_light}; }}

/* ===================== menu ===================== */
QMenuBar {{
    background: {p.ribbon};
    border-bottom: 1px solid {p.border};
    padding: 1px 4px;
}}
QMenuBar::item {{ padding: 4px 10px; background: transparent; border-radius: 3px; }}
QMenuBar::item:selected {{ background: {p.accent_hover}; }}
QMenuBar::item:pressed  {{ background: {p.accent_light}; }}

QMenu {{
    background: {p.surface};
    border: 1px solid {p.border};
    padding: 4px;
}}
QMenu::item {{ padding: 5px 28px 5px 26px; border-radius: 3px; }}
QMenu::item:selected {{ background: {p.selection}; }}
QMenu::item:disabled {{ color: {p.text_disabled}; }}
QMenu::separator {{ height: 1px; background: {p.border_light}; margin: 4px 8px; }}

/* ===================== toolbar ===================== */
QToolBar {{
    background: {p.toolbar};
    border: none;
    border-bottom: 1px solid {p.border};
    spacing: 2px;
    padding: 3px 6px;
}}
QToolBar::separator {{
    background: {p.border};
    width: 1px;
    margin: 4px 6px;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 4px 6px;
}}
QToolButton:hover   {{ background: {p.accent_hover}; border-color: {p.accent_light}; }}
QToolButton:pressed {{ background: {p.accent_light}; }}
QToolButton:checked {{ background: {p.accent_light}; border-color: {p.accent}; }}
QToolButton:disabled {{ color: {p.text_disabled}; }}
QToolButton::menu-indicator {{ image: none; }}

/* ===================== dock ===================== */
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
    font-weight: 600;
}}
QDockWidget::title {{
    background: {p.panel_header};
    border: 1px solid {p.border_light};
    border-bottom: 2px solid {p.accent};
    padding: 5px 8px;
    text-align: left;
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: none;
    padding: 0px;
    icon-size: 12px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background: {p.accent_light};
    border-radius: 2px;
}}

/* ===================== tab ===================== */
QTabWidget::pane {{
    border: 1px solid {p.border};
    background: {p.surface};
    top: -1px;
}}
QTabBar::tab {{
    background: {p.panel_header};
    border: 1px solid {p.border};
    border-bottom: none;
    padding: 5px 14px;
    margin-right: 1px;
    color: {p.text_muted};
}}
QTabBar::tab:selected {{
    background: {p.surface};
    color: {p.text};
    border-bottom: 2px solid {p.accent};
}}
QTabBar::tab:hover:!selected {{ background: {p.accent_hover}; }}

/* ===================== bảng / cây ===================== */
QTreeView, QTableView, QTableWidget, QTreeWidget, QListWidget, QListView {{
    background: {p.surface};
    alternate-background-color: {p.surface_alt};
    border: 1px solid {p.border};
    gridline-color: {p.grid};
    selection-background-color: {p.selection};
    selection-color: {p.text};
    outline: none;
}}
QTreeView::item, QTableView::item, QListWidget::item {{ padding: 2px 4px; }}
QTreeView::item:selected, QTableView::item:selected, QListWidget::item:selected {{
    background: {p.selection};
    color: {p.text};
}}
QTreeView::item:hover, QTableView::item:hover {{ background: {p.accent_hover}; }}
QTreeView::branch {{ background: transparent; }}

QHeaderView::section {{
    background: {p.panel_header};
    border: none;
    border-right: 1px solid {p.border_light};
    border-bottom: 1px solid {p.border};
    padding: 4px 6px;
    font-weight: 600;
    color: {p.text_muted};
}}
QHeaderView::section:hover {{ background: {p.accent_hover}; }}
QTableCornerButton::section {{ background: {p.panel_header}; border: none; }}

/* ===================== nhập liệu ===================== */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 2px;
    padding: 3px 6px;
    selection-background-color: {p.selection};
    selection-color: {p.text};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {p.accent};
}}
QLineEdit:disabled, QComboBox:disabled {{
    background: {p.surface_alt};
    color: {p.text_disabled};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {p.text_muted};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    selection-background-color: {p.selection};
}}

/* ===================== nút ===================== */
QPushButton {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 3px;
    padding: 5px 14px;
    min-width: 70px;
}}
QPushButton:hover   {{ background: {p.accent_hover}; border-color: {p.accent}; }}
QPushButton:pressed {{ background: {p.accent_light}; }}
QPushButton:disabled {{ color: {p.text_disabled}; background: {p.surface_alt}; }}
QPushButton:default {{ border: 1px solid {p.accent}; }}

QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 13px; height: 13px; }}
QCheckBox::indicator:unchecked {{
    border: 1px solid {p.border}; background: {p.surface}; border-radius: 2px;
}}
QCheckBox::indicator:checked {{
    border: 1px solid {p.accent}; background: {p.accent}; border-radius: 2px;
}}

/* ===================== thanh cuộn ===================== */
QScrollBar:vertical {{
    background: {p.surface_alt}; width: 13px; margin: 0; border: none;
}}
QScrollBar::handle:vertical {{
    background: #c1c6cc; min-height: 24px; border-radius: 6px; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: #a8aeb5; }}
QScrollBar:horizontal {{
    background: {p.surface_alt}; height: 13px; margin: 0; border: none;
}}
QScrollBar::handle:horizontal {{
    background: #c1c6cc; min-width: 24px; border-radius: 6px; margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: #a8aeb5; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ===================== status bar ===================== */
QStatusBar {{
    background: {p.ribbon};
    border-top: 1px solid {p.border};
    color: {p.text_muted};
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ padding: 2px 8px; }}

/* ===================== khác ===================== */
QGroupBox {{
    border: 1px solid {p.border_light};
    border-radius: 3px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {p.text_muted};
}}
QSplitter::handle {{ background: {p.border_light}; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical   {{ height: 4px; }}
QSplitter::handle:hover {{ background: {p.accent_light}; }}
QToolTip {{
    background: #fffce8;
    color: {p.text};
    border: 1px solid {p.border};
    padding: 4px 6px;
}}
QProgressBar {{
    border: 1px solid {p.border};
    border-radius: 2px;
    background: {p.surface};
    text-align: center;
    height: 14px;
}}
QProgressBar::chunk {{ background: {p.accent}; }}
"""
