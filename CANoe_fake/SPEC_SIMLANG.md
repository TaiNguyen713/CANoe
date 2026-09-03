# SPEC — `simlang`: DSL cú pháp CAPL cho OBD Simulator

> **Tài liệu này dành cho Claude Code.** Đây là đặc tả xây dựng, không phải hướng dẫn sử dụng.
> Tham chiếu bắt buộc: `HUONG_DAN_FILE_SIM.md` (định dạng đích và các bug của engine).

---

## 1. Mục tiêu

Xây một **transpiler**: người dùng viết test bằng cú pháp giống CAPL, công cụ
sinh ra file `.sim` cho engine `SimulatorInterface.dll` v2.3.

**Không xây engine runtime.** Không viết interpreter. Chỉ parse → validate → sinh text.

### ⛔ Ngoài phạm vi giai đoạn 1 — KHÔNG được tự ý xây

- **Runtime state backend** (theo dõi trạng thái xuyên phiên bằng Python callback)
- Cú pháp `state`, `on message`, biến toàn cục, hoặc bất kỳ dạng lưu trạng thái nào
  ngoài `Q--` và `l1`
- Backend thứ hai cho phần điều khiển tool (JSON)

Những thứ này thuộc giai đoạn 2 (§12) và **phụ thuộc vào kết quả thử nghiệm M0**.
Nếu gặp một nhu cầu mà `.sim` không diễn đạt được, **báo lỗi rõ ràng cho người
dùng** — đừng thiết kế cú pháp mới để lấp. Sinh ra cú pháp mà backend không thực
thi nổi là lỗi nghiêm trọng hơn là không hỗ trợ.

### Vấn đề đang giải quyết

File `.sim` hiện tại là bảng phẳng phân cách bằng TAB, mỗi dòng phải gõ đủ 8 byte
kể cả padding, và khung ISO-TP phải tự tay tính PCI. Một file cho một xe có
~1300 dòng. Viết tay chậm và sai sót nhiều.

### Ba việc công cụ phải làm tốt hơn con người

1. **Tự động chia khung ISO-TP** — người viết payload logic, công cụ sinh `10 xx` / `21` / `22`
2. **Validate** — engine có validator nhưng là code chết (xem §6)
3. **Sinh từ nguồn khác** — Excel DB, log đã bắt

---

## 2. Stack

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Ngôn ngữ | Python 3.11+ | khớp hệ sinh thái tool hiện có |
| Parser | **Lark** (`lark-parser`) | grammar khai báo, EBNF, lỗi rõ ràng |
| Điều khiển engine | **pythonnet** (`clr`) | gọi trực tiếp `SimulatorInterface.dll` |
| Test | pytest | |
| CLI | argparse hoặc typer | |

Không dùng ANTLR (nặng, cần Java). Không tự viết lexer bằng regex.

---

## 3. Cấu trúc repo

```
simlang/
├── grammar/
│   └── simlang.lark          # định nghĩa grammar
├── src/simlang/
│   ├── parser.py             # Lark → AST
│   ├── ast_nodes.py          # dataclass cho từng node
│   ├── validator.py          # kiểm tra ngữ nghĩa (§6)
│   ├── isotp.py              # chia khung ISO-TP
│   ├── codegen.py            # AST → .sim
│   ├── decompile.py          # .sim → DSL (chiều ngược)
│   ├── runtime.py            # pythonnet wrapper (§8)
│   └── cli.py
├── tests/
│   ├── fixtures/*.sim        # file thật để test roundtrip
│   └── test_*.py
└── examples/
```

---

## 4. Cú pháp DSL

### 4.1 Khối config

```
config {
    protocol  = 29;          // ghi thẳng vào <config sw> Protocol
    baudrate  = 500000;
    tframe    = 5;           // → timingp2, delay mặc định mọi response
    tbyte     = 3;           // → timingp4
    autocanfc = true;        // → ProtocolConfig EnableAutoCANFC
}
```

### 4.2 Khai báo ECU

```
ecu ABS {
    rx = 0x7E0;    // địa chỉ ECU nhận request
    tx = 0x7E8;    // địa chỉ ECU gửi response
}

ecu ENGINE { rx = 0x7DF; tx = 0x7E8; }
```

### 4.3 Request / response cơ bản

```
on request ABS: 22 F1 90 {
    respond 62 F1 90 "WAUAH74F58NO76944";
}
```

- Payload là chuỗi byte hex, hoặc string literal (mã hóa ASCII)
- Công cụ **tự thêm PCI, tự chia khung, tự pad `00`**
- Sinh ra nhiều dòng `Res<` / `Res>` tùy độ dài

### 4.4 Wildcard

```
on request ENGINE: 09 02 xx xx {     // xx = don't care
    respond 49 02 01 "WAUAH74F58NO76944";
}
```

### 4.5 Delay và repeat

```
on request ABS: 01 05 {
    delay 500ms;             // → t500 trên khung ĐẦU TIÊN
    respond 41 05 7B;
}

on request ABS: 01 0D {
    repeat 3;                // → r3
    respond 41 0D 50;
}
```

**Quy tắc bắt buộc trong codegen:** `delay` chỉ đặt lên khung đầu của response
đa khung. Các khung sau để trường `[1]` rỗng. (Lý do: §5 bảng ánh xạ.)

### 4.6 Negative response

```
on request ABS: 31 01 02 03 {
    nrc 0x33;                // → 7F 31 33
}
```

### 4.7 Response xoay vòng

```
on request ENGINE: 01 0C {
    cycle {
        respond 41 0C 1A F8;
        respond 41 0C 1B 40;
        respond 41 0C 1C 88;
    }
}
```
→ sinh `l1` ở đầu trường dữ liệu của response đầu tiên.

### 4.8 Chuỗi có trạng thái ⭐

```
sequence unlock_and_routine {
    on request ABS: 10 03      { respond 50 03 00 32 01 F4; }
    on request ABS: 27 03      { respond 67 03 12 34 56 78; }
    on request ABS: 27 04 xx xx xx xx { respond 67 04; }
    on request ABS: 31 01 02 03 { respond 71 01 02 03; }
}
```

**Codegen:** entry **đầu tiên** trong `sequence` sinh bình thường; **mọi entry
sau** sinh với tiền tố `Q--` ở đầu trường dữ liệu.

### ⚠ Giới hạn đã kiểm chứng thực tế: `Q--` chỉ nhìn lại MỘT bước

Thử nghiệm trên thiết bị thật cho thấy `Q--` khớp theo **request ngay liền trước**,
không phải theo trạng thái tích lũy của phiên. Nếu tool chèn bất kỳ lệnh nào vào
giữa (tester present `3E`, đọc trạng thái, đọc PID khác), chuỗi **đứt** và entry
`Q--` không khớp.

**Dùng được:** chuỗi ngắn, liền mạch, không bị xen giữa —
security access (`27 01` → `27 02`), request → flow control, multi-frame.

**KHÔNG dùng được:** trạng thái tồn tại xuyên suốt phiên. Ví dụ điển hình là
`03` (đọc DTC) → `04` (xóa) → `03` (đọc lại, phải rỗng): tool thường gửi hàng
chục lệnh giữa `04` và `03` tiếp theo.

`l1` cũng không thay thế được: nó xoay vòng theo **số lần gọi**, không theo việc
`04` đã xảy ra hay chưa.

Validator phải cảnh báo (`W006`) khi một `sequence` có nhiều hơn 3 entry hoặc
chứa các service không liên quan trực tiếp với nhau — đó là dấu hiệu người dùng
đang cố dùng `Q--` cho trạng thái xuyên phiên.

Đây là cách duy nhất **trong giai đoạn 1** để khai báo cùng một request nhiều lần với response khác nhau —
không có `Q--` thì entry trùng bị engine vô hiệu hóa im lặng.

### 4.9 Broadcast

```
broadcast ENGINE every 100ms repeat 5 {
    send 22 F1 90 00;
}
```
→ `INFO_DATABASE = Broadcast` + `t100` + `r5`

### 4.10 Chú thích

```
// bị bỏ khi sinh file
note "Odometer 40240 km";     // → //NOTE: Odometer 40240 km (engine giữ lại)
```

---

## 5. Bảng ánh xạ codegen

Mỗi dòng sinh ra **luôn có đúng 7 trường, 6 TAB**.

```
INFO_DATABASE = {tag}\t{delay}\t{repeat}\t{prefix}{canid} {dlc} {8 bytes}\t{cs}\t{poly}\t0
```

| DSL | Trường | Giá trị sinh ra |
|---|---|---|
| `on request` | `[0]` | `INFO_DATABASE = Req>1` |
| `respond` đơn khung | `[0]` | `INFO_DATABASE = Res<1` |
| `respond` đa khung | `[0]` | `INFO_DATABASE = Res>1` |
| `broadcast` | `[0]` | `INFO_DATABASE = Broadcast` |
| `delay 500ms` | `[1]` | `t500` — **bỏ qua nếu < 3ms** (ngưỡng engine) |
| không có `delay` | `[1]` | rỗng |
| `repeat n` (n≥2) | `[2]` | `r{n}` |
| `repeat 1` / không có | `[2]` | rỗng (engine coi <2 là không lặp) |
| trong `sequence`, không phải entry đầu | `[3]` | tiền tố `Q-- ` |
| `cycle`, response đầu | `[3]` | tiền tố `l1 ` |
| mặc định | `[4]`,`[5]`,`[6]` | `NONE`, `0`, `0` |

Thứ tự tiền tố khi có cả hai: `Q-- l1 <canid> ...`

### Chia khung ISO-TP (`isotp.py`)

| Độ dài payload | Sinh ra |
|---|---|
| ≤ 7 byte | 1 khung: `0{len} {payload} {pad 00}` |
| > 7 byte | FF: `1{len:03X} {6 byte đầu}`, rồi CF: `2{seq:01X} {7 byte}`, seq quay vòng 0→F |

Luôn pad đủ 8 byte dữ liệu. DLC luôn `08`.

Khi payload > 7 byte, phải sinh thêm dòng Flow Control cho phía tool:
```
INFO_DATABASE = Req>1\t\t\tQ-- {tester_addr} 08 30 00 00 00 00 00 00 00\tNONE\t0\t0
```
(trừ khi `autocanfc = true`, khi đó engine tự xử lý — cần kiểm chứng)

---

## 6. Validator — phần tạo giá trị lớn nhất

Engine **có** validator nhưng nó không bao giờ chạy: điều kiện
`dbProtocol == enumprotocol.DWCAN` không bao giờ đúng vì file dùng đánh số của
`enumOBDProtocol`. Công cụ phải tự làm.

### Lỗi (chặn sinh file)

| Mã | Kiểm tra |
|---|---|
| `E001` | Dòng sinh ra không đúng 7 trường |
| `E002` | Request trùng nhau mà không nằm trong `sequence` (engine sẽ vô hiệu hóa im lặng) |
| `E003` | `Q--` không ở đầu trường dữ liệu (engine cắt cứng 3 ký tự → mất dữ liệu) |
| `E004` | Độ dài FF không khớp tổng độ dài CF — tính đúng: `((b0 & 0x0F) << 8) \| b1` |
| `E005` | CAN ID không hợp lệ / ECU chưa khai báo |
| `E006` | Payload vượt 4095 byte (giới hạn ISO-TP) |

### Cảnh báo

| Mã | Kiểm tra |
|---|---|
| `W001` | `delay` đặt trên khung không phải khung đầu → phá STmin |
| `W002` | `delay` 1–2ms → engine bỏ qua (ngưỡng `> 2`) |
| `W003` | `repeat 1` → không có tác dụng |
| `W004` | `delay` > 1000ms → `Utilities.DelayMs` chặn luồng, có thể mất khung |
| `W005` | `sequence` chỉ có 1 entry → `Q--` không cần thiết |
| `W006` | `sequence` > 3 entry, hoặc chứa service không liên quan liền kề → `Q--` chỉ nhìn lại 1 bước, chuỗi sẽ đứt khi tool chèn lệnh khác (xem §4.8) |

---

## 7. CLI

```bash
simlang build  input.sl -o output.sim       # transpile
simlang check  input.sl                     # chỉ validate
simlang decompile input.sim -o output.sl    # chiều ngược
simlang run    input.sl --port COM3         # build + nạp + chạy (§8)
simlang fmt    input.sl                     # format
```

**`decompile` là bắt buộc, không phải tùy chọn.** Team đã có file `.sim` cho
nhiều xe. Không có chiều ngược thì không ai chuyển sang dùng công cụ.

---

## 8. Runtime wrapper (`runtime.py`)

Bọc `SimulatorInterface.dll` qua pythonnet. Trình tự theo comment trong
`SimulatorApi`:

```python
import clr
clr.AddReference(r"path/to/SimulatorInterface.dll")
from SimulatorInterface import ObdSimulator

class Simulator:
    def __init__(self, dll_dir: str): ...
    def open(self, port: str) -> bool          # OpenConnection
    def load(self, sim_path: str) -> bool      # Database_LoadFile(path, True, True)
    def start(self) -> bool                    # StartDevice
    def stop(self) -> bool                     # StopDevice
    def close(self) -> None                    # Close
    def errors(self) -> list[str]              # getSimDB().getLogError()  ← LUÔN gọi sau load
    def update_response(self, ...) -> bool     # getSimDB().OBDDB_UpdateRespData
```

**Bắt buộc:** sau mỗi `load()` phải gọi `errors()` và in ra. `Database_LoadFile`
trả `False` với lỗi mơ hồ; danh sách lỗi thật nằm trong `getLogError()`.

**Ghi chú kiến trúc:** logic so khớp chạy trên PC, board chỉ là bộ thu phát. Nên
`OBDDB_UpdateRespData` có hiệu lực ngay, không cần nạp lại file. Tận dụng điều
này cho chế độ interactive sau này.

**Linux:** `System.IO.Ports` có native runtime cho `linux-x64` / `linux-arm64`.
Truyền thẳng tên cổng (`/dev/ttyACM0`), **không gọi `Device_GetListPort`** — hàm
đó dùng `System.Management`, chỉ có trên Windows.

---

## 9. Lộ trình

| Mốc | Nội dung | Tiêu chí hoàn thành |
|---|---|---|
| **M0** | **Thử nghiệm callback** (nửa ngày, làm TRƯỚC mọi thứ) | Trả lời được 3 câu hỏi §9.1 |
| **M1** | Grammar + parser + AST | Parse được mọi cú pháp §4, lỗi có số dòng |
| **M2** | `isotp.py` + codegen cơ bản | Sinh đúng file cho request/response đơn giản |
| **M3** | **Roundtrip** | `decompile` file Audi thật → `build` lại → khác biệt chỉ ở khoảng trắng |
| **M4** | Validator §6 | Bắt được cả 6 lỗi và 5 cảnh báo, có test case cho từng mã |
| **M5** | `runtime.py` + `simlang run` | Nạp và chạy thật trên COM, in log lỗi |
| **M6** | `sequence` / `cycle` / `broadcast` | Kiểm chứng `Q--` và `l1` chạy trên thiết bị thật |

**M3 là mốc quan trọng nhất.** Roundtrip trên file thật 1300 dòng chứng minh
grammar phủ đủ và codegen chính xác. Làm M3 trước M4.

### 9.1 M0 — thử nghiệm callback (chuẩn bị cho giai đoạn 2)

Viết một script Python ngắn qua pythonnet, đăng ký
`SimulatorApi.setCallbackUpdateConsoleText`, chạy một phiên chẩn đoán thật,
in mọi thứ callback trả về. **Không xây gì thêm.**

Ba câu hỏi cần trả lời:

1. Callback trả **byte thô** hay **chuỗi đã format cho UI**? (Tên hàm gợi ý cái sau)
2. Bản tin có bị **gom lô** không? (`setCallbackUpdateConsoleBuff` nhận mảng —
   có thể engine gom nhiều bản tin trước khi bắn)
3. **Độ trễ** từ lúc khung tới lúc callback chạy là bao nhiêu?

Kết quả quyết định giai đoạn 2 khả thi tới đâu và tốn bao nhiêu. Ghi câu trả lời
vào `docs/M0_callback_findings.md`.

**M0 không chặn M1–M6.** Nó chạy song song và chỉ phục vụ việc lập kế hoạch
giai đoạn 2.

---

## 10. Test

```
tests/fixtures/2008_Audi_A6_V6__3_2L_V0_17_4.sim    # file thật, 1306 dòng
```

**Test bắt buộc:**

1. **Roundtrip** — decompile → build → so sánh từng trường (bỏ qua khác biệt khoảng trắng)
2. **Đếm TAB** — mọi dòng `INFO_DATABASE` sinh ra có đúng 6 TAB
3. **ISO-TP** — payload 1..300 byte, kiểm tra PCI, seq quay vòng tại 0x2F→0x20, độ dài FF
4. **Golden file** — mỗi cú pháp §4 có một file `.sl` và một `.sim` kỳ vọng
5. **Validator** — mỗi mã lỗi/cảnh báo có ít nhất một case dương và một case âm

---

## 11. Giới hạn và điều chưa biết

Những điểm sau **chưa xác minh**, không được giả định trong code:

| Điều chưa biết | Cách xử lý tạm |
|---|---|
| Con số sau `Req>` / `Res<` (thấy 1,2,3,4,5,6,7,8,14) | Luôn sinh `1`; khi decompile thì **giữ nguyên** giá trị gốc |
| `xx` xử lý ở tầng nào | Truyền thẳng, không diễn giải |
| `^` (byte engine tự tính) | Chưa hỗ trợ trong DSL; decompile thì giữ nguyên |
| `CorrectFileDB` có sửa dữ liệu không | Cho phép `--no-analyze` để load với `isEnableAnalyze=false` |
| `r0` với broadcast | Không sinh; báo lỗi nếu người dùng viết |

**Không tự ý "sửa" file khi decompile.** Nếu gặp ký hiệu chưa hiểu, giữ nguyên
và đánh dấu `// TODO: unknown token` thay vì bỏ đi.

---

## 12. Giai đoạn 2 (chưa làm — không xây trong giai đoạn 1)

### 12.1 Runtime state backend

Giải quyết đúng cái `Q--` không làm được: trạng thái xuyên phiên (§4.8).

Khả thi vì logic so khớp chạy trên PC, không trên board — nên có sẵn hai API:

- `setCallbackUpdateConsoleText(cb)` — bắn sự kiện mỗi khi có bản tin
- `OBDDB_UpdateRespData(...)` — đổi response, **có hiệu lực ngay**, không nạp lại file

Ghép lại cho ra đúng mô hình `on message` của CAPL:

```python
state = {"dtc_cleared": False}

def on_message(port, msgtype, message):
    if is_request(message, service=0x04):
        state["dtc_cleared"] = True
        db.OBDDB_UpdateRespData(req="...03...", resp="02 43 00 ...")
```

Tool chèn bao nhiêu lệnh giữa chừng cũng không ảnh hưởng, vì trạng thái nằm ở
Python chứ không phụ thuộc thứ tự liền kề.

**Điều kiện tiên quyết:** kết quả M0 (§9.1). Không thiết kế cú pháp `state` /
`on message` trước khi biết callback trả về gì.

### 12.2 Backend điều khiển tool (JSON)

Cùng cú pháp, backend khác. Chưa có schema JSON nên chưa đặc tả được.

### 12.3 Ràng buộc kiến trúc cho giai đoạn 1

Giữ `codegen.py` **tách rời** parser và AST. Thêm backend thứ hai hoặc thứ ba
không được đòi sửa grammar.

### 12.4 Bảng phân tầng cuối cùng (tham khảo)

| Loại nhu cầu | Backend | Giai đoạn |
|---|---|---|
| Tĩnh, wildcard, đa khung ISO-TP | file `.sim` | 1 |
| Chuỗi liền kề một bước | `Q--` | 1 |
| Xoay vòng theo số lần gọi | `l1` | 1 |
| Trễ / lặp | `t` / `r` | 1 |
| **Trạng thái xuyên phiên** | **runtime Python** | **2** |
| Điều khiển tool | JSON | 2 |
