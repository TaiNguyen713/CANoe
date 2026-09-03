"""Cập nhật nội dung file .sim - hiện tại có 2 việc:
1. for_vehicle(): tạo (hoặc tái sử dụng) 1 file .sim RIÊNG cho từng tổ hợp
   xe/system/subsystem/profile, copy từ CAN_default.sim làm điểm khởi đầu -
   để không bao giờ ghi đè lên file mẫu dùng chung. File này nằm trong 1 cây
   thư mục output/ có cấu trúc phân cấp (xem for_vehicle()) thay vì 1 file
   tên dài phẳng như trước.
2. add_entries(): append các cặp dòng INFO_DATABASE (Req/Res, build sẵn bởi
   SimulatorAnalyzer.CAN_single_response()) vào cuối phần database của file
   riêng đó.
Các thao tác khác (sửa field khác, dedup...) sẽ bổ sung theo hướng dẫn tiếp
theo.
"""

import logging
import os
import re
import shutil
import tempfile
import uuid

from simulatorhandle.simulator_control import DEFAULT_SIM_FILE

logger = logging.getLogger(__name__)

# Windows không cho phép các ký tự này trong tên file/thư mục - thay bằng
# "_" để mỗi cấp thư mục (tên xe, tên system, tên subsystem) không bị lỗi
# nếu lỡ chứa ký tự cấm (khoảng trắng và ngoặc đơn như "Accent (HC)" vẫn hợp
# lệ trên Windows nên không cần đụng tới).
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')

# Tên thư mục gốc chứa toàn bộ output, nằm cùng cấp với SimFiles/ - xem
# for_vehicle() để biết cấu trúc cây thư mục bên trong.
_OUTPUT_DIR_NAME = "output"


class SimFileUpdater:
    """Cập nhật file .sim bằng cách append entry mới, không đụng tới các
    field cấu hình khác của file (vd SIZE_DATABASE giữ nguyên như file mẫu
    - theo yêu cầu, KHÔNG tự tính lại theo số entry đã add).
    """

    def __init__(self, simfile):
        self.simfile = simfile

    @property
    def log_path(self) -> str:
        """Đường dẫn file .log Rx/Tx tương ứng - luôn cùng tên với .sim,
        chỉ đổi đuôi (quy ước dùng xuyên suốt: SimulatorControl ghi log ra
        đây, process.py đọc lại để phân tích/dò Protocol)."""
        return os.path.splitext(self.simfile)[0] + ".log"

    @classmethod
    def new_scratch(cls, base_simfile=DEFAULT_SIM_FILE) -> "SimFileUpdater":
        """Tạo 1 SimFileUpdater TẠM (file .sim chưa tồn tại, copy sẵn từ
        `base_simfile`) trong thư mục temp hệ thống - dùng cho discovery
        pass và test từng tổ hợp Init riêng lẻ (xem
        process.VehicleDataCollector._discover_and_process_profiles()).
        KHÔNG BAO GIỜ nằm trong cây output/ thật - chỉ những tổ hợp đã XÁC
        NHẬN đủ mới được ghi thành profile thật qua for_vehicle() + copy_from().
        """
        path = os.path.join(tempfile.gettempdir(), f"auto_reverse_db_scratch_{uuid.uuid4().hex}.sim")
        shutil.copyfile(base_simfile, path)
        return cls(path)

    def cleanup(self) -> None:
        """Xoá file .sim tạm (+ .log đi kèm nếu có) - dùng sau khi 1
        scratch/candidate SimFileUpdater (xem new_scratch()) đã dùng xong,
        tránh rác tích luỹ trong thư mục temp hệ thống qua nhiều lần chạy."""
        for path in (self.simfile, self.log_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass

    def copy_from(self, source: "SimFileUpdater") -> None:
        """Copy thẳng nội dung .sim VÀ .log từ 1 SimFileUpdater khác (thường
        là 1 scratch/candidate vừa CONFIRM đủ, xem new_scratch()) sang file
        của instance này - dùng thay vì dạy lại (add_entries) từ đầu khi nội
        dung cần y hệt cái đã có sẵn (tiết kiệm 1 chu kỳ reload+chờ trên máy
        thật cho mỗi profile, xem _materialize_profile_sim())."""
        shutil.copyfile(source.simfile, self.simfile)
        if os.path.exists(source.log_path):
            shutil.copyfile(source.log_path, self.log_path)

    @classmethod
    def for_vehicle(cls, year, make, model, engine, system, subsystem="", profile_id="1", base_simfile=DEFAULT_SIM_FILE):
        """Trả về 1 SimFileUpdater gắn với file "{profile_id}.sim" nằm
        trong cây thư mục phân cấp:

            output/{Year}_{Make}_{Model}_{Engine}/{System}/{profile_id}.sim
            output/{Year}_{Make}_{Model}_{Engine}/{System}/{Subsystem}/{profile_id}.sim  (nếu có subsystem)

        `output/` nằm cùng cấp với `SimFiles/` (thư mục cha của
        `base_simfile`). File .log/.json tương ứng (xem process.py) chỉ đổi
        đuôi của cùng path này nên tự động nằm chung thư mục lá.

        Nếu file .sim CHƯA tồn tại, copy từ base_simfile làm điểm khởi đầu.
        Nếu đã tồn tại (từ lần chạy reverse trước), TÁI SỬ DỤNG nguyên vẹn -
        không copy đè - để các command đã dò được ở lần chạy trước không bị
        mất, add_entries() ở lần chạy sau sẽ cộng dồn tiếp vào đúng file này.
        """
        base_dir = os.path.dirname(os.path.dirname(base_simfile))
        vehicle_dir = _INVALID_FILENAME_CHARS.sub("_", f"{year}_{make}_{model}_{engine}")
        system_dir = _INVALID_FILENAME_CHARS.sub("_", system)
        dir_parts = [base_dir, _OUTPUT_DIR_NAME, vehicle_dir, system_dir]
        if subsystem:
            dir_parts.append(_INVALID_FILENAME_CHARS.sub("_", subsystem))
        target_dir = os.path.join(*dir_parts)
        os.makedirs(target_dir, exist_ok=True)

        path = os.path.join(target_dir, f"{profile_id}.sim")
        if not os.path.exists(path):
            shutil.copyfile(base_simfile, path)
        return cls(path)

    def add_entries(self, entries, label=None):
        """Append các cặp (req_line, res_line) vào cuối file .sim, mỗi cặp
        cách nhau 1 dòng trống (đúng style file mẫu OBD2 CAN 11Bits.sim).

        `entries`: list các tuple (req_line, res_line), thường lấy trực
        tiếp từ SimulatorAnalyzer.CAN_single_response().

        `label` (optional): tên giai đoạn/process sinh ra các entry này (vd
        "Init", "Read DTCs", "Live data", "Active Test", "Special function")
        - ghi thành 1 dòng comment "#####{label}" ngay trước block entry,
        đúng convention comment đã thấy trong file mẫu OBD2 CAN 11Bits.sim
        (vd "#####engine speed: 1984.00 RPM"). Giúp phân biệt được entry nào
        thuộc giai đoạn nào khi đọc lại file sau này, vì command init (lúc
        vừa vào system) khác hẳn command của Read DTCs/Live data/Active
        Test/Special function dù cùng nằm chung 1 file .sim của xe đó.

        Đọc/ghi ở chế độ nhị phân (rb/wb), tự dùng line ending "\\r\\n" cố
        định thay vì mode text - file .sim gốc dùng CRLF nhất quán, mode
        text mặc định của Python trên Windows có thể biến "\\n" thành
        "\\r\\n" không kiểm soát được nếu nội dung có sẵn "\\r\\n", gây lặp
        CR thừa.
        """
        with open(self.simfile, "rb") as f:
            content = f.read()

        if not content.endswith(b"\r\n"):
            content += b"\r\n"

        header = f"#####{label}\r\n".encode("utf-8") if label else b""
        block = b"\r\n".join(f"{req}\r\n{res}".encode("utf-8") for req, res in entries)
        content += b"\r\n" + header + block + b"\r\n"

        with open(self.simfile, "wb") as f:
            f.write(content)

        logger.info(
            "add_entries: added %d entry (%s) into '%s':",
            len(entries), label or "?", self.simfile,
        )
        for req, res in entries:
            logger.info("  Req: %s", req)
            logger.info("  Res: %s", res)
