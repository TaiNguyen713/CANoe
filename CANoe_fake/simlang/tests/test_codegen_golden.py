"""Test "golden" cho codegen (M4, mục 3 trong bảng test §11): mỗi cú pháp
§5 phải sinh ra Python CHẠY ĐÚNG. Kiểm theo HÀNH VI (chạy handler thật qua
FakeTransport, xem `conftest.build_harness`) chứ không so sánh text sinh ra
— bền với thay đổi cách format của codegen (xem plan §10 mục 10)."""

from __future__ import annotations

import asyncio

import pytest

from conftest import build_harness, build_module, dispatch_message


async def test_variables_block_all_types_initial_values():
    h = build_harness(
        "variables { int a = 5; long b = 10; float c = 1.5; double d = 2.5; "
        "char e = 65; byte[] f; char[8] g; msTimer t; }"
        "on start { write(1); }"
    )
    assert h.module.a == 5
    assert h.module.b == 10
    assert h.module.c == 1.5
    assert h.module.d == 2.5
    assert h.module.e == 65
    assert h.module.t.name == "t"


async def test_on_start_and_on_stop_run():
    h = build_harness(
        "variables { int started = 0; int stopped = 0; }"
        "on start { started = 1; }"
        "on stop { stopped = 1; }"
    )
    await h.module.on_start(h.ctx)
    assert h.module.started == 1
    await h.module.on_stop(h.ctx)
    assert h.module.stopped == 1


async def test_on_request_basic_dispatch_and_output():
    h = build_harness("on request 0x7E0 service 0x22 { output(0x62, 0x01); }")
    ok = await dispatch_message(h, 0x7E0, bytes([0x22]))
    assert ok is True
    assert len(h.transport.sent) == 1
    frame = h.transport.sent[0]
    assert frame.can_id == 0x7E8  # 0x7E0 + 8
    assert frame.data[:3] == bytes([0x02, 0x62, 0x01])  # SF độ dài 2


async def test_on_request_pid_beats_service_only():
    h = build_harness(
        "on request 0x7DF service 0x01 { output(0xAA); }"
        "on request 0x7DF service 0x01 pid 0x0C { output(0xBB); }"
    )
    ok = await dispatch_message(h, 0x7DF, bytes([0x01, 0x0C]))
    assert ok
    assert h.transport.sent[0].data[1] == 0xBB  # pid cụ thể thắng service-only


async def test_data_clause_with_wildcard_matches_and_beats_pid():
    h = build_harness(
        "on request 0x7DF service 0x01 pid 0x0C { output(0x11); }"
        "on request 0x7DF service 0x01 data 0x01 0x0C xx { output(0x22); }"
    )
    ok = await dispatch_message(h, 0x7DF, bytes([0x01, 0x0C, 0x99]))
    assert ok
    assert h.transport.sent[0].data[1] == 0x22  # data (specificity 2) thắng pid (specificity 1)


async def test_data_clause_wildcard_matches_any_byte_value():
    # `data` mô tả TOÀN BỘ payload kể cả byte service (xem ghi chú trong
    # grammar/simlang.lark) — 0x22 lặp lại service là cố ý, không phải thừa.
    h = build_harness("on request 0x7DF service 0x22 data 0x22 xx xx { output(0x01); }")
    assert await dispatch_message(h, 0x7DF, bytes([0x22, 0xDE, 0xAD]))
    assert h.transport.sent[0].data[1] == 0x01


async def test_no_handler_matches_returns_false():
    h = build_harness("on request 0x7DF service 0x01 { output(1); }")
    ok = await dispatch_message(h, 0x7DF, bytes([0x99]))
    assert ok is False
    assert h.transport.sent == []


async def test_on_message_raw_handler_registered_separately():
    h = build_harness("on message 0x100 { write(1); }")
    fns = h.dispatch_table.find_raw(0x100)
    assert len(fns) == 1
    assert h.dispatch_table.find_raw(0x200) == []


async def test_if_else_branching():
    h = build_harness(
        "variables { int flag = 0; }"
        "on start { if (flag) write(1); else write(0); }"
    )
    printed = []
    # write(1)/write(0) không có tham số format bổ sung -> Context.write()
    # in thẳng giá trị nguyên gốc (int), không ép sang string.
    h.ctx.write = lambda fmt, *a: printed.append(fmt % a if a else fmt)
    await h.module.on_start(h.ctx)
    assert printed == [0]

    h.module.flag = 1
    printed.clear()
    await h.module.on_start(h.ctx)
    assert printed == [1]


async def test_while_loop():
    h = build_harness(
        "variables { int i = 0; int total = 0; }"
        "on start { while (i < 5) { total = total + i; i = i + 1; } }"
    )
    await h.module.on_start(h.ctx)
    assert h.module.total == 0 + 1 + 2 + 3 + 4
    assert h.module.i == 5


async def test_for_loop():
    # `i` không khai báo trong variables{} — vẫn hợp lệ vì nó chỉ được
    # gán/đọc trong PHẠM VI CỤC BỘ của on_start (không cần `global`, Python
    # tự coi là biến local của hàm). `total` mới cần `global` vì được khai
    # báo ở variables{} và phải thấy được từ ngoài sau khi hàm chạy xong.
    h = build_harness(
        "variables { int total = 0; }"
        "on start { for (i = 0; i < 4; i = i + 1) total = total + i; }"
    )
    await h.module.on_start(h.ctx)
    assert h.module.total == 0 + 1 + 2 + 3


async def test_switch_case_literal_dispatch():
    h = build_harness(
        "variables { int result = 0; }"
        "on start { switch (2) { case 1: result = 10; case 2: result = 20; default: result = 0; } }"
    )
    await h.module.on_start(h.ctx)
    assert h.module.result == 20


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("1 + 2", 3), ("5 - 2", 3), ("3 * 4", 12), ("7 % 3", 1),
        ("1 << 3", 8), ("16 >> 2", 4),
        ("0x0F & 0x03", 3), ("0x01 | 0x02", 3), ("0x0F ^ 0x0A", 5),
        ("1 == 1", True), ("1 != 2", True),
        ("1 < 2", True), ("2 > 1", True), ("2 <= 2", True), ("2 >= 3", False),
        ("1 && 0", False), ("1 || 0", True),
        ("!0", True), ("-5", -5), ("~0", -1),
    ],
)
async def test_every_operator_evaluates_correctly(expr, expected):
    h = build_harness(f"variables {{ int result = 0; }} on start {{ result = {expr}; }}")
    await h.module.on_start(h.ctx)
    assert h.module.result == expected


@pytest.mark.parametrize(
    # int(2.5)=2, int(3.0)=3 -> 2<<3=16, 2>>3=0, 2&3=2, 2|3=3, 2^3=1
    "op, expected",
    [("<<", 16), (">>", 0), ("&", 2), ("|", 3), ("^", 1)],
)
async def test_bitwise_ops_coerce_float_to_int_like_c(op, expected):
    """Bug thật bắt được lúc chạy test_three_hard_cases: rpm = 800 + 1100 *
    sin(...) làm rpm thành float, rồi `(rpm*4) >> 8` crash TypeError trong
    Python (C/CAPL thì tự ép). Test trực tiếp bằng float 2.5/3.0 để không
    phụ thuộc giá trị cụ thể của sin()."""
    h = build_harness(f"variables {{ int result = 0; }} on start {{ result = 2.5 {op} 3.0; }}")
    await h.module.on_start(h.ctx)
    assert h.module.result == expected


async def test_hex_decimal_float_string_literals_roundtrip():
    h = build_module(
        'on start { write("%d %d %f %s", 0x10, 42, 3.5, "hi"); }'
    )
    captured = []
    import builtins as _b

    real_print = _b.print
    _b.print = lambda s: captured.append(s)
    try:
        from simlang.runtime.builtins import Context
        from simlang.runtime.dispatch import DispatchTable
        from simlang.runtime.isotp import PendingFcRegistry
        from simlang.runtime.timers import TimerManager
        from simlang.runtime.transport import FakeTransport

        ctx = Context(FakeTransport(), DispatchTable(), TimerManager(), PendingFcRegistry())
        await h.on_start(ctx)
    finally:
        _b.print = real_print
    assert captured == ["16 42 3.500000 hi"]


async def test_global_state_persists_across_dispatches():
    h = build_harness(
        "variables { int counter = 0; }"
        "on request 0x100 service 0x01 { counter = counter + 1; output(counter); }"
    )
    await dispatch_message(h, 0x100, bytes([0x01]))
    await dispatch_message(h, 0x100, bytes([0x01]))
    await dispatch_message(h, 0x100, bytes([0x01]))
    assert h.module.counter == 3
    assert [f.data[1] for f in h.transport.sent] == [1, 2, 3]


async def test_output_raw_sends_one_unframed_frame():
    h = build_harness("on start { outputRaw(0x123, 1, 2, 3, 4, 5, 6, 7, 8); }")
    await h.module.on_start(h.ctx)
    assert len(h.transport.sent) == 1
    frame = h.transport.sent[0]
    assert frame.can_id == 0x123
    assert frame.data == bytes([1, 2, 3, 4, 5, 6, 7, 8])


async def test_set_timer_and_cancel_timer():
    h = build_harness(
        "variables { msTimer t; int fired = 0; }"
        "on start { setTimer(t, 10); }"
        "on timer t { fired = 1; }"
    )
    await h.module.on_start(h.ctx)
    await asyncio.sleep(0.05)
    assert h.module.fired == 1


async def test_cancel_timer_prevents_fire():
    h = build_harness(
        "variables { msTimer t; int fired = 0; }"
        "on start { setTimer(t, 10); cancelTimer(t); }"
        "on timer t { fired = 1; }"
    )
    await h.module.on_start(h.ctx)
    await asyncio.sleep(0.05)
    assert h.module.fired == 0


async def test_elapsed_increases_over_time():
    h = build_harness("on start { write(1); }")
    e0 = h.ctx.elapsed()
    await asyncio.sleep(0.02)
    e1 = h.ctx.elapsed()
    assert e1 > e0


async def test_load_static_populates_static_table():
    # loadStatic() nhận string literal cố định trong .can thật (spec §5.1:
    # `loadStatic("2008_Audi_A6.sim")`) — ở đây gọi ctx.load_static() trực
    # tiếp với đường dẫn fixture thật, tách biệt khỏi việc codegen phải sinh
    # đúng string literal (đã test riêng ở test_hex_decimal_float_string...).
    h = build_harness("on start { write(1); }")
    from conftest import FIXTURES

    h.ctx.load_static(FIXTURES / "DTC_info.sim")
    assert len(h.ctx.static_table._entries) > 0


async def test_call_unknown_builtin_raises_codegen_error():
    from simlang.codegen import CodegenError
    from simlang.parser import parse
    from simlang.codegen import generate

    can_file = parse("on start { notAFunction(1); }")
    with pytest.raises(CodegenError):
        generate(can_file)


async def test_switch_case_with_non_literal_raises_codegen_error():
    from simlang.codegen import CodegenError
    from simlang.parser import parse
    from simlang.codegen import generate

    can_file = parse("variables { int x = 1; } on start { switch (x) { case x: write(1); } }")
    with pytest.raises(CodegenError):
        generate(can_file)
