"""M0 — spike thăm dò đường truyền thô (SPEC_SIMLANG_V2.md §10.1).

**ĐÃ CHẠY THẬT trên board COM3 — xem `docs/M0_findings.md` cho kết quả đầy
đủ.** Script này đã được cập nhật theo những gì xác nhận thật (không còn là
bản đoán ban đầu):

- Constructor `ClassDeviceComport` cần `fVoidCallBackType` callback, không
  phải parameterless.
- Cần 2 fix runtime .NET (pythonnet.load(runtime_config=...) + force-load
  System.IO.Ports.dll bản Windows) — không có 2 fix này, ngay bước tạo
  instance đã crash, dù đang chạy trên Windows thật.
- `WriteConfigProtocol` cần `OBDInterface` set ĐẦY ĐỦ field (DLC profile,
  UART format) — object rỗng bị từ chối (trả `False`, không throw).
- Round-trip **đơn khung** đã xác nhận hoạt động thật (test `01 00` → nhận
  đúng response qua scan tool thật), nhưng qua đường vòng `ObdSimulator`
  (lớp cao, tự dispatch nội bộ), CHƯA qua `ClassDeviceComport` thuần +
  `SendMesg`/`readOBDMsgdata` trực tiếp như kiến trúc simlang v2 muốn.
- Round-trip **đa khung** (First Frame/Consecutive Frame, vd đọc VIN `09
  02`) CHƯA xác nhận hoạt động — cần logic analyzer để chẩn đoán tiếp.

Bốn câu hỏi gốc của spec — trạng thái sau khi chạy thật:
  1. `readOBDMsgdata()` trả về gì → **trả lời được**: object `obdMsgData`
     (fields: `addr`, `lendata`, `data`, `msgtype`, `msgrawdatatype`,
     `timestamp`...). Trả `None` khi chưa có gì (không chặn).
  2. `SendMesg(...)` tham số đầu nghĩa là gì → **trả lời được**: đó là
     `TimeOutMs` (Int32), không phải "channel". Định dạng byte chính xác
     của `FullMsg` CHƯA xác nhận chắc chắn (chỉ test được round-trip đơn
     khung qua đường khác, không qua SendMesg trực tiếp).
  3. Board có tự lọc/tự trả lời khung không → **trả lời được**: KHÔNG, im
     lặng hoàn toàn nếu không có DB nạp.
  4. Độ trễ vòng → chưa đo mili-giây cụ thể, nhưng round-trip đơn khung xảy
     ra đủ nhanh để scan tool không timeout.

Cách chạy (trên máy có board + pythonnet đã cài — same máy build code này,
đã xác nhận có 2 board COM3/COM5 khớp VID:PID 0483:2010):

    python simlang/spike/m0_probe.py COM3
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_DLL_DIR = (
    Path(__file__).resolve().parents[2]
    / "engine" / "OBDSimulation_CLI_1.3.36.3" / "x64" / "net9.0"
)
_DLL_PATH = _DLL_DIR / "SimulatorInterface.dll"
_RUNTIMECONFIG_PATH = _DLL_DIR / "OBDSimulation_CLI.runtimeconfig.json"
_WIN_PORTS_DLL = _DLL_DIR / "runtimes" / "win" / "lib" / "net8.0" / "System.IO.Ports.dll"

_PROBE_REQUEST_SERVICE = 0x09
_PROBE_REQUEST_PID = 0x02


def _load_clr():
    """2 fix runtime .NET xác nhận BẮT BUỘC — xem docs/M0_findings.md §7."""
    import pythonnet

    pythonnet.load("coreclr", runtime_config=str(_RUNTIMECONFIG_PATH))
    import clr  # type: ignore[import-not-found]

    if _WIN_PORTS_DLL.exists():
        clr.AddReference(str(_WIN_PORTS_DLL))
    else:
        print(f"[M0] CẢNH BÁO: không tìm thấy {_WIN_PORTS_DLL} — có thể vẫn lỗi PlatformNotSupportedException")
    clr.AddReference(str(_DLL_PATH))
    return clr


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Dùng: python {argv[0]} <COM_PORT>")
        return 2
    port = argv[1]

    print(f"[M0] DLL: {_DLL_PATH} (tồn tại: {_DLL_PATH.exists()})")
    print(f"[M0] Cổng: {port}")

    try:
        clr = _load_clr()
    except ImportError:
        print("[M0] LỖI: pythonnet chưa cài. `pip install pythonnet` rồi chạy lại.")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[M0] LỖI khi nạp CLR/DLL: {exc!r}")
        return 1

    try:
        from SimulatorInterface import (
            ClassDeviceComport,
            OBDInterface,
            clsuartformat,
            enum_obd_serial_msg_type,
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
    except Exception as exc:  # noqa: BLE001
        print(f"[M0] KHÔNG import được type cần thiết: {exc!r}")
        return 1

    callback_count = [0]

    def on_callback():
        callback_count[0] += 1
        print(f"[M0] callback fired! (lần {callback_count[0]}) — ý nghĩa CHƯA xác nhận")

    cb = fVoidCallBackType(on_callback)
    device = ClassDeviceComport(cb)
    print(f"[M0] Đã tạo instance: {device!r}")

    print(f"[M0] Đang mở cổng {port}...")
    try:
        info = device.Open(port)
        print(f"[M0] Open({port!r}) -> {list(info) if info is not None else info!r} "
              f"(format xác nhận: [port, firmware_version, device_guid])")
    except Exception as exc:  # noqa: BLE001
        print(f"[M0] Open({port!r}) LỖI: {exc!r}")
        return 1

    print("[M0] Đang cấu hình OBDInterface (CAN 500kbps, pin 6/14 — chuẩn OBD-II)...")
    dlckline = structDLCProfile()
    dlckline.dlcpin = enumDLCPinName.DLC_PIN6
    dlckline.voltage = enumVoltageLevel.LEVEL_12V
    dlckline.resistor = enumPUResitor.PU_NONE
    dlckline.isinverted = False

    dlclline = structDLCProfile()
    dlclline.dlcpin = enumDLCPinName.DLC_PIN14
    dlclline.voltage = enumVoltageLevel.LEVEL_12V
    dlclline.resistor = enumPUResitor.PU_NONE
    dlclline.isinverted = False

    uartinfo = clsuartformat()
    uartinfo.databit = enumDataBit.D_8
    uartinfo.parity = enumParity.P_NONE
    uartinfo.stopbit = enumstopbit.S_1

    obdif = OBDInterface("1.0")
    obdif.protocol = enumprotocol.DWCAN
    obdif.baudrate = 500_000
    obdif.timingp4 = 3
    obdif.timingp2 = 5
    obdif.dlckline = dlckline
    obdif.dlclline = dlclline
    obdif.clsuartinfo = uartinfo

    try:
        ok = device.WriteConfigProtocol(obdif)
        print(f"[M0] WriteConfigProtocol(...) -> {ok} (False = object thiếu field, xem docs/M0_findings.md §4)")
        if not ok:
            return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[M0] WriteConfigProtocol(...) LỖI: {exc!r}")
        return 1

    device.SetActiveProtocol(enumprotocol.DWCAN)
    print("[M0] SetActiveProtocol(DWCAN) OK")

    try:
        started = device.startdevice()
        print(f"[M0] startdevice() -> {started}")
    except Exception as exc:  # noqa: BLE001
        print(f"[M0] startdevice() LỖI: {exc!r}")
        return 1

    print(f"[M0] Vòng lặp đọc trong 20 giây — gửi request 09 02 (đọc VIN) hoặc 01 00 (PID discovery) từ scan tool THẬT ngay bây giờ.")
    deadline = time.monotonic() + 20.0
    seen_anything = False
    while time.monotonic() < deadline:
        try:
            raw = device.readOBDMsgdata()
        except Exception as exc:  # noqa: BLE001
            print(f"[M0] readOBDMsgdata() LỖI: {exc!r}")
            break
        if raw is not None:
            seen_anything = True
            t = time.monotonic()
            data_list = list(raw.data) if raw.data else None
            print(f"[M0] t={t:.3f} readOBDMsgdata() -> addr={raw.addr} lendata={raw.lendata} "
                  f"msgtype={raw.msgtype} rawtype={raw.msgrawdatatype} data={data_list}")

            try:
                import System  # type: ignore[import-not-found]

                result = device.SendMesg(100, System.Array[System.Byte]([0x49, 0x02, 0x01]), enum_obd_serial_msg_type.OBD_MSG_NORMAL)
                print(f"[M0] SendMesg(100, ..., NORMAL) thử nghiệm -> {result!r} (định dạng FullMsg CHƯA xác nhận, xem docs/M0_findings.md §3)")
            except Exception as exc:  # noqa: BLE001
                print(f"[M0] SendMesg(...) LỖI: {exc!r}")
        time.sleep(0.02)

    if not seen_anything:
        print("[M0] KHÔNG thấy khung nào qua ClassDeviceComport.readOBDMsgdata() trực tiếp trong 20 giây.")
        print("[M0] -> Đã xác nhận (M0 trước): round-trip qua ObdSimulator (lớp cao, Database_LoadFile)")
        print("[M0]    HOẠT ĐỘNG cho request đơn khung. Nếu ClassDeviceComport thuần vẫn im lặng ở đây,")
        print("[M0]    có thể lớp thấp cần thêm bước khởi tạo nào đó mà ObdSimulator làm ngầm bên trong")
        print("[M0]    (chưa xác định được bước đó là gì — cần đọc thêm code nội bộ ObdSimulator).")

    try:
        device.stopdevice()
    except Exception as exc:  # noqa: BLE001
        print(f"[M0] stopdevice() LỖI: {exc!r}")
    try:
        device.Close()
    except Exception as exc:  # noqa: BLE001
        print(f"[M0] Close() LỖI: {exc!r}")

    print("[M0] Xong. So sánh với docs/M0_findings.md, cập nhật nếu có phát hiện mới.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
