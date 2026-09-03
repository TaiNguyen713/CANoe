"""Điểm khởi động CANoe Fake.

    python main.py                 # chạy với cấu hình demo
    python main.py --workspace X   # dùng thư mục CAPL khác
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from canoe_fake import APP_TITLE, __version__
from canoe_fake.model.database import demo_configuration
from canoe_fake.ui.main_window import MainWindow
from canoe_fake.ui.theme import ui_font


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="canoe-fake",
        description=f"{APP_TITLE} {__version__} — mô phỏng giao diện Vector CANoe.")
    parser.add_argument(
        "--workspace", type=Path, default=Path(__file__).resolve().parent / "capl",
        help="thư mục chứa file CAPL (.can/.cin); mặc định: ./capl")
    parser.add_argument("--version", action="version",
                        version=f"{APP_TITLE} {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("CANoe Fake")
    app.setFont(ui_font(9))

    window = MainWindow(config=demo_configuration(), workspace=args.workspace)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
