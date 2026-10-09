"""CLI `simlang` (§9 của SPEC_SIMLANG_V2.md).

`fmt` chưa implement (cần một unparser AST→`.can` riêng, không có tiêu chí
test nào trong spec §11 cho nó) — xem plan §10 mục 18. `run --fake` là bổ
sung KHÔNG có trong spec, thêm để smoke-test lệnh `run` thật mà không cần
phần cứng (xem plan §10 mục 17).
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import typer

from . import importer as importer_mod
from .codegen import CodegenError, generate
from .parser import SimlangSyntaxError, parse_file
from .runtime.builtins import Context
from .runtime.dispatch import DispatchTable, Message
from .runtime.isotp import PendingFcRegistry, Reassembler
from .runtime.timers import TimerManager
from .runtime.transport import FakeTransport

app = typer.Typer(add_completion=False, help="simlang — DSL kiểu CAPL cho OBD Simulator")


def _report_error(path: Path, message: str, line: int, column: int) -> None:
    typer.echo(f"{path}:{line}:{column}: error: {message}", err=True)


@app.command()
def check(can_path: Path) -> None:
    """Parse + validate, không sinh code."""
    try:
        parse_file(can_path)
    except SimlangSyntaxError as exc:
        _report_error(can_path, exc.message, exc.line, exc.column)
        raise typer.Exit(code=1)
    typer.echo(f"{can_path}: OK")


@app.command()
def build(
    can_path: Path,
    output: Path = typer.Option(None, "-o", "--output", help="Ghi ra file thay vì in ra stdout"),
) -> None:
    """Sinh mã Python (để debug), không chạy."""
    try:
        can_file = parse_file(can_path)
        generated = generate(can_file)
    except SimlangSyntaxError as exc:
        _report_error(can_path, exc.message, exc.line, exc.column)
        raise typer.Exit(code=1)
    except CodegenError as exc:
        typer.echo(f"{can_path}: error: {exc}", err=True)
        raise typer.Exit(code=1)
    if output:
        output.write_text(generated.source, encoding="utf-8")
        typer.echo(f"đã ghi {output}")
    else:
        typer.echo(generated.source)


@app.command(name="import")
def import_cmd(
    sim_path: Path,
    output: Path = typer.Option(None, "-o", "--output", help="Ghi ra file .can thay vì in ra stdout"),
) -> None:
    """`.sim` → `.can` — MỘT CHIỀU, không phải roundtrip (xem importer.py)."""
    result = importer_mod.import_sim_to_can(sim_path)
    if output:
        output.write_text(result.can_source, encoding="utf-8")
        typer.echo(f"đã ghi {output}")
    else:
        typer.echo(result.can_source)
    if result.todo_count:
        typer.echo(f"TODO cần xem lại tay: {result.todo_count}", err=True)


def _build_module(can_path: Path) -> types.ModuleType:
    can_file = parse_file(can_path)
    generated = generate(can_file)
    module = types.ModuleType(can_path.stem)
    exec(compile(generated.source, str(can_path), "exec"), module.__dict__)
    return module


async def _run_loop(module: types.ModuleType, transport, base_dir: Path) -> None:
    dispatch_table = DispatchTable()
    timer_manager = TimerManager()
    fc_registry = PendingFcRegistry()
    reassembler = Reassembler()
    ctx = Context(transport, dispatch_table, timer_manager, fc_registry, base_dir=base_dir)
    if hasattr(module, "register"):
        module.register(dispatch_table, timer_manager)

    transport.start()
    ctx.mark_started()
    if hasattr(module, "on_start"):
        await module.on_start(ctx)

    try:
        while True:
            frame = await transport.read()
            if fc_registry.resolve_if_pending(frame):
                continue
            for raw_fn in dispatch_table.find_raw(frame.can_id):
                asyncio.create_task(raw_fn(ctx, frame.data))
            result = reassembler.feed(frame)
            if result.control_frame is not None:
                await transport.write(result.control_frame)
            if result.message is not None:
                msg = Message(can_id=frame.can_id, data=result.message)
                handler = dispatch_table.find(msg)
                if handler is not None:
                    async def _invoke(h=handler, m=msg):
                        ctx.current_request = m
                        await h.fn(ctx, m)
                    asyncio.create_task(_invoke())
                else:
                    response = ctx.static_table.respond(msg)
                    if response is not None:
                        ctx.current_request = msg
                        asyncio.create_task(ctx.output(*response))
    except asyncio.CancelledError:
        pass
    finally:
        if hasattr(module, "on_stop"):
            await module.on_stop(ctx)
        transport.stop()


@app.command()
def run(
    can_path: Path,
    port: str = typer.Option(None, "--port", help="Cổng COM board thật (vd COM3)"),
    fake: bool = typer.Option(False, "--fake", help="Chạy với FakeTransport để smoke-test, không cần board"),
) -> None:
    """Transpile + chạy. `--port` cần board thật (RealTransport, chưa xác
    minh — chờ M0). `--fake` chạy on_start rồi thoát, không cần phần cứng."""
    try:
        module = _build_module(can_path)
    except SimlangSyntaxError as exc:
        _report_error(can_path, exc.message, exc.line, exc.column)
        raise typer.Exit(code=1)
    except CodegenError as exc:
        typer.echo(f"{can_path}: error: {exc}", err=True)
        raise typer.Exit(code=1)

    if fake:
        transport = FakeTransport()
        typer.echo("(--fake) chạy on_start(), không có board thật để đọc/ghi khung.")
        asyncio.run(_smoke_run(module, transport, can_path.resolve().parent))
        return

    if not port:
        typer.echo("cần --port <COMx> hoặc --fake", err=True)
        raise typer.Exit(code=1)

    from .runtime.transport import RealTransport  # import trễ — pythonnet có thể chưa cài
    dll_path = Path(__file__).resolve().parents[3] / "engine" / "OBDSimulation_CLI_1.3.36.3" / "x64" / "net9.0" / "SimulatorInterface.dll"
    transport = RealTransport(str(dll_path))
    transport.open(port)
    try:
        asyncio.run(_run_loop(module, transport, can_path.resolve().parent))
    except KeyboardInterrupt:
        pass
    finally:
        transport.close()


async def _smoke_run(module: types.ModuleType, transport: FakeTransport, base_dir: Path) -> None:
    dispatch_table = DispatchTable()
    timer_manager = TimerManager()
    fc_registry = PendingFcRegistry()
    ctx = Context(transport, dispatch_table, timer_manager, fc_registry, base_dir=base_dir)
    if hasattr(module, "register"):
        module.register(dispatch_table, timer_manager)
    ctx.mark_started()
    if hasattr(module, "on_start"):
        await module.on_start(ctx)


@app.command()
def fmt(can_path: Path) -> None:
    """Chưa implement — cần unparser .can riêng, không có tiêu chí test
    trong spec §11 (xem plan §10 mục 18)."""
    typer.echo("simlang fmt: chưa implement", err=True)
    raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
