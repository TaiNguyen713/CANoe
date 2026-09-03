"""Kiểm thử mã hoá/giải mã signal và cấu hình demo."""

from __future__ import annotations

import pytest

from canoe_fake.model import codec
from canoe_fake.model.database import (ByteOrder, MessageDef, SignalDef,
                                       demo_configuration)


def test_intel_roundtrip():
    sig = SignalDef("S", start_bit=0, bit_length=16, factor=0.25)
    data = bytearray(8)
    codec.encode_signal(sig, data, 1000.0)
    assert codec.decode_signal(sig, bytes(data)) == pytest.approx(1000.0)


def test_intel_offset_and_factor():
    sig = SignalDef("Temp", start_bit=16, bit_length=8, factor=1.0, offset=-40)
    data = bytearray(8)
    codec.encode_signal(sig, data, 92.0)
    assert data[2] == 132
    assert codec.decode_signal(sig, bytes(data)) == pytest.approx(92.0)


def test_motorola_roundtrip():
    sig = SignalDef("M", start_bit=7, bit_length=12,
                    byte_order=ByteOrder.MOTOROLA, factor=1.0)
    data = bytearray(8)
    codec.encode_signal(sig, data, 1365)
    assert codec.decode_signal(sig, bytes(data)) == pytest.approx(1365)


def test_signed_signal():
    sig = SignalDef("S", start_bit=0, bit_length=8, is_signed=True, factor=1.0)
    data = bytearray(2)
    codec.encode_signal(sig, data, -5)
    assert codec.decode_signal(sig, bytes(data)) == pytest.approx(-5)


def test_value_saturates_instead_of_wrapping():
    sig = SignalDef("S", start_bit=0, bit_length=8, factor=1.0)
    data = bytearray(2)
    codec.encode_signal(sig, data, 9999)
    assert data[0] == 255


def test_non_overlapping_signals_do_not_interfere():
    msg = MessageDef("M", 0x100, 8, signals=(
        SignalDef("A", 0, 12, factor=1.0),
        SignalDef("B", 12, 12, factor=1.0),
        SignalDef("C", 24, 8, factor=1.0),
    ))
    payload = codec.encode_message(msg, {"A": 1234, "B": 567, "C": 89})
    decoded = codec.decode_message(msg, payload)
    assert decoded == pytest.approx({"A": 1234.0, "B": 567.0, "C": 89.0})


def test_decode_short_payload_does_not_crash():
    sig = SignalDef("S", start_bit=48, bit_length=16, factor=1.0)
    assert codec.decode_signal(sig, b"\x01\x02") == 0.0


def test_payload_text_helpers():
    assert codec.format_payload(b"\x01\xa2\xff") == "01 A2 FF"
    assert codec.parse_payload("01 A2 FF") == b"\x01\xa2\xff"
    assert codec.parse_payload("01A2FF") == b"\x01\xa2\xff"
    assert codec.parse_payload("0x22, 0xF1, 0x90") == b"\x22\xf1\x90"
    assert codec.parse_payload("rác") == b""


def test_demo_configuration_is_consistent():
    config = demo_configuration()
    assert len(config.networks) == 2
    assert config.network("CAN 1 — Powertrain") is not None
    assert config.sysvar("Engine::RPM") is not None

    for net in config.networks:
        ids = [m.can_id for m in net.messages]
        assert len(ids) == len(set(ids)), f"trùng CAN ID trong {net.name}"
        for msg in net.messages:
            for sig in msg.signals:
                assert sig.start_bit + sig.bit_length <= msg.dlc * 8, \
                    f"{msg.name}::{sig.name} vượt quá DLC"

    # mỗi message có sender phải trỏ tới một node thật trong cùng mạng
    for net in config.networks:
        names = {n.name for n in net.nodes}
        for msg in net.messages:
            if msg.sender:
                assert msg.sender in names, f"{msg.name}: sender lạ {msg.sender}"


def test_diag_services_have_valid_request_and_response():
    config = demo_configuration()
    ecu = config.diag_ecus[0]
    for service in ecu.services:
        assert service.request_bytes
        assert service.request_bytes[0] == service.sid
        if service.response_bytes and service.response_bytes[0] != 0x7F:
            assert service.response_bytes[0] == service.sid + 0x40
