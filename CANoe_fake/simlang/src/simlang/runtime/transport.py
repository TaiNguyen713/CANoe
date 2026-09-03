"""Lớp giao tiếp phần cứng. `FakeTransport` là thứ TOÀN BỘ test suite dùng —
không cần board thật (M1/M2/M4/M5 chạy hoàn toàn không cần phần cứng).
`RealTransport` viết theo §7 của SPEC_SIMLANG_V2.md nhưng các điểm cần câu
trả lời từ M0 (dạng dữ liệu `readOBDMsgdata`/`SendMesg` thật) để trống dưới
dạng `TODO(M0)` — không thể tự chạy/xác minh trong môi trường này (không có
COM port/board thật).
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from .isotp import Frame


class Transport(Protocol):
    def open(self, port: str) -> None: ...
    def close(self) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    async def read(self) -> Frame: ...
    async def write(self, frame: Frame) -> None: ...


class FakeTransport:
    """Giả lập trong bộ nhớ cho test. `.sent` ghi lại mọi khung đã gửi (để
    assert), `.inject()` mô phỏng một khung nhận được từ scan tool."""

    def __init__(self) -> None:
        self.sent: list[Frame] = []
        self._inbox: asyncio.Queue[Frame] = asyncio.Queue()
        self.opened_port: str | None = None
        self.started = False

    def open(self, port: str) -> None:
        self.opened_port = port

    def close(self) -> None:
        self.opened_port = None

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def inject(self, frame: Frame) -> None:
        self._inbox.put_nowait(frame)

    async def read(self) -> Frame:
        return await self._inbox.get()

    async def write(self, frame: Frame) -> None:
        self.sent.append(frame)


class RealTransport:
    """Binding qua pythonnet tới `ClassDeviceComport` trong
    `SimulatorInterface.dll` (§7). `import clr` nằm TRONG `__init__`, không ở
    top-level module — máy không cài pythonnet vẫn import được
    `runtime.transport` bình thường (toàn bộ test suite M1/M2/M4/M5 chỉ dùng
    `FakeTransport`, không bao giờ chạm tới class này).

    Các hàm dưới đây là TODO(M0): chưa biết chính xác `readOBDMsgdata` trả
    về cấu trúc gì, `SendMesg` cần tham số/định dạng `data` ra sao — spike
    ở `simlang/spike/m0_probe.py` phải trả lời trước khi implement thật.
    Không đoán rồi viết liều — xem SPEC_SIMLANG_V2.md §10.1/§12.
    """

    def __init__(self, dll_path: str) -> None:
        import clr  # type: ignore[import-not-found]

        clr.AddReference(dll_path)
        from SimulatorInterface import ClassDeviceComport  # type: ignore[import-not-found]

        self._device = ClassDeviceComport()

    def open(self, port: str) -> None:
        # TODO(M0): xác nhận dùng Open(port) hay DeviceOpenConnection(port)
        self._device.Open(port)

    def close(self) -> None:
        raise NotImplementedError("TODO(M0): chưa xác nhận API đóng cổng")

    def start(self) -> None:
        self._device.startdevice()

    def stop(self) -> None:
        self._device.stopdevice()

    async def read(self) -> Frame:
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, self._device.readOBDMsgdata)
        return self._decode_frame(raw)

    async def write(self, frame: Frame) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._encode_and_send, frame)

    def _decode_frame(self, raw) -> Frame:
        raise NotImplementedError(
            "TODO(M0): chưa biết readOBDMsgdata() trả về cấu trúc gì "
            "(byte array? object? chuỗi?) — xem spike/m0_probe.py"
        )

    def _encode_and_send(self, frame: Frame) -> None:
        raise NotImplementedError(
            "TODO(M0): chưa biết SendMesg() cần tham số đầu (vd '1') nghĩa "
            "là gì, và định dạng `data` chính xác — xem spike/m0_probe.py"
        )
