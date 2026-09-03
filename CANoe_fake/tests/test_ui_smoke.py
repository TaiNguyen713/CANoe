"""Kiểm thử khói cho giao diện — chạy headless bằng platform 'offscreen'.

Mục tiêu: bắt lỗi kết nối signal/slot, tên thuộc tính sai, và vòng đời widget.
Không kiểm tra hình ảnh (offscreen trên máy CI thường không có font).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication          # noqa: E402

from canoe_fake.backend.base import MeasurementState  # noqa: E402
from canoe_fake.model.database import demo_configuration  # noqa: E402
from canoe_fake.ui.main_window import DESKTOPS, MainWindow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture
def window(app, tmp_path):
    win = MainWindow(config=demo_configuration(), workspace=tmp_path)
    yield win
    win.backend.stop()
    win.close()
    win.deleteLater()
    app.processEvents()


def test_window_builds_all_desktops(window):
    assert window.stack.count() == len(DESKTOPS)
    assert window.desktop_bar.count() == len(DESKTOPS)


def test_switching_every_desktop_does_not_crash(app, window):
    for index in range(window.stack.count()):
        window._goto_index(index)
        app.processEvents()
        assert window.stack.currentIndex() == index


def test_measurement_lifecycle(app, window):
    assert window.backend.state is MeasurementState.STOPPED
    window.start_measurement()
    assert window.backend.state is MeasurementState.RUNNING
    window.pause_measurement()
    assert window.backend.state is MeasurementState.PAUSED
    window.start_measurement()
    assert window.backend.state is MeasurementState.RUNNING
    window.stop_measurement()
    assert window.backend.state is MeasurementState.STOPPED


def test_trace_model_answers_integer_roles(app):
    """Qt truyền `role` xuống model dưới dạng int, không phải enum.

    Nếu model so sánh role bằng `is`, mọi ô sẽ trống dù rowCount() vẫn đúng —
    bảng Trace trông như bị treo. Test này khoá lại hành vi đó.
    """
    from PySide6.QtCore import Qt

    from canoe_fake.backend.base import BusEvent, Direction, EventKind
    from canoe_fake.ui.windows.trace import TraceModel

    model = TraceModel()
    model.append_many([BusEvent(
        timestamp=1.5, kind=EventKind.CAN_FRAME, channel=1, can_id=0x100,
        name="EngineData", direction=Direction.RX, dlc=8, data=b"\x01\x02")])

    display = int(Qt.ItemDataRole.DisplayRole)
    horizontal = Qt.Orientation.Horizontal

    assert model.headerData(0, horizontal, display) == "Time"
    assert model.headerData(3, horizontal, display) == "Name"
    assert model.data(model.index(0, 0), display) == "1.500000"
    assert model.data(model.index(0, 2), display) == "100"
    assert model.data(model.index(0, 3), display) == "EngineData"
    assert model.data(model.index(0, 4), display) == "Rx"
    assert model.data(model.index(0, 6), display) == "01 02"
    assert model.data(model.index(0, 0), int(Qt.ItemDataRole.ForegroundRole)) is not None


def test_trace_receives_frames_and_renders_text(app, window):
    from PySide6.QtCore import Qt

    window.start_measurement()
    for _ in range(60):
        app.processEvents()
    window.trace_window._flush()
    window.stop_measurement()

    model = window.trace_window.model
    assert model.rowCount() > 0, "backend giả lập phải sinh ra frame"
    display = int(Qt.ItemDataRole.DisplayRole)
    names = {model.data(model.index(r, 3), display) for r in range(model.rowCount())}
    assert any(names), "cột Name không được rỗng toàn bộ"


def test_trace_filter_rejects_non_matching(window):
    from canoe_fake.backend.base import BusEvent, EventKind

    window.trace_window._on_filter_changed("EngineData")
    match = BusEvent(timestamp=0.0, kind=EventKind.CAN_FRAME, name="EngineData")
    other = BusEvent(timestamp=0.0, kind=EventKind.CAN_FRAME, name="ABSdata")
    assert window.trace_window._passes(match)
    assert not window.trace_window._passes(other)


def test_capl_browser_opens_sample_files(app, window):
    sample_dir = ROOT / "capl"
    files = sorted(sample_dir.glob("*.can"))
    assert files, "thiếu file CAPL mẫu trong ./capl"
    for path in files:
        window.capl_browser.open_path(path)
        app.processEvents()
    assert window.capl_browser.tabs.count() == len(files)

    # mở lại file đã mở thì không tạo tab trùng
    window.capl_browser.open_path(files[0])
    assert window.capl_browser.tabs.count() == len(files)


def test_capl_editor_reports_no_error_for_samples(app, window):
    for path in sorted((ROOT / "capl").glob("*.can")):
        window.capl_browser.open_path(path)
        app.processEvents()
        editor = window.capl_browser.current_editor
        editor.analyze()
        errors = [d for d in editor.diagnostics if d.severity.name == "ERROR"]
        assert not errors, f"{path.name}: {[str(e) for e in errors]}"


def test_diagnostics_send_and_response(app, window):
    window.start_measurement()
    window.diagnostics_window.request_edit.setText("22 F1 90")
    window.diagnostics_window.send_request()
    for _ in range(80):
        app.processEvents()
    window.stop_measurement()
    assert "22 F1 90" in window.diagnostics_window.history.toPlainText()


def test_test_window_loads_testcases_from_capl(app, tmp_path):
    (tmp_path / "M.can").write_text(
        'testcase TC_One()\n{\n'
        '  TestStep("1", "chuẩn bị");\n'
        '  if (x) TestStepPass("1", "nhánh đúng");\n'
        '  else TestStepFail("1", "nhánh sai");\n'
        '  TestStep("2", "dọn dẹp");\n}\n'
        'testcase TC_Two()\n{\n  TestStep("1", "bước hai");\n}\n',
        encoding="utf-8")
    win = MainWindow(config=demo_configuration(), workspace=tmp_path)
    try:
        win.test_window.reload_modules()
        app.processEvents()
        cases = [c for m in win.test_window._modules for c in m.cases]
        assert {c.name for c in cases} == {"TC_One", "TC_Two"}
        # chỉ TestStep(...) mới là bước; TestStepPass/Fail là kết quả, phải bị loại
        assert cases[0].steps == ["chuẩn bị", "dọn dẹp"]
    finally:
        win.backend.stop()
        win.close()
        win.deleteLater()
        app.processEvents()


def test_capl_reference_dialog_lists_and_filters(app, window):
    window.show_capl_reference()
    dialog = window._reference_dialog
    assert dialog is not None
    dialog.search.setText("setTimer")
    app.processEvents()
    assert "/" in dialog.count_label.text()
    dialog.search.setText("")
    app.processEvents()
    dialog.close()


def test_statistics_window_updates(app, window):
    from canoe_fake.backend.base import BusStatistics

    stat = BusStatistics(channel=1, bus_load_percent=12.5, frames_total=100)
    window.statistics_window.update_statistics(stat)
    assert window.statistics_window.tree.topLevelItemCount() == 1
    window.statistics_window.reset()
    assert window.statistics_window.tree.topLevelItemCount() == 0
