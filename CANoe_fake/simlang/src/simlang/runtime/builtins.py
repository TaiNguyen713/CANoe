"""`Context` — đối tượng truyền vào mọi handler sinh ra (`ctx`), gói các
builtin cần I/O (`output`, `write`, `setTimer`...). Cũng chứa `StaticTable`
cho `loadStatic()` — bảng nền tĩnh nạp từ file `.sim`, được tra khi không
handler CAPL nào khớp (§1: "handler CAPL phủ đè lên request nào cần logic;
không có thì tra bảng tĩnh")."""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Callable

from .. import simfile
from . import isotp
from .dispatch import DispatchTable, Message
from .isotp import Frame
from .timers import TimerHandle, TimerManager


def random_(n: int) -> int:
    """`random(n)` kiểu CAPL: số nguyên trong [0, n) — KHÔNG phải
    `random.random()` kiểu Python (float [0,1)). Xem plan §10 mục 7."""
    return random.randrange(n)


class StaticTable:
    """Bảng request→response tĩnh nạp từ `.sim`. Best-effort: chỉ khớp
    request đơn khung (SF) không wildcard một cách đáng tin cậy — request đa
    khung hoặc có wildcard trong vùng PCI là ca hiếm, chưa được tài liệu nào
    xác nhận cách engine gốc xử lý, nên KHÔNG cố đoán, chỉ đơn giản không
    khớp (trả None) thay vì suy diễn sai (đúng nguyên tắc §11 của
    HUONG_DAN_FILE_SIM.md)."""

    def __init__(self) -> None:
        self._entries: dict[tuple[int, bytes], list[bytes]] = {}

    def load(self, path: str | Path) -> None:
        report = simfile.parse_sim_file(path)
        exchanges = simfile.group_exchanges(report)
        for ex in exchanges:
            if ex.request is None or ex.request.can_id is None:
                continue
            req_payload = self._reassemble(ex.request.can_id, [ex.request])
            if req_payload is None:
                continue
            res_payloads = []
            if ex.responses:
                can_id = ex.responses[0].can_id or ex.request.can_id
                payload = self._reassemble(can_id, ex.responses)
                if payload is not None:
                    res_payloads.append(payload)
            self._entries.setdefault((ex.request.can_id, req_payload), []).extend(res_payloads)

    def respond(self, msg: Message) -> bytes | None:
        results = self._entries.get((msg.can_id, msg.data))
        return results[0] if results else None

    @staticmethod
    def _reassemble(can_id: int, lines: list[simfile.DataLine]) -> bytes | None:
        reassembler = isotp.Reassembler()
        message = None
        for line in lines:
            byte_values = [b.value for b in line.data_bytes]
            if any(v is None for v in byte_values):
                return None  # wildcard/unknown-marker trong vùng PCI — bỏ qua, không đoán
            frame = Frame(can_id, bytes(byte_values))
            result = reassembler.feed(frame)
            if result.message is not None:
                message = result.message
        return message


class Context:
    def __init__(
        self,
        transport,
        dispatch_table: DispatchTable,
        timer_manager: TimerManager,
        fc_registry: isotp.PendingFcRegistry,
        base_dir: str | Path = ".",
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._dispatch = dispatch_table
        self.timers = timer_manager
        self._fc_registry = fc_registry
        self._base_dir = Path(base_dir)
        self._time_source = time_source
        self._t0: float | None = None
        self.static_table = StaticTable()
        self.current_request: Message | None = None

    def mark_started(self) -> None:
        self._t0 = self._time_source()

    # ---- builtin: output() — tự đóng khung ISO-TP, CAN ID suy ra từ request
    # đang xử lý (quy ước request+8, xem isotp.reply_can_id) ----
    async def output(self, *byte_values: int) -> None:
        if self.current_request is None:
            raise RuntimeError("output() được gọi ngoài ngữ cảnh xử lý request")
        can_id = isotp.reply_can_id(self.current_request.can_id)
        await isotp.send(self._transport, can_id, bytes(byte_values), self._fc_registry)

    # ---- builtin: outputRaw() — gửi thẳng MỘT khung thô, không đóng gói,
    # CAN ID do người viết .can chỉ định tường minh ----
    async def output_raw(self, can_id: int, *b0_7: int) -> None:
        await self._transport.write(Frame(can_id, bytes(b0_7)))

    # ---- builtin: khác ----
    def elapsed(self) -> float:
        if self._t0 is None:
            return 0.0
        return self._time_source() - self._t0

    def write(self, fmt: str, *args) -> None:
        print(fmt % args if args else fmt)

    def load_static(self, path: str) -> None:
        full_path = Path(path)
        if not full_path.is_absolute() and not full_path.exists():
            full_path = self._base_dir / path
        self.static_table.load(full_path)

    def set_timer(self, handle: TimerHandle, ms: int) -> None:
        self.timers.set(handle, ms, self)

    def cancel_timer(self, handle: TimerHandle) -> None:
        self.timers.cancel(handle)
