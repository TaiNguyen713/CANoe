"""Mã hoá / giải mã signal trong payload CAN.

Hỗ trợ cả hai kiểu sắp xếp bit của DBC: Intel (little-endian, đếm bit từ LSB)
và Motorola (big-endian, đếm bit theo sơ đồ Vector).
"""

from __future__ import annotations

from .database import ByteOrder, MessageDef, SignalDef


def _bits_to_int(data: bytes, start_bit: int, length: int,
                 order: ByteOrder) -> int:
    if length <= 0:
        return 0
    total_bits = len(data) * 8
    value = 0
    if order is ByteOrder.INTEL:
        for i in range(length):
            bit_index = start_bit + i
            if bit_index >= total_bits:
                break
            byte = data[bit_index // 8]
            if byte >> (bit_index % 8) & 1:
                value |= 1 << i
    else:
        # Motorola: bit đếm từ MSB của byte, đi xuống rồi sang byte kế tiếp
        bit_index = start_bit
        for _ in range(length):
            byte_index = bit_index // 8
            if byte_index >= len(data):
                break
            bit_in_byte = 7 - (bit_index % 8)
            value = (value << 1) | (data[byte_index] >> bit_in_byte & 1)
            if bit_index % 8 == 0:
                bit_index += 15
            else:
                bit_index -= 1
    return value


def _int_to_bits(data: bytearray, start_bit: int, length: int,
                 order: ByteOrder, value: int) -> None:
    total_bits = len(data) * 8
    if order is ByteOrder.INTEL:
        for i in range(length):
            bit_index = start_bit + i
            if bit_index >= total_bits:
                break
            mask = 1 << (bit_index % 8)
            if value >> i & 1:
                data[bit_index // 8] |= mask
            else:
                data[bit_index // 8] &= ~mask & 0xFF
    else:
        bit_index = start_bit
        for i in range(length):
            byte_index = bit_index // 8
            if byte_index >= len(data):
                break
            bit_in_byte = 7 - (bit_index % 8)
            bit = value >> (length - 1 - i) & 1
            if bit:
                data[byte_index] |= 1 << bit_in_byte
            else:
                data[byte_index] &= ~(1 << bit_in_byte) & 0xFF
            if bit_index % 8 == 0:
                bit_index += 15
            else:
                bit_index -= 1


def _apply_sign(raw: int, length: int, is_signed: bool) -> int:
    if is_signed and length > 0 and raw >> (length - 1) & 1:
        return raw - (1 << length)
    return raw


def decode_signal(sig: SignalDef, data: bytes) -> float:
    """Trả về giá trị vật lý của một signal trong payload."""
    raw = _bits_to_int(data, sig.start_bit, sig.bit_length, sig.byte_order)
    raw = _apply_sign(raw, sig.bit_length, sig.is_signed)
    return sig.raw_to_phys(raw)


def decode_message(msg: MessageDef, data: bytes) -> dict[str, float]:
    """Giải mã toàn bộ signal của một message."""
    return {s.name: decode_signal(s, data) for s in msg.signals}


def encode_signal(sig: SignalDef, data: bytearray, phys: float) -> None:
    """Ghi giá trị vật lý của một signal vào payload (sửa tại chỗ)."""
    raw = sig.phys_to_raw(phys)
    limit = 1 << sig.bit_length
    if sig.is_signed:
        raw = max(-(limit >> 1), min((limit >> 1) - 1, raw))
        if raw < 0:
            raw += limit
    else:
        raw = max(0, min(limit - 1, raw))
    _int_to_bits(data, sig.start_bit, sig.bit_length, sig.byte_order, raw)


def encode_message(msg: MessageDef, values: dict[str, float]) -> bytes:
    """Dựng payload từ tập giá trị vật lý của các signal."""
    data = bytearray(msg.dlc)
    for sig in msg.signals:
        if sig.name in values:
            encode_signal(sig, data, values[sig.name])
    return bytes(data)


def format_payload(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


_HEX_CHARS = set("0123456789abcdefABCDEF")


def parse_payload(text: str) -> bytes:
    """Đọc chuỗi hex kiểu '01 A2 FF', '01A2FF' hoặc '0x22, 0xF1' thành bytes.

    Token không phải hex hợp lệ bị bỏ qua, không ném lỗi — hàm này nhận dữ liệu
    người dùng gõ tay trong Diagnostic Console.
    """
    cleaned = text.replace("0x", " ").replace("0X", " ").replace(",", " ").split()
    # dạng liền một khối '01A2FF' -> tách thành từng cặp, chỉ khi toàn ký tự hex
    if len(cleaned) == 1 and len(cleaned[0]) > 2:
        blob = cleaned[0]
        if all(c in _HEX_CHARS for c in blob) and len(blob) % 2 == 0:
            cleaned = [blob[i:i + 2] for i in range(0, len(blob), 2)]
    out = bytearray()
    for token in cleaned:
        if len(token) > 2 or not all(c in _HEX_CHARS for c in token):
            continue
        out.append(int(token, 16) & 0xFF)
    return bytes(out)
