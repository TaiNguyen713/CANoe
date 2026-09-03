"""Test ISO-TP (mục 1 trong bảng test §11 của SPEC_SIMLANG_V2.md): payload
1..4095 byte, PCI đúng, seq quay vòng 0x2F→0x20, độ dài FF đúng công thức."""

from __future__ import annotations

import asyncio

import pytest

from simlang.runtime.isotp import (
    FlowControlTimeout,
    Frame,
    FrameBuilder,
    PendingFcRegistry,
    Reassembler,
    ff_length,
    reply_can_id,
    send,
)
from simlang.runtime.transport import FakeTransport

CAN_ID = 0x7E8


def _roundtrip(payload: bytes) -> bytes:
    """Build khung đi (FrameBuilder) rồi ghép lại (Reassembler) — nhận đúng
    payload gốc thì coi là round-trip thành công."""
    builder = FrameBuilder(CAN_ID, payload)
    reassembler = Reassembler()

    result = reassembler.feed(builder.first())
    if len(payload) <= 7:
        assert result.message == payload
        assert result.control_frame is None
        return result.message

    assert result.message is None
    assert result.control_frame is not None
    assert result.control_frame.data[:3] == bytes([0x30, 0x00, 0x00])

    message = None
    for frame in builder.remaining():
        r = reassembler.feed(frame)
        if r.message is not None:
            message = r.message
    return message


@pytest.mark.parametrize("length", [0, 1, 6, 7])
def test_single_frame_roundtrip(length):
    payload = bytes(range(length))
    assert _roundtrip(payload) == payload


@pytest.mark.parametrize("length", [8, 9, 50, 300, 4095])
def test_multi_frame_roundtrip(length):
    payload = bytes(i % 256 for i in range(length))
    assert _roundtrip(payload) == payload


def test_single_frame_pci_byte():
    frame = FrameBuilder(CAN_ID, bytes([0xAA, 0xBB])).first()
    assert frame.data[0] == 0x02  # SF, độ dài 2
    assert frame.data[1:3] == bytes([0xAA, 0xBB])
    assert len(frame.data) == 8  # luôn pad đủ 8 byte
    assert frame.data[3:] == b"\x00" * 5


def test_first_frame_pci_and_length():
    payload = bytes(range(20))
    frame = FrameBuilder(CAN_ID, payload).first()
    assert (frame.data[0] >> 4) == 0x1  # FF
    assert ff_length(frame.data[0], frame.data[1]) == 20
    assert frame.data[2:8] == payload[:6]


def test_ff_length_uses_correct_formula_not_vendor_bug():
    # b0=0x11 (FF, high nibble length=0x1), b1=0x50 -> length = (1<<8)|0x50 = 0x150 = 336
    assert ff_length(0x11, 0x50) == 336
    # Công thức bug của engine gốc ((b0 & 0xF00) + b1) luôn = b1 vì b0 chỉ 1 byte.
    buggy = (0x11 & 0xF00) + 0x50
    assert buggy == 0x50  # 80, khác hẳn 336 — chứng minh 2 công thức lệch nhau thật sự
    assert ff_length(0x11, 0x50) != buggy


def test_consecutive_frame_sequence_wraps_at_0x2f_to_0x20():
    # payload đủ dài để cần 17 CF: 6 byte đã nằm trong FF, mỗi CF mang 7 byte
    # -> 16 CF đầu dùng hết nibble 1..15 rồi 0 (quay vòng), CF thứ 17 phải
    # tiếp tục bình thường với nibble 1 trở lại.
    payload = bytes(i % 256 for i in range(6 + 17 * 7))
    frames = FrameBuilder(CAN_ID, payload).remaining()
    seq_nibbles = [f.data[0] & 0x0F for f in frames]
    assert seq_nibbles[:15] == list(range(1, 16))  # 0x21..0x2F
    assert seq_nibbles[15] == 0  # 0x20 — quay vòng đúng như spec mô tả
    assert seq_nibbles[16] == 1  # tiếp tục bình thường sau khi quay vòng
    for f in frames:
        assert (f.data[0] >> 4) == 0x2  # mọi khung đều là CF


def test_consecutive_frame_always_padded_to_8_and_dlc_implicit():
    payload = bytes(range(10))
    frames = FrameBuilder(CAN_ID, payload).remaining()
    assert len(frames) == 1
    assert len(frames[0].data) == 8


def test_reassembler_auto_generates_flow_control_frame_on_reply_id():
    payload = bytes(range(15))
    builder = FrameBuilder(0x7E0, payload)  # request đi TỚI ECU trên 0x7E0
    reassembler = Reassembler()
    result = reassembler.feed(builder.first())
    assert result.control_frame is not None
    assert result.control_frame.can_id == reply_can_id(0x7E0) == 0x7E8
    assert result.control_frame.data == bytes([0x30, 0x00, 0x00, 0, 0, 0, 0, 0])


def test_reply_can_id_physical_address_adds_8():
    assert reply_can_id(0x7E0) == 0x7E8
    assert reply_can_id(0x7E1) == 0x7E9


def test_reply_can_id_functional_broadcast_is_not_plus_8():
    """0x7DF (functional broadcast) + 8 = 0x7E7 SAI — xác nhận bằng dữ liệu
    thật trong DTC_info.sim: mọi request 0x7DF đều nhận response 0x7E8,
    không phải 0x7E7 (bug đã bắt được lúc build lúc test end-to-end)."""
    assert reply_can_id(0x7DF) == 0x7E8
    assert reply_can_id(0x7DF) != 0x7DF + 8


def test_reassembler_ignores_orphan_consecutive_frame():
    reassembler = Reassembler()
    orphan_cf = Frame(CAN_ID, bytes([0x21, 1, 2, 3, 4, 5, 6, 7]))
    result = reassembler.feed(orphan_cf)
    assert result.message is None
    assert result.control_frame is None


def test_reassembler_tracks_independent_can_ids_concurrently():
    payload_a = bytes(range(20))
    payload_b = bytes(range(30, 30 + 20))
    fb_a = FrameBuilder(0x100, payload_a)
    fb_b = FrameBuilder(0x200, payload_b)
    reassembler = Reassembler()

    reassembler.feed(fb_a.first())
    reassembler.feed(fb_b.first())

    result_a = None
    for frame in fb_a.remaining():
        r = reassembler.feed(frame)
        if r.message is not None:
            result_a = r.message
    result_b = None
    for frame in fb_b.remaining():
        r = reassembler.feed(frame)
        if r.message is not None:
            result_b = r.message

    assert result_a == payload_a
    assert result_b == payload_b


# ---------------------------------------------------------------------------
# Điều phối async (send() + PendingFcRegistry) — dùng FakeTransport
# ---------------------------------------------------------------------------


async def test_send_single_frame_no_fc_needed():
    transport = FakeTransport()
    registry = PendingFcRegistry()
    await send(transport, CAN_ID, bytes([1, 2, 3]), registry)
    assert len(transport.sent) == 1
    assert transport.sent[0].data[0] == 0x03


async def test_send_multi_frame_waits_for_flow_control_then_sends_cf():
    transport = FakeTransport()
    registry = PendingFcRegistry()
    payload = bytes(range(20))

    async def responder():
        # đợi FF được gửi rồi mới bắn Flow Control — mô phỏng scan tool thật
        while not transport.sent:
            await asyncio.sleep(0)
        fc = Frame(CAN_ID, bytes([0x30, 0x00, 0x00]))
        assert registry.resolve_if_pending(fc)

    task = asyncio.create_task(responder())
    await send(transport, CAN_ID, payload, registry)
    await task

    assert (transport.sent[0].data[0] >> 4) == 0x1  # FF
    assert all((f.data[0] >> 4) == 0x2 for f in transport.sent[1:])  # còn lại toàn CF


async def test_send_raises_flow_control_timeout_when_nothing_responds():
    transport = FakeTransport()
    registry = PendingFcRegistry()
    with pytest.raises(FlowControlTimeout):
        await send(transport, CAN_ID, bytes(range(20)), registry, fc_timeout_s=0.05)
