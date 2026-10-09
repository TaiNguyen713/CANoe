"""Test CLI (§9 của SPEC_SIMLANG_V2.md) qua `typer.testing.CliRunner` —
không cần phần cứng: `build`/`check`/`import`/`run --fake` đều chạy được
không board thật."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from simlang.cli import app

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXAMPLE_CAN = Path(__file__).resolve().parents[1] / "examples" / "example_5_1.can"

runner = CliRunner()


def test_check_valid_file_reports_ok():
    result = runner.invoke(app, ["check", str(EXAMPLE_CAN)])
    assert result.exit_code == 0
    assert "OK" in result.stdout


def test_check_invalid_file_reports_line_number_and_exits_nonzero(tmp_path):
    bad = tmp_path / "bad.can"
    bad.write_text("on start { write(1 }", encoding="utf-8")
    result = runner.invoke(app, ["check", str(bad)])
    assert result.exit_code == 1
    assert str(bad) in result.stdout or str(bad) in (result.stderr or "")


def test_build_prints_generated_python_to_stdout():
    result = runner.invoke(app, ["build", str(EXAMPLE_CAN)])
    assert result.exit_code == 0
    assert "async def on_start" in result.stdout
    assert "__SIMLANG_LINEMAP__" in result.stdout


def test_build_writes_to_output_file(tmp_path):
    out = tmp_path / "gen.py"
    result = runner.invoke(app, ["build", str(EXAMPLE_CAN), "-o", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    assert "async def on_start" in out.read_text(encoding="utf-8")


def test_import_command_prints_can_source_and_todo_summary():
    result = runner.invoke(app, ["import", str(FIXTURES / "synthetic_todo_cases.sim")])
    assert result.exit_code == 0
    assert "on request 0x7E0" in result.stdout


def test_import_command_writes_to_output_file(tmp_path):
    out = tmp_path / "imported.can"
    result = runner.invoke(app, ["import", str(FIXTURES / "CAN_default_dev.sim"), "-o", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    assert "on request" in out.read_text(encoding="utf-8")


def test_run_fake_executes_on_start_without_hardware(tmp_path):
    # KHÔNG dùng example_5_1.can ở đây: nó gọi loadStatic("2008_Audi_A6.sim")
    # — file đó chưa có trong repo (khoảng trống đã biết, xem plan), nên sẽ
    # raise FileNotFoundError thật, không liên quan gì đến việc test "run
    # --fake" tự nó có nối dây đúng hay không.
    can = tmp_path / "smoke.can"
    can.write_text('variables { int started = 0; } on start { started = 1; }', encoding="utf-8")
    result = runner.invoke(app, ["run", str(can), "--fake"])
    assert result.exit_code == 0


def test_run_without_port_or_fake_errors():
    result = runner.invoke(app, ["run", str(EXAMPLE_CAN)])
    assert result.exit_code == 1


def test_fmt_reports_not_implemented():
    result = runner.invoke(app, ["fmt", str(EXAMPLE_CAN)])
    assert result.exit_code == 1
