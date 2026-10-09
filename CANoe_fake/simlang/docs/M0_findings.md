# M0 — kết quả spike raw transceiver

**Ngày chạy:** 2026-09-04
**Board/cổng dùng:** COM3 (USB Serial Device, VID:PID 0483:2010 — khớp
`engine/simulator_control.py`). Máy có 2 board tương tự cắm cùng lúc
(COM3, COM5) — chỉ dùng COM3 cho spike này.
**Scan tool dùng để gửi request thật:** scan tool thật của người dùng (tên
cụ thể không ghi lại), nối CAN-H/CAN-L vật lý vào board qua connector OBD-II
chuẩn (pin 6/14).
**File `.sim` dùng để test:** `2019 Hyundai Accent(HC) G 1.6 GDI_V0.15.sim`
(1067 dòng, file xe thật — **dùng file này thay cho fixture Audi bị thiếu**
nêu trong SPEC_SIMLANG_V2.md §10, vì cùng dạng thật, kích thước tương đương).

---

## Tóm tắt kết quả

| Câu hỏi (spec §10.1) | Trạng thái | Kết quả |
|---|---|---|
| 1. `readOBDMsgdata()` trả về gì | ✅ Trả lời được (qua reflection) | Trả về object `obdMsgData` có cấu trúc rõ ràng — xem §2 |
| 2. `SendMesg` tham số nghĩa là gì | ⚠️ Một phần | `SendMesg(Int32 TimeOutMs, Byte[] FullMsg, enum_obd_serial_msg_type)` — tham số đầu là **timeout (ms)**, KHÔNG phải "channel" như spec đoán. Định dạng `FullMsg` byte-for-byte chưa xác nhận chắc chắn (spec chỉ dùng lớp cao `ObdSimulator` nên chưa cần gọi `SendMesg` trực tiếp) |
| 3. Board tự lọc/tự trả lời khung khi không sim mode | ✅ Không — board im lặng hoàn toàn nếu không có DB nạp, không tự phản hồi gì |
| 4. Độ trễ vòng | ⚠️ Chưa đo chính xác (round-trip đơn khung THÀNH CÔNG nhưng không đo mili-giây cụ thể) |

**Kết luận tổng thể: KHÔNG THẤT BẠI, nhưng chưa hoàn toàn thành công.**
Kiến trúc simlang v2 (bypass `ObdSimulator`, tự làm dispatch bằng Python qua
`ClassDeviceComport`) là **khả thi về mặt API** — class tồn tại thật, mọi
phương thức cần thiết đều có. Nhưng:
- ✅ **Round-trip đơn khung (Single Frame) đã xác nhận hoạt động thật** —
  qua đường vòng dùng lớp cao `ObdSimulator` + `Database_LoadFile()`, KHÔNG
  phải qua `ClassDeviceComport` trực tiếp (xem §5, lý do kỹ thuật).
- ⚠️ **Round-trip đa khung (First Frame + Consecutive Frame) CHƯA xác nhận
  được** — thử với request `09 02` (đọc VIN, cần response 20 byte = FF + 2
  CF) nhiều lần, kể cả sau khi thêm `ProtocolConfig EnableAutoCANFC`, vẫn
  không thấy phản hồi trên scan tool. **Không kết luận đây là lỗi giao thức
  thật** — nhiều lần thử có vấn đề phối hợp thời điểm (script mở cửa sổ
  poll xong TRƯỚC khi người dùng kịp gửi từ scan tool), nên chưa loại trừ
  được khả năng đơn giản là chưa test đúng lúc. Cần lặp lại với thiết bị đo
  bus CAN (logic analyzer) để xác nhận chắc chắn khung FF có thực sự rời
  khỏi board hay không.

---

## 1. `ClassDeviceComport` — constructor thật khác spec

```csharp
public ClassDeviceComport(fVoidCallBackType fCallback)
```

**KHÔNG phải parameterless như `RealTransport.__init__` ban đầu giả định.**
`fVoidCallBackType` là delegate `Void Invoke()` — không tham số. Ý nghĩa
chính xác của callback này (báo "có dữ liệu mới" hay chỉ "trạng thái đổi")
**chưa xác nhận** — trong lúc test, callback KHÔNG BAO GIỜ fire (0 lần) dù
`SendMesg`/polling có hoạt động, kể cả khi dùng qua đường vòng `ObdSimulator`
(lớp cao không cho truy cập callback này trực tiếp).

Ví dụ tạo instance đúng cách:
```python
def on_callback():
    pass  # ý nghĩa thật chưa xác nhận — không fire trong test

cb = fVoidCallBackType(on_callback)
device = ClassDeviceComport(cb)
```

## 2. `readOBDMsgdata()` — trả về `obdMsgData`, các field xác nhận qua reflection

```
class obdMsgData:
    msgrawdatatype: enumOBDMsgRawDataType   # OBD_DATA_REQ | OBD_DATA_RES | OBD_DATA_MULTI_RES |
                                             # OBD_DATA_RES_5BPS | OBD_DATA_RES_WITHTIME | OBD_DATA_RES_NO_DATA
    addr: Int32
    protocol: enumprotocol                  # NO_MODE|VPW|PWM|KWP2000|KW1281|DWCAN|CCD|SCI|SWCAN|CAN_FD|J1708
    lendata: Int32
    data: List<T>                           # kiểu phần tử chưa xác nhận (nhiều khả năng byte)
    timestamp: Int64
    previoustimestamp: Int64
    msgtype: enumOBDMsgType                 # OBD_UNKNOW|OBD_REQ|OBD_RES|MSG_INFO|OBD_RES_NEG|OBD_REQ_FLOWCONTROL|MSG_INFO_VIN
    listTimeInterval: List<T>
```

Khi board đang chạy nhưng KHÔNG có traffic thật, `readOBDMsgdata()` trả về
`null` (Python thấy `None`) — đã xác nhận qua polling 5-20s nhiều lần.

Một lần thử gọi `SendMesg(100, <10 byte tự chế>, OBD_MSG_NORMAL)` rồi đọc
lại thấy `obdMsgData(addr=0, lendata=10, data=None)` — **không tin cậy
được**, khả năng cao là do định dạng `FullMsg` tôi tự đoán (2 byte CAN-ID +
PCI + payload) sai, KHÔNG kết luận gì từ kết quả này.

## 3. `SendMesg` — chữ ký thật

```csharp
Boolean SendMesg(Int32 TimeOutMs, Byte[] FullMsg, enum_obd_serial_msg_type e_obd_serial_msg_type)
```

`enum_obd_serial_msg_type`: `OBD_MSG_NORMAL | OBD_MSG_WAKEUP | OBD_MSG_FB`.

Tham số đầu (`1` trong ví dụ minh hoạ của spec) là **timeout tính bằng ms**,
KHÔNG phải "channel". Định dạng byte chính xác của `FullMsg` (có cần 2 byte
CAN-ID ở đầu không, hay engine tự thêm) **chưa xác nhận chắc chắn** — gọi
thử không lỗi (trả `True`) nhưng không kiểm chứng được nội dung nhận đúng.

## 4. `WriteConfigProtocol` cần `OBDInterface` ĐẦY ĐỦ, không phải object rỗng

```csharp
Boolean WriteConfigProtocol(OBDInterface obdinterface)
```

Object rỗng (chỉ set `protocol`/`baudrate`/`timingp2`/`timingp4`) →
**`WriteConfigProtocol` trả `False`** (từ chối, không throw). Phải set thêm
đầy đủ `dlckline`/`dlclline` (kiểu `structDLCProfile`: `dlcpin`, `voltage`,
`resistor`, `isinverted`) và `clsuartinfo` (kiểu `clsuartformat`: `databit`,
`parity`, `stopbit`) thì mới được chấp nhận (trả `True`). Ánh xạ từ
`<config sw>` của `.sim` sang các enum thật:

| `.sim` field | Enum/giá trị .NET thật |
|---|---|
| `Protocol = 29` | **KHÔNG dùng trực tiếp** — `enumprotocol` chỉ có 11 giá trị (0-10); dùng `enumprotocol.DWCAN` cho CAN (xác nhận đúng bug đã ghi trong HUONG_DAN_FILE_SIM.md §11b) |
| `PIN_KRX_CANH = 6` | `dlckline.dlcpin = enumDLCPinName.DLC_PIN6` |
| `PIN_KTX_CANH = 14` | `dlclline.dlcpin = enumDLCPinName.DLC_PIN14` |
| `VOLT_*_CANH = 3` | `enumVoltageLevel.LEVEL_12V` (thứ tự enum: FLOAT,5V,8V,12V) |
| `TYPE_*_CANH = 0` | `isinverted = False` |
| `DATABIT = 0` | `enumDataBit.D_8` |
| `PARITY = 0` | `enumParity.P_NONE` |
| `TBYTE` | `timingp4` |
| `TFRAME` | `timingp2` |
| (không có trong `.sim`) | `resistor = enumPUResitor.PU_NONE` (đoán, không có field `.sim` tương ứng) |
| (không có trong `.sim`) | `stopbit = enumstopbit.S_1` (đoán) |

Sau `WriteConfigProtocol` (True), gọi thêm `SetActiveProtocol(enumprotocol.DWCAN)`
rồi `startdevice()` → cả hai đều `True`.

## 5. ⭐ Round-trip THẬT: đơn khung hoạt động, đa khung chưa xác nhận

**Quan trọng: dùng đường vòng qua `ObdSimulator` (lớp cao), KHÔNG phải
`ClassDeviceComport` trực tiếp**, vì việc tự implement toàn bộ
`WriteConfigProtocol`/dispatch bằng `ClassDeviceComport` thuần chưa xong khi
hết thời gian test. Trình tự đã xác nhận hoạt động:

```python
sim = ObdSimulator(swversion, isEnableLogFile)
sim.OpenConnection("COM3")                       # -> True
sim.Database_LoadFile(path, True, True)          # -> True (xem §6 các lỗi thật gặp)
sim.StartDevice()                                # -> True
# engine tự xử lý request/response nội bộ từ đây, không cần gọi gì thêm
```

- **Request `01 00` (Mode 1, PID 00) tới `0x7DF`** → scan tool THẬT nhận
  được response đúng (`41 00 ...`) — **round-trip đơn khung xác nhận hoạt
  động end-to-end thật**, qua cả 2 lỗi runtime .NET đã fix (xem §7).
- **Request `09 02` (đọc VIN) tới `0x7DF`** → cần response 20 byte (First
  Frame + 2 Consecutive Frame, xem file `.sim` dòng 240-243, VIN
  `3KPC24A32KE059844`) — **KHÔNG thấy phản hồi**, thử nhiều lần kể cả sau
  khi thêm `ProtocolConfig EnableAutoCANFC` vào file. Giả thuyết
  `EnableAutoCANFC` được test và **không xác nhận là nguyên nhân** — cờ đó
  nhiều khả năng chỉ ảnh hưởng khi board NHẬN request đa khung (tự sinh Flow
  Control để nhắc bên gửi tiếp tục), không ảnh hưởng khi board GỬI response
  đa khung (lúc đó chính SCAN TOOL mới là bên phải gửi Flow Control lại cho
  board) — suy luận, chưa xác nhận bằng tài liệu/log cụ thể.
  **Không loại trừ được vấn đề phối hợp thời điểm test** (nhiều lần cửa sổ
  poll kết thúc trước khi kịp xác nhận scan tool đã gửi) — cần lặp lại có
  logic analyzer trên bus CAN để xác nhận chắc chắn.

## 6. Lỗi thật từ `getSimDB().getLogError()` khi load file xe thật

Load `2019 Hyundai Accent(HC) G 1.6 GDI_V0.15.sim` (1067 dòng, file thật)
qua `Database_LoadFile(path, True, True)` → `True` (file vẫn load được) NHƯNG
kèm 4 dòng lỗi/cảnh báo thật từ chính engine gốc:

```
ERROR_GENERAL::Reference Correct File :...sim.correct.sim
ERROR_DUPPLICATEREQ::000007A0  08  03 19 02 08 00 00 00 00
ERROR_WRONGFIRSTFRAMERESP::frame 141, req:000007E1 08 03 22 01 A3 00 00 00 00,
  Resp:00 00 07 E9 08 10 1C 62 01 A3 F8 00 00, Expected Len = 0x1C, Actual Len = 0x0D
ERROR_UNKNOW_RESPONSE::INFO_DATABASE = Res<4  000007DE  08  05 61 01 01 FF FF 00  NONE 0 0
```

- **`ERROR_GENERAL::Reference Correct File`** — xác nhận `isEnableAnalyze=True`
  (tham số thứ 3 của `Database_LoadFile`) thực sự kích hoạt cơ chế
  "CorrectFileDB" nhắc tới trong SPEC_SIMLANG_V2.md §12 — engine tham chiếu
  một file `.correct.sim` cùng tên (không tồn tại trong trường hợp này,
  nhưng không làm load thất bại).
- **`ERROR_DUPPLICATEREQ`** — xác nhận THẬT hành vi "request trùng bị vô
  hiệu hoá" đã ghi trong HUONG_DAN_FILE_SIM.md — xảy ra trên file xe thật,
  không chỉ lý thuyết.
- **`ERROR_WRONGFIRSTFRAMERESP`** — engine tự phát hiện được: độ dài khai
  trong First Frame (`0x1C` = 28) không khớp tổng số byte thực có trong các
  dòng Res tiếp theo của file (chỉ `0x0D` = 13) — đây là LỖI TÁC GIẢ file
  `.sim` gốc (thiếu dòng Consecutive Frame), KHÔNG phải bug engine — nhưng
  xác nhận engine CÓ validate độ dài FF/CF tổng, khác với những gì
  HUONG_DAN_FILE_SIM.md §11b nói validate ISO-TP protocol/DWCAN là code
  chết (hai việc validate khác nhau: đây là check độ dài, không phải check
  protocol enum).
- **`ERROR_UNKNOW_RESPONSE`** — một dòng `Res` không khớp được với `Req`
  nào (mồ côi) — xác nhận `group_exchanges()` trong `simfile.py` của
  simlang cần xử lý đúng ca này (đã có, xem `Res` mồ côi bị bỏ qua an toàn).

## 6b. Bonus: `CorrectFileDB` (isEnableAnalyze=True) XÁC NHẬN có sửa dữ liệu

SPEC_SIMLANG_V2.md §12 liệt kê "CorrectFileDB có sửa dữ liệu không" là điều
chưa biết. Xác nhận thật: **CÓ** — `Database_LoadFile(path, True, True)`
(tham số 3 = `isEnableAnalyze=True`) tự ghi ra một file MỚI cùng thư mục,
tên `<path>.correct.sim`, KHÔNG sửa file gốc tại chỗ. Trên file Hyundai
1067 dòng, file `.correct.sim` sinh ra chỉ còn **481 dòng** (~55% nhỏ hơn):
bỏ hết comment (`//...`), dòng trống, `SIZE_DATABASE`, và (nhiều khả năng)
các entry đã bị flag lỗi trong `getLogError()` (trùng request, response mồ
côi...) — chưa diff chi tiết từng dòng để xác nhận 100% quy tắc loại bỏ,
nhưng xu hướng rõ ràng là "dọn dẹp file, giữ lại phần load được sạch".

**Ý nghĩa cho `importer.py`/`simfile.py` của simlang:** nếu cần một phiên
bản "đã được engine xác nhận sạch" của file thật để so sánh/validate, có
thể load qua `Database_LoadFile(path, True, True)` rồi đọc lại
`<path>.correct.sim` — cách này dùng chính engine gốc làm oracle, độc lập
với `simfile.py` tự viết.

## 7. Hai lỗi runtime .NET PHẢI FIX để pythonnet host được DLL này

Đây là phát hiện **quan trọng nhất về mặt kỹ thuật triển khai** — không có
gì trong 2 file spec nhắc tới, và nếu không fix thì `RealTransport` sẽ luôn
crash ngay ở bước khởi tạo, dù mọi thứ khác đúng.

**Lỗi 1** — `TypeLoadException` khi gọi `ClassDeviceComport(cb)` với
pythonnet mặc định:
```
System.TypeLoadException: Could not load type 'System.ComponentModel.Component'
from assembly 'System.ComponentModel.Primitives'...
```
**Fix:** phải trỏ pythonnet dùng ĐÚNG `runtimeconfig.json` của chính app
(`OBDSimulation_CLI.runtimeconfig.json`) thay vì để pythonnet tự bootstrap
runtime mặc định:
```python
import pythonnet
pythonnet.load("coreclr", runtime_config=str(runtimeconfig_path))
import clr  # PHẢI sau load(), không phải trước
```

**Lỗi 2** — sau khi fix lỗi 1, gặp tiếp:
```
System.PlatformNotSupportedException: System.IO.Ports is currently only
supported on Windows.
```
(dù đang chạy trên Windows thật — đây là do bản `System.IO.Ports.dll` được
nạp là bản "reference stub" RID-agnostic, không phải bản Windows thật, vì
`clr.AddReference()` không đi qua cơ chế resolve theo `deps.json`/RID như
khi chạy qua `dotnet exec`/apphost thật).
**Fix:** ép nạp tay bản Windows thật TRƯỚC khi nạp `SimulatorInterface.dll`:
```python
clr.AddReference(str(base / "runtimes" / "win" / "lib" / "net8.0" / "System.IO.Ports.dll"))
clr.AddReference(str(base / "SimulatorInterface.dll"))
```

Cả 2 fix này đã áp dụng vào `RealTransport` trong `runtime/transport.py`.

---

## Kết luận

- [x] M0 **THÀNH CÔNG MỘT PHẦN** — API thật đã xác nhận đầy đủ qua
      reflection, 2 lỗi runtime .NET đã tìm ra cách fix, round-trip
      **đơn khung** đã xác nhận hoạt động thật end-to-end qua scan tool
      thật (dùng đường vòng `ObdSimulator`, chưa qua `ClassDeviceComport`
      thuần trực tiếp).
- [ ] **CHƯA XÁC NHẬN đầy đủ** — round-trip **đa khung** (First
      Frame/Consecutive Frame) chưa thấy hoạt động trong các lần thử, lý do
      thật sự (giao thức, config, hay chỉ do phối hợp thời điểm test chưa
      khớp) chưa chốt được. Cần lặp lại với logic analyzer trên bus CAN.
      Việc dùng `ClassDeviceComport` THUẦN (không qua `ObdSimulator`) —
      đúng kiến trúc simlang v2 muốn — cũng CHƯA được test round-trip thật
      (chỉ mới xác nhận `Open`/`WriteConfigProtocol`/`startdevice` chạy
      không lỗi, chưa xác nhận `SendMesg`/`readOBDMsgdata` hoạt động đúng
      với traffic thật qua đường này).

**Việc tiếp theo trước khi implement `RealTransport` đầy đủ:**
1. Xác nhận round-trip đa khung bằng logic analyzer (loại trừ vấn đề
   phối hợp thời điểm test).
2. Test `ClassDeviceComport` thuần (không qua `ObdSimulator`) với
   `SendMesg`/`readOBDMsgdata` trên traffic thật, để xác nhận định dạng
   byte chính xác của `FullMsg`/`obdMsgData.data`.
3. Xác nhận ý nghĩa thật của callback `fVoidCallBackType` (chưa fire lần
   nào trong mọi lần test).
