# CAPL Syntax Learning & Mock Workspace

Workspace nhẹ, không phụ thuộc (zero-dependency) để **học và luyện tập cú pháp CAPL** (CAN Access Programming Language) trong VS Code mà **không cần license CANoe** hay engine thực thi thật.

---

## 1. Cách mở workspace trong VS Code

1. Mở VS Code.
2. Chọn **File > Open Folder...** và trỏ tới thư mục này (`CANoe_rep`).
3. VS Code sẽ tự động đọc cấu hình trong `.vscode/settings.json` và `.vscode/extensions.json`.
4. Khi được gợi ý cài extension (góc dưới bên phải), chọn **Install All** để cài các extension hỗ trợ cú pháp CAPL/C.
5. Các file `.can` sẽ được highlight theo cú pháp C (fallback) vì CAPL có cấu trúc gần giống C.

> Nếu máy bạn đã cài CANoe/Vector, extension `capl-language-support` (nếu có trên Marketplace) sẽ cho highlight chính xác hơn.

---

## 2. Mô phỏng giao diện CAPL Browser bằng cách chia màn hình (Split Editor)

CANoe thật có cửa sổ **CAPL Browser** với 3 vùng chính: cây file/hàm bên trái, code editor ở giữa, và Write Window (log) ở dưới. Bạn có thể mô phỏng lại trong VS Code:

1. **Explorer (cây thư mục) bên trái**: Mặc định VS Code đã hiển thị `modules/` và `templates/` giống cây file trong CAPL Browser.
2. **Chia đôi màn hình soạn thảo (giống nhiều tab code)**:
   - Mở 1 file `.can`, nhấn `Ctrl + \` (Windows) để tách editor thành 2 cột.
   - Kéo tab file khác sang cột bên phải để so sánh 2 module cùng lúc (vd: `capl_template.can` bên trái, `03_can_message_handling.can` bên phải).
3. **Giả lập Write Window bằng Terminal panel**:
   - Mở Terminal (`` Ctrl + ` ``) ở phía dưới, kéo giãn để giống thanh Write Window của CANoe.
   - Dùng terminal này để ghi chú lại "kết quả mong đợi" khi bạn tự trace code bằng tay (vì không có engine thật để chạy `write()`).
4. **Tùy chọn**: Bật chế độ **Zen Mode** (`Ctrl K Z`) khi muốn tập trung đọc 1 file duy nhất, giống việc phóng to 1 pane trong CANoe.

---

## 3. Cấu trúc thư mục

```text
.
├── .vscode/
│   ├── settings.json      # Cấu hình file association (.can/.cin -> C), tab = 2 space
│   └── extensions.json    # Extension đề xuất cho CAPL/C
├── templates/
│   └── capl_template.can  # Boilerplate: preStart, start, timer, message, key, stopMeasurement
├── modules/
│   ├── 01_basics_variables.can      # Kiểu dữ liệu, mảng, msTimer, message
│   ├── 02_events_and_timers.can     # setTimer, cancelTimer, on timer
│   ├── 03_can_message_handling.can  # output(), this.id, this.byte(x), this.dlc, this.dir
│   ├── 04_uds_diagnostics.can       # diagRequest, diagResponse, ISO-TP
│   └── 05_system_variables.can      # on sysvar, sysGetVariableInt, @sysvar::...
└── README.md
```

Mỗi file `.can` trong `modules/` có các dòng `// TODO:` — hãy **tự gõ tay** phần code còn thiếu để luyện phản xạ cú pháp, thay vì chỉ đọc.

---

## 4. Bảng tóm tắt cú pháp CAPL cốt lõi

| Nhóm | Cú pháp | Ý nghĩa |
|---|---|---|
| **Khối biến** | `variables { ... }` | Khai báo biến toàn cục (global) cho node CAPL |
| **Kiểu dữ liệu** | `byte`, `word`, `dword`, `int`, `long`, `double` | Số nguyên/thực với độ rộng khác nhau |
| **Mảng** | `byte data[8];` | Mảng cố định, hay dùng cho payload CAN |
| **Sự kiện khởi tạo** | `on preStart` | Chạy trước khi measurement bắt đầu |
| **Sự kiện bắt đầu** | `on start` | Chạy khi measurement bắt đầu (bus active) |
| **Timer 1 lần** | `msTimer t; setTimer(t, ms);` | Đặt lịch chạy `on timer t` sau `ms` mili giây |
| **Timer lặp lại** | Gọi lại `setTimer()` bên trong `on timer` | Tạo hiệu ứng timer tuần hoàn |
| **Hủy timer** | `cancelTimer(t);` | Hủy timer đang chờ |
| **Nhận message** | `on message *` / `on message <Ten>` | Bắt sự kiện khi nhận CAN frame |
| **Thuộc tính frame** | `this.id`, `this.dlc`, `this.dir`, `this.byte(x)` | Đọc ID, độ dài, hướng, dữ liệu byte của frame |
| **Gửi frame** | `output(msgVar);` | Gửi 1 CAN frame ra bus |
| **Phím tắt** | `on key 'x'` | Gán hành động cho phím `x` trong Write Window |
| **Kết thúc đo** | `on stopMeasurement` | Dọn dẹp khi measurement dừng |
| **UDS request** | `diagRequest Service.Request req;` | Khai báo 1 yêu cầu chẩn đoán UDS |
| **UDS response** | `on diagResponse Service.Request` | Bắt phản hồi UDS tương ứng |
| **Đọc tham số UDS** | `diagGetParameter(this, "Param", buf);` | Lấy giá trị 1 tham số từ response |
| **System Variable** | `on sysvar NS::Var` | Bắt sự kiện khi sysvar thay đổi |
| **Đọc sysvar (hàm)** | `sysGetVariableInt(sysvar::NS::Var)` | Đọc giá trị int của sysvar |
| **Đọc/ghi sysvar (trực tiếp)** | `@sysvar::NS::Var` | Truy cập trực tiếp giá trị sysvar |
| **Ghi log** | `write("...", args);` | In thông tin ra Write Window (giống `printf`) |

---

## 5. Gợi ý lộ trình luyện tập

1. Đọc và hiểu `templates/capl_template.can` trước — đây là "khung xương" mà mọi file CAPL thật đều có.
2. Làm lần lượt các module từ `01` đến `05`, hoàn thành từng `// TODO:` bằng tay.
3. Sau khi tự tin với cú pháp, thử mở CANoe thật (nếu có license) và copy code vào một node CAPL thật để build thử — trình biên dịch CAPL sẽ báo lỗi cú pháp nếu có, giúp bạn tự kiểm tra lại.
