# simlang

DSL kiểu CAPL (`.can`) transpile ra Python, điều khiển trực tiếp phần cứng
OBD Simulator qua `pythonnet`. Xem `SPEC_SIMLANG_V2.md` ở gốc repo cho đặc
tả đầy đủ; `HUONG_DAN_FILE_SIM.md` cho định dạng file `.sim`.

> **Không phải CAPL, không tương thích CANoe.** `simlang/examples/*.can`
> dùng chung đuôi file `.can` với `capl/*.can` của app `canoe_fake/` khác ở
> gốc repo — hai thứ không liên quan, khác thư mục, khác cú pháp.

---

## Trạng thái

| Mốc | Nội dung | Trạng thái |
|---|---|---|
| M0 | Spike phần cứng thật | **Đã chạy thật trên COM3** — API xác nhận đầy đủ qua reflection, round-trip đơn khung hoạt động thật qua scan tool thật, đa khung còn treo. Xem `docs/M0_findings.md` |
| M1 | `simfile.py` — parser `.sim` | ✅ Xong, test trên 3 file thật + 1 file xe thật (Hyundai Accent 1067 dòng) |
| M2 | Grammar + parser + AST cho `.can` | ✅ Xong |
| M3 | `isotp.py` (lõi) | ✅ Xong, test thuần Python. `RealTransport` đã cập nhật theo M0 nhưng multi-frame chưa xác nhận thật |
| M4 | Codegen + runtime + dispatch | ✅ Xong, test cả 3 ca khó trên `FakeTransport` |
| M5 | Importer `.sim` → `.can` | ✅ Xong |
| M6 | CI trên board thật | Chưa làm — cần phần cứng + logic analyzer cho phần multi-frame |

Chạy test: `pytest simlang/tests` (hoặc `pytest` từ gốc repo).

## CLI

```bash
simlang check  test.can                # parse + validate
simlang build  test.can -o test.py     # sinh Python để debug
simlang import old.sim -o old.can      # .sim -> .can (một chiều, KHÔNG roundtrip)
simlang run    test.can --fake         # chạy on_start, không cần board
simlang run    test.can --port COM3    # chạy thật — CHƯA XÁC MINH, chờ M0
```

(`fmt` chưa implement.)

## Khoảng trống đã biết

- **File fixture Audi thật** (`tests/fixtures/2008_Audi_A6_V6__3_2L_V0_17_4.sim`,
  1306 dòng) mà spec dùng làm mốc test không có trong repo. Test hiện dùng
  3 file thật đã có sẵn (`engine/SimFiles/{DTC_info,CAN_default,CAN_default_dev}.sim`,
  copy vào `tests/fixtures/`). Có thêm 1 file xe thật khác ở gốc repo
  (`2019 Hyundai Accent(HC) G 1.6 GDI_V0.15.sim`, 1067 dòng) dùng để test M0
  sống — có thể dùng làm fixture bổ sung nếu cần.
- **`RealTransport`** đã cập nhật theo kết quả M0 thật (constructor cần
  callback, config `OBDInterface` đầy đủ, 2 fix runtime .NET) — round-trip
  **đơn khung** xác nhận hoạt động thật (qua đường `ObdSimulator`, chưa qua
  `ClassDeviceComport`+`SendMesg` trực tiếp). Round-trip **đa khung** (First
  Frame/Consecutive Frame) CHƯA xác nhận — cần logic analyzer trên bus CAN.
  Xem `docs/M0_findings.md` đầy đủ trước khi sửa `transport.py`.
- Vài quyết định thiết kế không có trong spec gốc (số CF bắt đầu từ 1 theo
  chuẩn ISO 15765-2 thật thay vì 0 như spec diễn giải; `reply_can_id()` đặc
  cách `0x7DF` → `0x7E8` thay vì cộng 8; `data <bytes>` mô tả TOÀN BỘ payload
  kể cả byte service) — xem docstring tại chỗ khai báo trong code.

## Cấu trúc

```
simlang/
├── grammar/simlang.lark
├── src/simlang/
│   ├── ast_nodes.py, parser.py, codegen.py
│   ├── simfile.py       # parser .sim (M1)
│   ├── importer.py      # .sim -> .can (M5)
│   ├── cli.py
│   └── runtime/
│       ├── isotp.py, dispatch.py, timers.py, builtins.py, transport.py
├── spike/m0_probe.py     # chạy tay trên máy có board — KHÔNG tự chạy được ở đây
├── docs/M0_findings.md   # điền sau khi chạy spike
├── examples/example_5_1.can
└── tests/                # pytest — 167 test, không cần phần cứng
```
