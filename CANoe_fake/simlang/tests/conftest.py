"""Cấu hình chung cho pytest: đảm bảo import được gói simlang từ simlang/src,
và cung cấp helper dựng "harness" runtime (dispatch/timer/transport/ctx) dùng
chung cho test_codegen_golden.py và test_three_hard_cases.py."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = Path(__file__).resolve().parent / "fixtures"

from simlang.codegen import generate  # noqa: E402
from simlang.parser import parse  # noqa: E402
from simlang.runtime.builtins import Context  # noqa: E402
from simlang.runtime.dispatch import DispatchTable  # noqa: E402
from simlang.runtime.isotp import PendingFcRegistry  # noqa: E402
from simlang.runtime.timers import TimerManager  # noqa: E402
from simlang.runtime.transport import FakeTransport  # noqa: E402


def build_module(source: str, module_name: str = "generated_test_module") -> types.ModuleType:
    """Parse + codegen + exec một đoạn `.can` thành module Python thật —
    dùng để test HÀNH VI (chạy handler thật) thay vì so sánh text sinh ra,
    nên bền với thay đổi cách format của codegen (xem plan §10 mục 10)."""
    can_file = parse(source)
    generated = generate(can_file)
    module = types.ModuleType(module_name)
    exec(compile(generated.source, f"<{module_name}>", "exec"), module.__dict__)
    module.__simlang_line_map__ = generated.line_map
    return module


@dataclass
class Harness:
    module: types.ModuleType
    transport: FakeTransport
    dispatch_table: DispatchTable
    timer_manager: TimerManager
    fc_registry: PendingFcRegistry
    ctx: Context


def build_harness(source: str, module_name: str = "generated_test_module") -> Harness:
    """Dựng đủ bộ runtime (transport giả + dispatch + timer + Context) rồi
    gọi `module.register(...)` — sẵn sàng dispatch message/timer ngay."""
    module = build_module(source, module_name)
    transport = FakeTransport()
    dispatch_table = DispatchTable()
    timer_manager = TimerManager()
    fc_registry = PendingFcRegistry()
    ctx = Context(transport, dispatch_table, timer_manager, fc_registry)
    ctx.mark_started()
    if hasattr(module, "register"):
        module.register(dispatch_table, timer_manager)
    return Harness(module, transport, dispatch_table, timer_manager, fc_registry, ctx)


async def dispatch_message(harness: Harness, can_id: int, data: bytes) -> bool:
    """Giả lập một request đã ghép ISO-TP xong tới `can_id`/`data` — tìm
    handler khớp rồi gọi trực tiếp (bỏ qua vòng lặp đọc thật, xem plan
    §8: test hard-case chỉ cần chạy handler thật trên FakeTransport, không
    cần toàn bộ read-loop). Trả về True nếu có handler khớp và đã chạy."""
    from simlang.runtime.dispatch import Message

    msg = Message(can_id=can_id, data=data)
    handler = harness.dispatch_table.find(msg)
    if handler is None:
        return False
    harness.ctx.current_request = msg
    await handler.fn(harness.ctx, msg)
    return True
