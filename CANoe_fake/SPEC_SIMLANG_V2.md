# SPEC — `simlang`: runtime cú pháp CAPL trên OBD Simulator

> **Dành cho Claude Code.** Đây là đặc tả xây dựng.
> Tham chiếu bắt buộc: `HUONG_DAN_FILE_SIM.md` — định dạng `.sim` và các bug của engine.
>
> **Tài liệu này thay thế `SPEC_SIMLANG.md` (bản transpiler → `.sim`).**
> Bản cũ chỉ còn giá trị tham khảo về định dạng đích.

---

## 1. Mục tiêu

Người viết test dùng **cú pháp giống CAPL**. Công cụ transpile ra Python, và
Python điều khiển **trực tiếp** phần cứng qua `ClassDeviceComport`.

```
file .can  (cú pháp CAPL)
      ↓  Lark parser
    AST
      ↓  codegen
mã Python + thư viện runtime
      ↓  pythonnet
ClassDeviceComport  →  board  →  scan tool
```

**Người viết test không bao giờ thấy Python.**

### Vì sao không đi đường `.sim`

Ba ca dưới đây định dạng `.sim` **không diễn đạt được**, và cả ba đều là nhu cầu
thường xuyên chứ không phải ngoại lệ:

| Ca | Vì sao `.sim` bó tay |
|---|---|
| `7F xx 78` (responsePending) | ECU tự gửi thêm mà tool không hỏi lại; `.sim` chỉ ánh xạ 1 request → 1 response |
| Đổi DTC sau `04` | `Q--` chỉ nhìn lại **một** bước; tool chèn hàng chục lệnh giữa `04` và `03` |
| Live data theo thời gian | `l1` xoay theo **số lần gọi**, không theo đồng hồ; không tương quan giữa các PID |

### Phân vai với team reverse

Team reverse **giữ nguyên** quy trình `.sim` hiện tại. Không bắt họ đổi.

| Thứ | Ai lo |
|---|---|
| Hàng nghìn PID/DTC tĩnh, wildcard, đa khung | file `.sim` — nạp làm **nền dữ liệu** |
| `78`, trạng thái, live data động | handler CAPL |

Runtime nạp `.sim` làm bảng tĩnh, handler CAPL **phủ đè** lên request nào cần
logic. Request có handler → handler trả lời. Không có → tra bảng tĩnh.

---

## 2. Phạm vi

### Trong phạm vi
- Grammar CAPL + parser + codegen ra Python
- Thư viện runtime: dispatch, ISO-TP, timer, biến trạng thái
- Binding `ClassDeviceComport` qua pythonnet
- Importer `.sim` → `.can` (§8)

### ⛔ Ngoài phạm vi — KHÔNG được xây
- **Sinh ngược ra `.sim`.** Team reverse dùng công cụ của họ; không còn ai tiêu thụ output đó.
- Interpreter cho CAPL. Chỉ transpile ra Python.
- Backend điều khiển tool (JSON) — giai đoạn sau, chưa có schema.
- Đi qua `ObdSimulator` / `classHandleReceiveData` để so khớp. Runtime tự so khớp.

---

## 3. Stack

| Thành phần | Lựa chọn | Ghi chú |
|---|---|---|
| Python | 3.11+ | |
| Parser | **Lark** | EBNF, lỗi có số dòng |
| Engine binding | **pythonnet** (`clr`) | gọi `SimulatorInterface.dll` |
| Đồng thời | **asyncio, đơn luồng** | xem §6.3 — quyết định kiến trúc, không đổi |
| Test | pytest + pytest-asyncio | |
| CLI | typer | |

---

## 4. Cấu trúc repo

```
simlang/
├── grammar/simlang.lark
├── src/simlang/
│   ├── parser.py           # Lark → AST
│   ├── ast_nodes.py
│   ├── codegen.py          # AST → Python (có # line map)
│   ├── runtime/
│   │   ├── dispatch.py     # bảng handler + tra bảng tĩnh
│   │   ├── isotp.py        # đóng/mở khung ISO-TP
│   │   ├── timers.py
│   │   ├── builtins.py     # output(), write(), setTimer()...
│   │   └── transport.py    # pythonnet ↔ ClassDeviceComport (§7)
│   ├── simfile.py          # parser .sim (§8)
│   ├── importer.py         # .sim → .can
│   └── cli.py
├── tests/
│   ├── fixtures/2008_Audi_A6_V6__3_2L_V0_17_4.sim
│   └── ...
└── examples/
```

---

## 5. Ngôn ngữ `.can`

### 5.1 Ví dụ đầy đủ — ba ca khó

```c
variables {
    int  dtcCleared = 0;
    int  rpm = 800;
    msTimer rpmTimer;
}

on start {
    loadStatic("2008_Audi_A6.sim");
    setTimer(rpmTimer, 100);
}

// responsePending
on request 0x7E0 service 0x31 {
    output(0x7F, 0x31, 0x78);
    delay(2000);
    output(0x7F, 0x31, 0x78);
    delay(2000);
    output(0x71, 0x01, 0x02, 0x03);
}

// trạng thái sau erase
on request 0x7DF service 0x04 {
    dtcCleared = 1;
    output(0x44);
}

on request 0x7DF service 0x03 {
    if (dtcCleared)
        output(0x43, 0x00);
    else
        output(0x43, 0x02, 0x01, 0x33, 0x01, 0x71);
}

// live data theo thời gian
on timer rpmTimer {
    rpm = 800 + 1100 * sin(elapsed() / 3.0);
    setTimer(rpmTimer, 100);
}

on request 0x7DF service 0x01 pid 0x0C {
    output(0x41, 0x0C, (rpm * 4) >> 8, (rpm * 4) & 0xFF);
}
```

### 5.2 Khối `variables`

Kiểu: `int`, `long`, `float`, `double`, `char`, `byte[]`, `msTimer`, `char[]`.
Khai báo có thể có giá trị khởi tạo. Phạm vi: module-level.

### 5.3 Event handler

| Cú pháp | Kích hoạt khi |
|---|---|
| `on start { }` | runtime khởi động, trước khi mở cổng |
| `on stop { }` | runtime dừng |
| `on request <canid> service <sv> { }` | nhận request khớp CAN ID + service |
| `on request <canid> service <sv> pid <p> { }` | thêm điều kiện PID |
| `on request <canid> service <sv> data <bytes> { }` | khớp thêm payload, hỗ trợ `xx` |
| `on timer <name> { }` | timer hết hạn |
| `on message <canid> { }` | khung thô, trước cả tầng ISO-TP |

**Độ ưu tiên dispatch** (cụ thể → tổng quát):
`data` > `pid` > `service` > bảng tĩnh `.sim`.
Handler khớp đầu tiên thắng; nếu không handler nào khớp thì tra `.sim`.

### 5.4 Hàm dựng sẵn

| Hàm | Ý nghĩa |
|---|---|
| `output(b0, b1, ...)` | gửi response — **tự đóng khung ISO-TP** |
| `outputRaw(canid, b0..b7)` | gửi một khung thô, không đóng gói |
| `delay(ms)` | chờ — **không chặn** vòng lặp (§6.3) |
| `setTimer(t, ms)` / `cancelTimer(t)` | timer |
| `elapsed()` | giây (float) từ lúc `on start` |
| `write(fmt, ...)` | ghi log ra console |
| `loadStatic(path)` | nạp file `.sim` làm bảng nền |
| `sin`, `cos`, `abs`, `min`, `max`, `random` | toán học |

### 5.5 Câu lệnh

`if` / `else`, `while`, `for`, `switch` / `case`, gán, biểu thức số học và bit
(`+ - * / % << >> & | ^ ~`), so sánh, `&&` `||` `!`.

Số hex `0x7E8`, số thập phân, chuỗi `"..."` (mã hóa ASCII khi dùng trong `output`).

Chú thích `//` và `/* */`.

### 5.6 Khác biệt có chủ ý so với CAPL của Vector

- `on request` là **mở rộng riêng** — CAPL gốc chỉ có `on message` ở mức khung
- Không hỗ trợ `testcase`, `on key`, `on envVar`, CAN database (`.dbc`)
- Không tương thích nhị phân với CANoe, và **không được gọi sản phẩm là "CAPL"**
  hay quảng cáo tương thích Vector (rủi ro nhãn hiệu)

---

## 6. Runtime

### 6.1 Vòng đời

```
parse .can → sinh Python → import
→ chạy on start
→ mở cổng, cấu hình protocol, startdevice
→ vòng lặp: readOBDMsgdata → ghép ISO-TP → dispatch → output
→ Ctrl-C → on stop → stopdevice, Close
```

### 6.2 Dispatch

```python
frame = transport.read()          # khung thô
msg   = isotp.feed(frame)         # None nếu chưa đủ khung
if msg:
    h = dispatch.find(msg)        # theo độ ưu tiên §5.3
    if h: await h(msg)
    else: static_table.respond(msg)
```

### 6.3 ⭐ Đồng thời — quyết định kiến trúc

**asyncio đơn luồng.** Mọi handler sinh ra là `async def`. `delay(ms)` dịch
thành `await asyncio.sleep(ms/1000)`.

Lý do bắt buộc: ca `78` cần chờ 2 giây giữa các lần `output()`. Nếu `delay`
chặn luồng, simulator **điếc 4 giây** và bỏ lỡ khung đến — đúng lỗi mà
`Utilities.DelayMs` của engine gốc mắc phải.

Đơn luồng nên biến chia sẻ **không cần khóa**, khớp với mô hình tư duy của CAPL.

Vòng lặp đọc là một task; mỗi lần gọi handler là một task. `readOBDMsgdata`
là lời gọi chặn của .NET → chạy trong `run_in_executor`.

### 6.4 ISO-TP (`isotp.py`)

Phần nặng nhất. Phải làm cả hai chiều.

**Gửi:** payload ≤ 7 byte → SF `0{len}`. Dài hơn → FF `1{len:03X}` + 6 byte,
chờ Flow Control, rồi CF `2{seq}` với seq quay vòng `0x20`→`0x2F`→`0x20`.
Tôn trọng STmin và block size từ FC. Luôn pad đủ 8 byte, DLC `08`.

**Nhận:** ghép SF/FF/CF, tự gửi FC (`30 00 00`), timeout N_Cr.

Độ dài FF tính đúng: `((b0 & 0x0F) << 8) | b1`
(engine gốc dùng `& 0xF00` — luôn ra 0, xem `HUONG_DAN_FILE_SIM.md` §11c).

---

## 7. Binding phần cứng (`transport.py`)

Dùng **`ClassDeviceComport`** (đã xác nhận `public`), **không** qua `ObdSimulator`.

```python
import clr
clr.AddReference(r"path/SimulatorInterface.dll")
from SimulatorInterface import ClassDeviceComport
```

Các hàm public dùng tới:

| Hàm | Dùng để |
|---|---|
| `Open` / `DeviceOpenConnection` | mở cổng serial |
| `WriteConfigProtocol` | cấu hình CAN |
| `SetActiveProtocol` | chọn protocol |
| `startdevice` / `stopdevice` | điều khiển board |
| `readOBDMsgdata` | đọc khung nhận được |
| `SendMesg` | gửi khung |
| `clearOBDMsgdata` | xóa buffer |

**Linux:** truyền thẳng tên cổng (`/dev/ttyACM0`). **Không gọi
`Device_GetListPort`** — hàm đó dùng `System.Management`, chỉ có runtime Windows.
`System.IO.Ports` có sẵn native cho `linux-x64` và `linux-arm64`.

---

## 8. Importer `.sim` → `.can`

**Không cần bảo toàn thứ tự.** Đây là công cụ **trích xuất dữ liệu**, không
phải roundtrip. Không có mốc so sánh bit-for-bit.

Quy tắc:

1. Mỗi cặp request/response tĩnh → một khối `on request`
2. Ghép các khung `Res` đa khung lại thành **payload logic**, bỏ PCI —
   `output()` sẽ tự đóng khung lại
3. `xx` giữ nguyên trong mệnh đề `data`
4. `//NOTE:` → chú thích `//` phía trên khối
5. Khối `<config sw>` → `on start` với `loadStatic()` hoặc lời gọi cấu hình

**Xử lý các trường hợp đặc biệt** — không cố dịch cho đúng, chỉ đánh dấu:

| Gặp | Sinh ra |
|---|---|
| `Q--` | khối `on request` bình thường + `// TODO: Q-- — viết lại thành handler có trạng thái` |
| `l1` | `// TODO: l1 (xoay vòng) — viết lại bằng biến trạng thái` kèm danh sách response dạng comment |
| Request trùng nhau | sinh cả hai + `// TODO: trùng request, cần logic phân biệt` |
| `^` (byte engine tự tính) | giữ nguyên + `// TODO: unknown token` |

Người dùng sẽ tự viết lại các ca này thành handler có trạng thái — đó là mục
đích của công cụ mới.

**Không tự ý bỏ ký hiệu chưa hiểu.** Giữ lại và đánh dấu `// TODO`.

---

## 9. CLI

```bash
simlang run    test.can --port COM3        # transpile + chạy
simlang build  test.can -o test.py         # chỉ sinh Python (debug)
simlang check  test.can                    # parse + validate
simlang import old.sim -o old.can          # importer §8
simlang fmt    test.can
```

---

## 10. Lộ trình

| Mốc | Nội dung | Tiêu chí hoàn thành |
|---|---|---|
| **M0** ⚠ | **Spike raw transceiver** (1 tuần, TRƯỚC MỌI THỨ) | §10.1 |
| **M1** | `simfile.py` — parser `.sim` | Đọc file Audi 1306 dòng, không mất dữ liệu |
| **M2** | Grammar + parser + AST | Parse được toàn bộ §5, lỗi có số dòng |
| **M3** | `isotp.py` + transport | Gửi/nhận đúng payload 1–300 byte trên board thật |
| **M4** | Codegen + runtime + dispatch | Ví dụ §5.1 chạy được, cả ba ca khó |
| **M5** | Importer §8 | Convert file Audi, đánh dấu đủ TODO |
| **M6** | Chạy CI trên Linux runner | pytest xanh, có board cắm vào |

### 10.1 M0 — spike, làm trước tiên

**Chưa viết ISO-TP, chưa viết parser.** Chỉ chứng minh đường raw thông:

```
Open → WriteConfigProtocol → startdevice
→ vòng lặp readOBDMsgdata
→ thấy request 09 02 thì SendMesg trả một khung
→ scan tool có nhận đúng không?
```

Phải trả lời:
1. `readOBDMsgdata` trả về **cấu trúc gì** (byte array? object? chuỗi?)
2. `SendMesg(1, data, OBD_MSG_NORMAL)` — tham số đầu `1` nghĩa là gì? Định dạng `data`?
3. Board có **tự lọc hoặc tự trả lời** khung nào không khi không ở chế độ sim?
4. Độ trễ vòng: từ lúc khung tới board đến lúc `readOBDMsgdata` thấy nó?

Ghi kết quả vào `docs/M0_findings.md`.

**Nếu M0 thất bại** — `SendMesg` cần header không giải mã được, hoặc board tự
lọc khung — thì toàn bộ kiến trúc này phải tính lại. Đó là lý do M0 đứng trước.

---

## 11. Test

**Không cần phần cứng cho phần lớn test.** `transport.py` phải có
implementation giả (`FakeTransport`) để pytest chạy trên CI runner thường.

1. **ISO-TP** — payload 1..4095 byte, PCI đúng, seq quay vòng `0x2F`→`0x20`, độ dài FF
2. **Dispatch** — độ ưu tiên `data` > `pid` > `service` > tĩnh
3. **Golden** — mỗi cú pháp §5 có `.can` và `.py` kỳ vọng
4. **Ba ca khó** — `78`, erase-đổi-DTC, live data — chạy trên `FakeTransport`,
   kiểm tra chuỗi khung gửi ra và thời điểm
5. **`simfile.py`** — parse file Audi thật, đếm đủ 1306 dòng, không nuốt dòng nào
6. **End-to-end** — chỉ mốc M6, cần board thật

---

## 12. Điều chưa biết

Không được giả định trong code:

| Điều chưa biết | Cách xử lý |
|---|---|
| Định dạng `readOBDMsgdata` / `SendMesg` | **M0 phải trả lời trước khi viết `transport.py`** |
| Con số sau `Req>` / `Res<` trong `.sim` (1,2,3,4,5,6,7,8,14) | Importer **giữ nguyên** làm comment, không diễn giải |
| `^` (byte engine tự tính) | Giữ nguyên + `// TODO` |
| Board có tự gửi Flow Control không | M0 câu 3; nếu có, cần `DisableAutoCANFC` |
| STmin thực tế board đáp ứng được | Đo ở M3 |

**Nguyên tắc chung:** gặp thứ chưa hiểu thì **giữ nguyên và đánh dấu**, đừng
đoán rồi sinh ra dữ liệu sai.
