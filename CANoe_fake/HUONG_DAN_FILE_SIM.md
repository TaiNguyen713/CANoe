# Hướng dẫn định dạng file `.sim`

**Engine:** `SimulatorInterface.dll` v2.3 (OBDSimulation_CLI 1.3.36.3)
**Nguồn:** giải mã từ `loadFileSimToDB`, `parsefileSim`, `OBDDB_AddReq`,
`AnalyserFileDB`, `DeviceLoadDataBase`, `processSendResp`
**Cập nhật:** 2026-09-03 (bản 2 — bổ sung `Q--`, timing đã kiểm chứng thực tế)

> Tài liệu mô tả những gì **code thực sự làm**, không phải tài liệu chính thức.
> Mục 12 liệt kê phần còn chưa xác minh.

---

## 0. Kiến trúc — logic chạy trên PC, không phải trên board

`DeviceLoadDataBase` **không gửi database xuống thiết bị**. Nó chỉ nạp file vào
bộ nhớ PC, rồi `Device_WriteSetting()` ghi *cấu hình* (protocol, chân DLC,
baudrate) xuống board.

```
Scan tool ──OBD──► Board (thu phát) ──serial──► PC
                                                 │ so khớp DB
Scan tool ◄──OBD── Board ◄────serial──────────── ┘ gửi response
```

**Hệ quả:** mọi tính năng động (`t`, `r`, `l1`, `Q--`) chạy trên PC, không phụ
thuộc firmware. Và `OBDDb_UpdateRes` / `OBDDB_UpdateRespData` có hiệu lực
**ngay lập tức** — không cần nạp lại file.

**Giới hạn:** response đi vòng qua USB-serial nên độ chính xác timing chỉ
tới mức vài ms. Test dưới 1ms không khả thi.

---

## 1. Cấu trúc file

```
<config sw> Protocol = 29                        ← cấu hình phần cứng
<config sw> BAUDRATE = 500000
SIZE_DATABASE = 5                                ← KHÔNG được parse

//NOTE: Odometer 40240 km                        ← giữ lại, đọc qua GetNotes()
// comment thường                                 ← bỏ

ProtocolConfig	EnableAutoCANFC

INFO_DATABASE = Req>1	t0	r1	000007DF 08 02 09 02 xx xx xx xx xx	NONE	0	0
```

Quy tắc lọc (`parsefileSim`): giữ dòng nếu `IsNoteLine()` **hoặc** không bắt
đầu bằng `/`.

---

## 2. Dòng dữ liệu — 7 trường, phân cách bằng TAB

```
INFO_DATABASE = Res<1 → t500 → r3 → 000007E8 08 06 49 ... → NONE → 0 → 0
        [0]            [1]    [2]           [3]              [4]    [5]  [6]
```

| Index | Tên | Mô tả |
|-------|-----|-------|
| `[0]` | Loại dòng | `INFO_DATABASE = Req...` / `Res...` / `Broadcast...` |
| `[1]` | **delayTime** | `t<số>` ms. Trống → lấy `TFRAME` |
| `[2]` | **repeatTime** | `r<số>`. Trống → `1` (= không lặp) |
| `[3]` | Dữ liệu | `[Q--] [l1] <CANID> <DLC> <8 byte>` |
| `[4]` | Checksum | `NONE` / `CS` / số |
| `[5]` | Poly | đa thức CRC, mặc định `29` (0x1D). Chỉ dùng khi `[4]` = `CRC` |
| `[6]` | — | không được code đọc |

### ⚠ Quy tắc TAB

**Số lượng TAB luôn là 6, không đổi.** Hai trường timing là hai ô **rỗng**
có sẵn giữa tag và dữ liệu — anh điền vào, không thêm tab mới.

```
Trước:  tag →→→ data
Sau:    tag → t500 → r3 → data      (vẫn 3 tab)
```

Kiểm tra nhanh mọi dòng:
```bash
awk -F'\t' '/^INFO_DATABASE/ && NF!=7 {print NR": "NF" truong"}' file.sim
```

Sửa hai số cuối (`[5]`, `[6]`) **không có tác dụng** — đó là poly và một
trường không ai đọc.

---

## 3. `t<ms>` — trễ trước khi gửi response

```csharp
if (dbmatch.getDelayTime() > 2)
    Utilities.DelayMs(dbmatch.getDelayTime());
simcomport.SendMesg(...);
```

Trễ áp dụng **trước khi gửi**, mô phỏng thời gian xử lý của ECU (P2).

| Viết | Kết quả |
|------|---------|
| `t500` | 500 ms ✔ |
| `500` | **bị bỏ qua im lặng** — thiếu tiền tố `t` ✘ |
| `t0`, `t1`, `t2` | **bị bỏ qua** — ngưỡng cứng `> 2` |
| `t3` | giá trị nhỏ nhất có tác dụng |
| *(rỗng)* | lấy `TFRAME` từ header |

**Lưu ý:** file Audi để `TFRAME = 5`, và 5 > 2, nên **mọi response vốn đã
có sẵn delay 5ms**. Anh không bật tính năng đang tắt, chỉ đổi giá trị.

### ⚠ Response đa khung — chỉ đặt `t` ở khung ĐẦU

`processSendResp` được gọi **một lần cho mỗi khung**. Đặt `t500` lên cả 3
dòng của một response ISO-TP → tổng 1.5s và khoảng cách giữa các khung 500ms,
vượt xa STmin, scan tool sẽ timeout.

```
INFO_DATABASE = Res<1	t500		000007E8 08 10 14 49 02 01 4b 4d 48	NONE	0	0   ← chỉ khung đầu
INFO_DATABASE = Res<1			000007E8 08 21 52 43 38 41 33 58 52	NONE	0	0
INFO_DATABASE = Res<1			000007E8 08 22 55 32 38 34 31 32 39	NONE	0	0
```

`Utilities.DelayMs` **chặn luồng**. `t5000` làm simulator đứng 5 giây và có
thể bỏ lỡ khung đến trong lúc đó.

---

## 4. `r<n>` — lặp response

```csharp
uint repeatTime = dbmatch.getRepeatTime();
if (repeatTime < 2) repeatTime = 0u;
```

**Chỉ `r2` trở lên mới có tác dụng.** `r0` và `r1` đều cho ra 0 (không lặp).

---

## 5. `Q--` — response phụ thuộc request trước đó ⭐

```csharp
if (Reqstring.ToUpper().Contains("Q--") || Reqstring.ToUpper().Contains("Q00"))
{
    isdependonprev = true;
    Req = Reqstring.Substring(3).Trim();
}
```

Đặt ở **đầu trường `[3]`**, ngay trước CAN ID. Bật `IsDepenonPrevReq`.

Đây là **cơ chế mô phỏng trạng thái** của engine. Request chỉ khớp khi nó đi
sau một request khác trong chuỗi — cho phép mô phỏng session, security access,
và mọi kịch bản nhiều bước.

```
INFO_DATABASE = Req>1			000007E0 08 02 10 03 00 00 00 00 00	NONE	0	0
INFO_DATABASE = Res<1			000007E8 08 06 50 03 00 32 01 F4 00	NONE	0	0
INFO_DATABASE = Req>1			Q-- 000007E0 08 02 27 03 00 00 00 00	NONE	0	0
INFO_DATABASE = Res<1			000007E8 08 06 67 03 12 34 56 78 00	NONE	0	0
```

### `Q--` cũng bỏ qua kiểm tra trùng lặp

```csharp
if (!isFoundReqInDB(Reqstring) | isdependonprev | isMultiReq)
    cldb.EnableFrame(true);
else
    cldb.errorstatus = Error_DupplicateReq;   // entry bị VÔ HIỆU HÓA
```

Bình thường request trùng bị disable im lặng. Với `Q--`, anh khai báo **cùng
một request nhiều lần với response khác nhau**, phân biệt bằng ngữ cảnh —
tức state machine, không cần công cụ ngoài.

### ⚠ Phải đặt ở đầu

```csharp
Req = Reqstring.Substring(3).Trim();   // cắt cứng 3 ký tự
```

Điều kiện dùng `Contains` nhưng cắt lại giả định vị trí đầu. Nếu `Q--` nằm
giữa chuỗi, **3 ký tự đầu của dữ liệu thật bị mất mà không báo lỗi**.

`Q00` tương đương `Q--`.

---

## 6. `l1` — xoay vòng response

Đặt ở đầu trường `[3]` (sau `Q--` nếu có cả hai):

```
INFO_DATABASE = Req>1	t0	r1	000007DF 08 03 02 04 00 00 00 00 00	4	0	0
INFO_DATABASE = Res<1	t0	r1	l1 000007E8 08 05 42 04 00 80 00 00 00	4	0	0
INFO_DATABASE = Res<1	t0	r1	000007E8 08 05 42 04 00 81 00 00 00	4	0	0
```

Cùng một request, mỗi lần gọi trả về giá trị khác nhau, xoay vòng.
Dùng cho: giá trị PID thay đổi, mô phỏng sensor, kịch bản nhiều bước.

---

## 7. `Broadcast` — bản tin phát tuần hoàn

```
INFO_DATABASE = Broadcast	t100	r0	00000300 08 05 22 F1 90 00 00 00	NONE	0	0
```

Xử lý cùng nhánh với `Res`, dùng được cả `t` và `r`. Không cần request kích hoạt.

---

## 8. `ProtocolConfig`

```
ProtocolConfig	EnableAutoCANFC
ProtocolConfig	DisableAutoCANFC
```

Bật/tắt việc engine tự sinh khung Flow Control cho ISO-TP.
Tắt khi cần test hành vi scan tool khi ECU **không** gửi FC.

---

## 9. Khối `<config sw>`

| Dòng | Ánh xạ |
|------|--------|
| `Protocol` | `dbProtocol` + `setProtocol()` |
| `PIN_KRX_CANH` / `TYPE_KRX_CANH` / `VOLT_KRX_CANH` | `dlckline` (pin / đảo / điện áp, chỉ nhận <4) |
| `PIN_KTX_CANH` / `TYPE_KTX_CANH` / `VOLT_KTX_CANH` | `dlclline` |
| `BAUDRATE` / `DATABIT` / `PARITY` | UART |
| **`TBYTE`** | `timingp4` |
| **`TFRAME`** | `timingp2` ← **mặc định delayTime cho mọi response** |
| `RANGE` | bị bỏ qua — luôn reset filter về `("0","0")` |

`VREF`, `F CAN NUMBER FRAME`, `SIZE_DATABASE` **không được parse**.

---

## 10. Ký hiệu trong trường dữ liệu

| Ký hiệu | Ý nghĩa | Nguồn |
|---------|---------|-------|
| `Q--` / `Q00` | phụ thuộc request trước | ✔ `OBDDB_AddReq` |
| `l1` | xoay vòng response | ✔ `loadFileSimToDB` |
| `xx` / `XX` | byte don't-care | suy luận từ file |
| `^` (`^10`, `^20`) | byte engine tự tính (PCI ISO-TP) | suy luận từ file |

Nhiều dòng `Res` liên tiếp = **các khung của một response dài**.
`Res<` = đơn khung, `Res>` = đa khung.

---

## 11. ⚠ Bug đã biết trong engine

**a) Kiểm tra độ dài mảng sai** (`loadFileSimToDB`)
```csharp
if (obddatainfos.Length > 4)                 // phải là > 5
    polybyte = (byte)Utilities.stringtohex(obddatainfos[5]);
```
Dòng chỉ có 5 trường → `IndexOutOfRange` → bị catch nuốt →
**toàn bộ file không load được**. *Luôn giữ đủ 7 trường.*

**b) Validation ISO-TP là code chết** (`AnalyserFileDB`)
```csharp
if (dbProtocol == enumprotocol.DWCAN || dbProtocol == enumprotocol.CAN_FD)
```
`enumprotocol` chỉ có 0–10, nhưng file khai `Protocol = 29` (giá trị của
`enumOBDProtocol.PROTOCOL_CAN`). Hai enum bị lẫn → khối kiểm tra
**không bao giờ chạy**.

**c) Tính độ dài First Frame sai**
```csharp
CanFrameRespExpectedLen = (databyte[0] & 0xF00) + databyte[1];
```
`databyte[0]` là 1 byte nên `& 0xF00` luôn = 0. Đúng phải là
`((databyte[0] & 0x0F) << 8) + databyte[1]`.

**d) `Q--` cắt cứng 3 ký tự** — xem mục 5.

---

## 12. Chưa xác minh

| Câu hỏi | Cách trả lời |
|---------|--------------|
| Con số sau `Req>` / `Res<` (1,2,3,4,5,6,7,8,14) nghĩa là gì | Đọc `OBDDB_AddRes`, `classOBDDataInfo.InitializeRespData` |
| `CorrectFileDB` có sửa dữ liệu không | Đọc hàm đó |
| `xx` và `^` xử lý ở đâu | Đọc `CorrectMsgOBD`, `classCANFrameData` |
| Cú pháp bật `ObdCounter*` từ file | Đọc `OBDDB_AddRes` |
| `r0` với Broadcast = vô hạn hay tắt | Thử nghiệm |

**Lưu ý:** `Enable` **không phải cột trong file**. Parser tự quyết: request
mới → bật, trùng → tắt (trừ khi có `Q--` hoặc `isMultiReq`).

---

## 13. Debug — luôn gọi `getLogError()`

```csharp
foreach (string _err in simdbhandler.getLogError())
    updateCallbackDisplay(MSG_INFO, _err);
```

M��i lỗi parse đều nằm ở đây. Qua CLI, chạy với tham số `showdata` để in
ra console:

```
OBDSimulation_CLI.exe "COM3" "file.sim" "showdata"
```

Đừng đoán dòng nào hỏng — đọc log.

---

## 14. Template

```
INFO_DATABASE = Req>1			<CANID> <DLC> <8 byte>	NONE	0	0
INFO_DATABASE = Res<1	t500		<CANID> <DLC> <8 byte>	NONE	0	0
INFO_DATABASE = Req>1			Q-- <CANID> <DLC> <8 byte>	NONE	0	0
INFO_DATABASE = Res<1			l1 <CANID> <DLC> <8 byte>	NONE	0	0
INFO_DATABASE = Broadcast	t100	r2	<CANID> <DLC> <8 byte>	NONE	0	0
ProtocolConfig	EnableAutoCANFC
```

Phân cách **bắt buộc là TAB**. Mọi dòng `INFO_DATABASE` phải có đúng 6 TAB.
