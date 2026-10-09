"""Bảng dispatch: khớp một `Message` (payload ISO-TP đã ghép xong) với handler
đã đăng ký, theo độ ưu tiên `data > pid > service > (không khớp -> bảng
tĩnh)` — xem SPEC_SIMLANG_V2.md §5.3.

`data` trong mỗi `Handler` là tuple các `(value, is_wildcard)` — KHÔNG tái sử
dụng `ast_nodes.ByteMatch` trực tiếp để giữ `runtime/` tách rời khỏi lớp
parser/AST (chỉ codegen mới biết về AST; runtime chỉ cần dữ liệu thô)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass(frozen=True)
class Message:
    can_id: int
    data: bytes  # payload logic ĐÃ ghép ISO-TP, KHÔNG còn PCI

    @property
    def service(self) -> int | None:
        return self.data[0] if self.data else None

    @property
    def pid(self) -> int | None:
        return self.data[1] if len(self.data) > 1 else None


DataPattern = tuple[tuple[int | None, bool], ...]  # (value, is_wildcard) mỗi byte
# QUY ƯỚC: pattern mô tả TOÀN BỘ msg.data từ byte 0 (bao gồm byte service),
# không phải phần "thêm" sau service/pid — xem ghi chú trong grammar/simlang.lark
# tại rule on_request. `data` có specificity cao nhất nên phải tự đủ để khớp.


def _data_matches(pattern: DataPattern, payload: bytes) -> bool:
    """Khớp CHÍNH XÁC độ dài (không phải khớp tiền tố) — xem plan §10 mục 13."""
    if len(pattern) != len(payload):
        return False
    return all(is_wild or value == byte for (value, is_wild), byte in zip(pattern, payload))


@dataclass
class Handler:
    can_id: int
    service: int
    pid: int | None
    data: DataPattern | None
    fn: Callable[..., Awaitable[None]]
    specificity: int  # 0=chỉ service, +1=pid, +2=data


class DispatchTable:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []
        self._raw_handlers: dict[int, list[Callable[..., Awaitable[None]]]] = {}

    def register(
        self,
        can_id: int,
        service: int,
        fn: Callable[..., Awaitable[None]],
        pid: int | None = None,
        data: DataPattern | None = None,
    ) -> None:
        specificity = (2 if data is not None else 0) + (1 if pid is not None else 0)
        self._handlers.append(Handler(can_id, service, pid, data, fn, specificity))

    def register_raw(self, can_id: int, fn: Callable[..., Awaitable[None]]) -> None:
        self._raw_handlers.setdefault(can_id, []).append(fn)

    def find(self, msg: Message) -> Handler | None:
        candidates = [
            h for h in self._handlers
            if h.can_id == msg.can_id and h.service == msg.service
        ]
        matched = []
        for h in candidates:
            if h.data is not None:
                if not _data_matches(h.data, msg.data):
                    continue
            elif h.pid is not None:
                if h.pid != msg.pid:
                    continue
            matched.append(h)
        if not matched:
            return None
        # specificity cao nhất thắng; đồng hạng thì ai đăng ký trước thắng
        # (sort ổn định — self._handlers giữ nguyên thứ tự đăng ký).
        return max(matched, key=lambda h: h.specificity)

    def find_raw(self, can_id: int) -> list[Callable[..., Awaitable[None]]]:
        return list(self._raw_handlers.get(can_id, ()))
