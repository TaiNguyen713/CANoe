"""Lớp giao tiếp phần cứng. `FakeTransport` là thứ TOÀN BỘ test suite dùng —
không cần board thật (M1/M2/M4/M5 chạy hoàn toàn không cần phần cứng).

`RealTransport` đã được cập nhật theo kết quả spike M0 THẬT (chạy trên board
COM3 thật, xem `docs/M0_findings.md` — đọc file đó trước khi sửa gì ở đây).
Vẫn còn một số điểm CHƯA xác nhận đầy đủ (đánh dấu rõ trong docstring từng
hàm) — round-trip đơn khung (Single Frame) đã xác nhận hoạt động thật qua
scan tool thật; round-trip đa khung (First Frame/Consecutive Frame) và định
dạng byte chính xác của `SendMesg` thì CHƯA.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
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


def _load_clr_for_simulator_dll(dll_path: Path):
    """Hai fix runtime .NET BẮT BUỘC, xác nhận thật qua spike M0 (xem
    `docs/M0_findings.md` §7) — thiếu 1 trong 2 là `ClassDeviceComport(...)`
    ném exception ngay khi khởi tạo, dù chạy trên Windows thật:

    1. pythonnet phải bootstrap ĐÚNG runtime của chính app (không phải
       runtime mặc định pythonnet tự chọn) — nếu không: TypeLoadException
       khi load `System.ComponentModel.Component`.
    2. Bản `System.IO.Ports.dll` phải là bản WINDOWS THẬT (trong
       `runtimes/win/lib/net8.0/`), nạp TRƯỚC `SimulatorInterface.dll` —
       nếu không, bản "reference stub" RID-agnostic được nạp thay vào, ném
       `PlatformNotSupportedException` dù đang chạy trên Windows.

    Trả về module `clr` đã sẵn sàng gọi `AddReference` cho SimulatorInterface.dll.
    """
    import pythonnet

    base = dll_path.parent
    runtimeconfig = base / "OBDSimulation_CLI.runtimeconfig.json"
    if not pythonnet.get_runtime_info():
        pythonnet.load("coreclr", runtime_config=str(runtimeconfig))

    import clr  # type: ignore[import-not-found]

    win_ports_dll = base / "runtimes" / "win" / "lib" / "net8.0" / "System.IO.Ports.dll"
    if win_ports_dll.exists():
        clr.AddReference(str(win_ports_dll))
    clr.AddReference(str(dll_path))
    return clr


class RealTransport:
    """Binding qua pythonnet tới `ClassDeviceComport` trong
    `SimulatorInterface.dll` (§7 của SPEC_SIMLANG_V2.md). `import
    pythonnet`/`clr` nằm TRONG `__init__`, không ở top-level module — máy
    không cài pythonnet vẫn import được `runtime.transport` bình thường
    (toàn bộ test suite M1/M2/M4/M5 chỉ dùng `FakeTransport`).

    Cấu hình CAN mặc định (protocol/pin/baudrate) khớp `<config sw>` của mọi
    fixture `.sim` thật đã thấy (`CAN_default*.sim`, file xe Hyundai) —
    truyền `protocol_config=` khác nếu xe/board dùng cấu hình khác.
    """

    def __init__(
        self,
        dll_path: str,
        baudrate: int = 500_000,
        timingp4: int = 3,
        timingp2: int = 5,
        krx_pin: int = 6,
        ktx_pin: int = 14,
    ) -> None:
        clr = _load_clr_for_simulator_dll(Path(dll_path))
        from SimulatorInterface import (  # type: ignore[import-not-found]
            ClassDeviceComport,
            OBDInterface,
            clsuartformat,
            enumDataBit,
            enumDLCPinName,
            enumParity,
            enumprotocol,
            enumPUResitor,
            enumstopbit,
            enumVoltageLevel,
            fVoidCallBackType,
            structDLCProfile,
        )

        # Ý nghĩa thật của callback CHƯA xác nhận (không fire lần nào trong
        # mọi lần test M0) — truyền no-op, không dựa vào nó cho logic gì.
        self._callback = fVoidCallBackType(lambda: None)
        self._device = ClassDeviceComport(self._callback)

        dlckline = structDLCProfile()
        dlckline.dlcpin = getattr(enumDLCPinName, f"DLC_PIN{krx_pin}")
        dlckline.voltage = enumVoltageLevel.LEVEL_12V
        dlckline.resistor = enumPUResitor.PU_NONE
        dlckline.isinverted = False

        dlclline = structDLCProfile()
        dlclline.dlcpin = getattr(enumDLCPinName, f"DLC_PIN{ktx_pin}")
        dlclline.voltage = enumVoltageLevel.LEVEL_12V
        dlclline.resistor = enumPUResitor.PU_NONE
        dlclline.isinverted = False

        uartinfo = clsuartformat()
        uartinfo.databit = enumDataBit.D_8
        uartinfo.parity = enumParity.P_NONE
        uartinfo.stopbit = enumstopbit.S_1

        self._obdif = OBDInterface("1.0")
        self._obdif.protocol = enumprotocol.DWCAN
        self._obdif.baudrate = baudrate
        self._obdif.timingp4 = timingp4
        self._obdif.timingp2 = timingp2
        self._obdif.dlckline = dlckline
        self._obdif.dlclline = dlclline
        self._obdif.clsuartinfo = uartinfo
        self._enumprotocol = enumprotocol

    def open(self, port: str) -> None:
        # Open() trả String[3]: [port, firmware_version, device_guid] —
        # xác nhận thật qua M0, KHÔNG phải bool như đoán ban đầu.
        info = self._device.Open(port)
        ok = self._device.WriteConfigProtocol(self._obdif)
        if not ok:
            raise RuntimeError(
                f"WriteConfigProtocol từ chối config (Open trả về {list(info)!r}) — "
                "kiểm tra lại obdif đã set đủ field chưa, xem docs/M0_findings.md §4"
            )
        self._device.SetActiveProtocol(self._enumprotocol.DWCAN)

    def close(self) -> None:
        self._device.Close()

    def start(self) -> None:
        self._device.startdevice()

    def stop(self) -> None:
        self._device.stopdevice()

    async def read(self) -> Frame:
        """`readOBDMsgdata()` không chặn — trả `None` ngay nếu chưa có gì
        (xác nhận qua M0: polling 5-20s không traffic luôn ra None ngay lập
        tức, không phải blocking call). Nên tự poll với sleep nhỏ."""
        loop = asyncio.get_running_loop()
        while True:
            raw = await loop.run_in_executor(None, self._device.readOBDMsgdata)
            if raw is not None:
                return self._decode_frame(raw)
            await asyncio.sleep(0.01)

    def _decode_frame(self, raw) -> Frame:
        # raw: obdMsgData — .addr (Int32, CAN ID), .data (List<T>, kiểu
        # phần tử CHƯA xác nhận chắc chắn — giả định List<Byte>, xem
        # docs/M0_findings.md §2). CHƯA xác nhận round-trip đa khung nên
        # hàm này chỉ mới test được với dữ liệu None (không traffic).
        data = bytes(raw.data) if raw.data else b""
        return Frame(can_id=raw.addr, data=data)

    async def write(self, frame: Frame) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._encode_and_send, frame)

    def _encode_and_send(self, frame: Frame) -> None:
        # SendMesg(TimeOutMs, FullMsg, msg_type) — chữ ký xác nhận thật qua
        # M0 (reflection), nhưng ĐỊNH DẠNG CHÍNH XÁC của FullMsg CHƯA xác
        # nhận (round-trip Single Frame đã test thành công qua đường
        # ObdSimulator cấp cao, KHÔNG PHẢI qua SendMesg trực tiếp — xem
        # docs/M0_findings.md §5). Đoán tạm: CAN ID 4 byte + data — CẦN
        # kiểm chứng lại bằng logic analyzer trước khi tin cậy.
        import System  # type: ignore[import-not-found]
        from SimulatorInterface import enum_obd_serial_msg_type  # type: ignore[import-not-found]

        can_id_bytes = frame.can_id.to_bytes(4, "big")
        full_msg = System.Array[System.Byte](list(can_id_bytes) + list(frame.data))
        self._device.SendMesg(100, full_msg, enum_obd_serial_msg_type.OBD_MSG_NORMAL)
