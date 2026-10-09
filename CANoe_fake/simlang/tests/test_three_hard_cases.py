"""Ba ca khó mà file `.sim` tĩnh KHÔNG diễn đạt được (SPEC_SIMLANG_V2.md §1),
lý do simlang tồn tại: chạy trên FakeTransport, kiểm chuỗi khung gửi ra và
thời điểm — đúng mục 4 trong bảng test §11.

Dùng bản THU NHỎ THỜI GIAN của ví dụ §5.1 (delay 20ms thay vì 2000ms) để bộ
test chạy nhanh — file `examples/example_5_1.can` giữ nguyên giá trị gốc của
spec cho mục đích tài liệu (xem plan §10 mục 16)."""

from __future__ import annotations

import asyncio

from conftest import build_harness, dispatch_message

EXAMPLE_5_1_FAST = """
variables {
    int  dtcCleared = 0;
    int  rpm = 800;
    msTimer rpmTimer;
}

on start {
    setTimer(rpmTimer, 20);
}

// responsePending
on request 0x7E0 service 0x31 {
    output(0x7F, 0x31, 0x78);
    delay(20);
    output(0x7F, 0x31, 0x78);
    delay(20);
    output(0x71, 0x01, 0x02, 0x03);
}

// trạng thái sau erase
on request 0x7DF service 0x04 {
    dtcCleared = 1;
    output(0x44);
}

on request 0x7DF service 0x03 {
    if (dtcCleared)
        output(0x43, 0x00);
    else
        output(0x43, 0x02, 0x01, 0x33, 0x01, 0x71);
}

// live data theo thời gian
on timer rpmTimer {
    rpm = 800 + 1100 * sin(elapsed() / 3.0);
    setTimer(rpmTimer, 20);
}

on request 0x7DF service 0x01 pid 0x0C {
    output(0x41, 0x0C, (rpm * 4) >> 8, (rpm * 4) & 0xFF);
}
"""


async def test_response_pending_78_sends_three_outputs_with_delay_between():
    """ECU tự gửi thêm (7F 31 78) hai lần trong lúc "xử lý" rồi mới trả lời
    thật — `.sim` tĩnh không diễn đạt được vì nó chỉ ánh xạ 1 request → 1
    response (xem SPEC_SIMLANG_V2.md §1 bảng 'Vì sao không đi đường .sim')."""
    h = build_harness(EXAMPLE_5_1_FAST)

    t0 = asyncio.get_event_loop().time()
    ok = await dispatch_message(h, 0x7E0, bytes([0x31]))
    elapsed = asyncio.get_event_loop().time() - t0

    assert ok is True
    assert len(h.transport.sent) == 3
    assert h.transport.sent[0].data[:4] == bytes([0x03, 0x7F, 0x31, 0x78])
    assert h.transport.sent[1].data[:4] == bytes([0x03, 0x7F, 0x31, 0x78])
    assert h.transport.sent[2].data[:5] == bytes([0x04, 0x71, 0x01, 0x02, 0x03])
    # phải THẬT SỰ chờ ~2*20ms (không phải delay() bị bỏ qua/chặn sai)
    assert elapsed >= 0.035


async def test_dtc_cleared_state_survives_dozens_of_intervening_requests():
    """`Q--` của .sim chỉ nhìn lại MỘT bước (SPEC_SIMLANG_V2.md §4.8 của bản
    v1, giữ nguyên lý do trong §1 của v2) — không sống sót qua hàng chục
    request TesterPresent xen giữa. State trong biến Python thì có."""
    h = build_harness(EXAMPLE_5_1_FAST)

    # đọc DTC TRƯỚC khi erase — phải thấy DTC "còn"
    # (output 6 byte: 43 02 01 33 01 71 -> PCI SF = 0x06, không phải 0x05)
    await dispatch_message(h, 0x7DF, bytes([0x03]))
    assert h.transport.sent[-1].data[:6] == bytes([0x06, 0x43, 0x02, 0x01, 0x33, 0x01])

    await dispatch_message(h, 0x7DF, bytes([0x04]))  # erase

    # mô phỏng hàng chục request không liên quan xen giữa (TesterPresent...)
    # — .sim với Q-- sẽ ĐỨT ở đây, Python thì không vì trạng thái nằm ở biến.
    for _ in range(30):
        await dispatch_message(h, 0x7DF, bytes([0x3E]))  # không handler nào khớp -> no-op

    await dispatch_message(h, 0x7DF, bytes([0x03]))  # đọc lại — phải thấy "đã xoá"
    assert h.transport.sent[-1].data[:2] == bytes([0x02, 0x43])
    assert h.transport.sent[-1].data[2] == 0x00


async def test_live_rpm_value_changes_over_wall_clock_time():
    """`l1` của .sim xoay theo SỐ LẦN GỌI, không theo đồng hồ — không tương
    quan được giữa các PID khác nhau đọc live data cùng lúc. simlang tính
    rpm trực tiếp từ `elapsed()` nên luôn nhất quán theo thời gian thật."""
    h = build_harness(EXAMPLE_5_1_FAST)
    await h.module.on_start(h.ctx)  # khởi động timer 20ms tự tái lập lịch

    await dispatch_message(h, 0x7DF, bytes([0x01, 0x0C]))
    first_rpm_word = h.transport.sent[-1].data[2:4]

    await asyncio.sleep(0.09)  # đủ cho vài lần tick 20ms trôi qua

    await dispatch_message(h, 0x7DF, bytes([0x01, 0x0C]))
    second_rpm_word = h.transport.sent[-1].data[2:4]

    assert h.module.rpm != 800  # đã bị on_timer cập nhật theo elapsed()
    assert first_rpm_word != second_rpm_word or h.module.rpm != 800
