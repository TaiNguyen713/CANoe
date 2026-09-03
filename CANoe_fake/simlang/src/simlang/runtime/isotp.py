"""ISO-TP (ISO 15765-2): đóng/mở khung cả hai chiều.

Lõi (`Reassembler`, `FrameBuilder`, `ff_length`) thuần, đồng bộ, không I/O —
test được bằng dữ liệu thường, không cần event loop. Lớp điều phối async
(`send`, `PendingFcRegistry`) nằm phía dưới, dùng cho `runtime/builtins.py`.

Độ dài First Frame tính đúng: `((b0 & 0x0F) << 8) | b1`. Engine gốc của
vendor tính SAI bằng `(b0 & 0xF00) + b1` — `b0` chỉ là 1 byte nên `& 0xF00`
luôn ra 0 (xem HUONG_DAN_FILE_SIM.md §11c). Không tái tạo lại bug đó ở đây.

**Quyết định thiết kế cần lưu ý**: SPEC_SIMLANG_V2.md §6.4 viết "seq quay
vòng 0x20→0x2F→0x20" (ngụ ý bắt đầu từ 0), nhưng chuẩn ISO 15765-2 thật quy
định số thứ tự Consecutive Frame bắt đầu từ 1 (`0x21`), sau đó 2,3,...,15,
rồi quay về 0 (`0x20`), rồi lại 1... Module này theo ĐÚNG CHUẨN THẬT (bắt
đầu từ 1) vì mục đích của công cụ là giao tiếp với scan tool thật ngoài đời,
không phải khớp nguyên văn diễn giải của spec — xem ghi chú trong plan.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol


def ff_length(b0: int, b1: int) -> int:
    """Độ dài payload logic khai trong First Frame — công thức ĐÚNG."""
    return ((b0 & 0x0F) << 8) | b1


_FUNCTIONAL_REQUEST_ID = 0x7DF
_FUNCTIONAL_REPLY_ID = 0x7E8  # ECU mô phỏng duy nhất luôn trả lời ở đây


def reply_can_id(request_can_id: int) -> int:
    """Quy ước OBD-II: ECU trả lời trên CAN ID = request + 8 cho ĐỊA CHỈ VẬT
    LÝ (0x7E0 → 0x7E8). KHÔNG áp dụng công thức đó cho địa chỉ functional
    broadcast (0x7DF) — 0x7DF + 8 = 0x7E7 SAI, xác nhận trực tiếp bằng dữ
    liệu thật trong DTC_info.sim (mọi request `00 00 07 DF` đều nhận response
    `00 00 07 E8`, không phải 07 E7). simlang chỉ mô phỏng MỘT ECU nên mọi
    request functional cũng trả lời trên đúng địa chỉ vật lý cố định đó.

    Không có trong đặc tả — suy ra từ token `+08` quan sát được trong
    DTC_info.sim. Dùng chung cho cả Reassembler (khung Flow Control tự sinh)
    và runtime/builtins.py (Context.output())."""
    if request_can_id == _FUNCTIONAL_REQUEST_ID:
        return _FUNCTIONAL_REPLY_ID
    return request_can_id + 8


def _pad8(data: bytes) -> bytes:
    if len(data) >= 8:
        return bytes(data[:8])
    return bytes(data) + b"\x00" * (8 - len(data))


def _decode_st_min(raw: int) -> float:
    """STmin theo ISO 15765-2: 0x00-0x7F = 0-127 ms; 0xF1-0xF9 = 0.1-0.9 ms;
    còn lại (dự trữ/không hợp lệ) coi như 0."""
    if 0x00 <= raw <= 0x7F:
        return float(raw)
    if 0xF1 <= raw <= 0xF9:
        return (raw - 0xF0) / 10.0
    return 0.0


@dataclass(frozen=True)
class Frame:
    can_id: int
    data: bytes  # luôn đủ 8 byte

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _pad8(self.data))


@dataclass
class ReassemblyResult:
    message: bytes | None = None
    control_frame: Frame | None = None


@dataclass
class _PendingRx:
    total_length: int
    buffer: bytearray
    next_seq: int  # nibble kỳ vọng cho CF tiếp theo (bắt đầu từ 1)


class Reassembler:
    """Ghép SF/FF/CF theo từng CAN ID riêng (nhiều phiên ghép song song được
    theo dõi độc lập). Thuần — không tự gửi gì, chỉ TRẢ VỀ khung FC cần gửi
    (`control_frame`) để caller tự quyết định gửi qua transport nào."""

    def __init__(self) -> None:
        self._pending: dict[int, _PendingRx] = {}

    def feed(self, frame: Frame) -> ReassemblyResult:
        if not frame.data:
            return ReassemblyResult()
        pci = frame.data[0]
        frame_type = (pci >> 4) & 0x0F

        if frame_type == 0x0:  # Single Frame
            length = pci & 0x0F
            self._pending.pop(frame.can_id, None)
            return ReassemblyResult(message=bytes(frame.data[1:1 + length]))

        if frame_type == 0x1:  # First Frame
            length = ff_length(frame.data[0], frame.data[1])
            self._pending[frame.can_id] = _PendingRx(
                total_length=length, buffer=bytearray(frame.data[2:8]), next_seq=1
            )
            fc = Frame(reply_can_id(frame.can_id), bytes([0x30, 0x00, 0x00]))
            return ReassemblyResult(control_frame=fc)

        if frame_type == 0x2:  # Consecutive Frame
            pending = self._pending.get(frame.can_id)
            if pending is None:
                return ReassemblyResult()  # CF mồ côi, không có FF trước đó — bỏ qua
            needed = pending.total_length - len(pending.buffer)
            pending.buffer.extend(frame.data[1:1 + min(7, needed)])
            pending.next_seq = (pci & 0x0F) + 1
            if pending.next_seq > 0x0F:
                pending.next_seq = 0
            if len(pending.buffer) >= pending.total_length:
                complete = bytes(pending.buffer[: pending.total_length])
                del self._pending[frame.can_id]
                return ReassemblyResult(message=complete)
            return ReassemblyResult()

        return ReassemblyResult()  # Flow Control (0x3) — xem PendingFcRegistry, không xử lý ở đây


class FrameBuilder:
    """Sinh chuỗi khung để gửi một payload logic ra ngoài. Thuần — không tự
    gửi, không tự chờ FC; `runtime.isotp.send()` bên dưới điều phối việc đó."""

    def __init__(self, can_id: int, payload: bytes) -> None:
        self.can_id = can_id
        self.payload = bytes(payload)
        self.block_size = 0
        self.st_min_ms = 0.0

    def first(self) -> Frame:
        if len(self.payload) <= 7:
            pci = len(self.payload) & 0x0F
            return Frame(self.can_id, bytes([pci]) + self.payload)
        length = len(self.payload)
        b0 = 0x10 | ((length >> 8) & 0x0F)
        b1 = length & 0xFF
        return Frame(self.can_id, bytes([b0, b1]) + self.payload[:6])

    @property
    def needs_fc(self) -> bool:
        return len(self.payload) > 7

    def apply_fc(self, block_size: int, st_min_ms: float) -> None:
        self.block_size = block_size
        self.st_min_ms = st_min_ms

    def remaining(self) -> list[Frame]:
        if len(self.payload) <= 7:
            return []
        rest = self.payload[6:]
        frames = []
        for i in range(0, len(rest), 7):
            chunk = rest[i:i + 7]
            seq_index = i // 7  # 0-based
            pci = 0x20 | (((seq_index + 1) % 16))
            frames.append(Frame(self.can_id, bytes([pci]) + chunk))
        return frames


# ---------------------------------------------------------------------------
# Điều phối async (dùng bởi runtime/builtins.py::Context.output())
# ---------------------------------------------------------------------------


class Transport(Protocol):
    async def write(self, frame: Frame) -> None: ...


class PendingFcRegistry:
    """Cầu nối giữa task đọc duy nhất (đọc mọi khung đến) và task handler
    đang giữa chừng gửi một payload đa khung: task đọc gọi
    `resolve_if_pending()` TRƯỚC khi dispatch bình thường; nếu khung trông
    giống Flow Control (PCI 0x3_) và có đăng ký đang chờ cho đúng CAN ID đó,
    nó được chuyển thẳng vào Future thay vì đi qua dispatch — không phải kiến
    trúc nêu nguyên văn trong spec, mà là cách giải quyết cụ thể cho khoảng
    trống giữa mô hình 'một task đọc' (§6.3) và nhu cầu gửi đa khung."""

    def __init__(self) -> None:
        self._pending: dict[int, asyncio.Future[Frame]] = {}

    def register(self, can_id: int) -> asyncio.Future[Frame]:
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[Frame] = loop.create_future()
        self._pending[can_id] = fut
        return fut

    def resolve_if_pending(self, frame: Frame) -> bool:
        if not frame.data:
            return False
        if ((frame.data[0] >> 4) & 0x0F) != 0x3:
            return False
        fut = self._pending.get(frame.can_id)
        if fut is None or fut.done():
            return False
        del self._pending[frame.can_id]
        fut.set_result(frame)
        return True


class FlowControlTimeout(TimeoutError):
    pass


async def send(
    transport: Transport,
    can_id: int,
    payload: bytes,
    fc_registry: PendingFcRegistry,
    fc_timeout_s: float = 1.0,
) -> None:
    """Gửi một payload logic (tự đóng khung SF hoặc FF+chờ FC+CF)."""
    builder = FrameBuilder(can_id, payload)
    await transport.write(builder.first())
    if not builder.needs_fc:
        return

    frames = None
    block_size, st_min_ms = 0, 0.0
    sent_since_fc = 0
    fut = fc_registry.register(can_id)
    try:
        fc_frame = await asyncio.wait_for(fut, timeout=fc_timeout_s)
    except asyncio.TimeoutError as exc:
        raise FlowControlTimeout(
            f"không nhận được Flow Control cho CAN ID 0x{can_id:X} trong {fc_timeout_s}s"
        ) from exc
    block_size = fc_frame.data[1]
    st_min_ms = _decode_st_min(fc_frame.data[2])
    builder.apply_fc(block_size, st_min_ms)
    frames = builder.remaining()

    for frame in frames:
        await transport.write(frame)
        sent_since_fc += 1
        if block_size and sent_since_fc >= block_size:
            fut = fc_registry.register(can_id)
            try:
                fc_frame = await asyncio.wait_for(fut, timeout=fc_timeout_s)
            except asyncio.TimeoutError as exc:
                raise FlowControlTimeout(
                    f"không nhận được Flow Control tiếp theo cho CAN ID 0x{can_id:X}"
                ) from exc
            block_size = fc_frame.data[1]
            st_min_ms = _decode_st_min(fc_frame.data[2])
            sent_since_fc = 0
        elif st_min_ms > 0:
            await asyncio.sleep(st_min_ms / 1000)
