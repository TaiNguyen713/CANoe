"""Điều khiển tiến trình OBDSimulation_CLI.exe (nạp file .sim, dò cổng COM,
kill/reload) - đóng gói thành class SimulatorControl thay vì hàm rời +
biến global module như bản cũ, để dùng lại được từ nhiều nơi (GUI,
flow automation, sim_manager sau này...) mà mỗi lần dùng không giẫm lên
handle tiến trình của lần khác.

Mỗi instance gắn với 1 cổng COM cụ thể (self.com) để hỗ trợ chạy SONG SONG
nhiều simulator cùng lúc - đã xác nhận trên thiết bị thật: máy có thể cắm
đồng thời nhiều mạch simulator (vd COM3 + COM5, cùng VID:PID), và
OBDSimulation_CLI.exe cho phép nhiều tiến trình chạy song song bình thường,
mỗi tiến trình 1 cổng. Tuy nhiên cửa sổ/console của nó KHÔNG hề đặt tiêu đề
theo cổng COM (xác nhận qua `tasklist /v` - Window Title luôn "N/A"), nên
không thể phân biệt các tiến trình đang chạy bằng tên hay tiêu đề cửa sổ.
Cách duy nhất xác định đúng tiến trình ứng với cổng nào là so khớp cổng COM
trong command-line của tiến trình (xác nhận qua
`Get-CimInstance Win32_Process`) - đó là lý do kill_commandline_process()
dùng psutil so khớp cmdline thay vì kill theo tên tiến trình như bản cũ
(bản cũ kill theo tên sẽ giết NHẦM cả simulator khác đang chạy song song).

## Vụ crash Console.ReadKey khi capture log (quan trọng, đọc trước khi sửa)

exe cần console THẬT (không bị redirect) để `Console.ReadKey()` hoạt động
("Press ESC to exit"). Muốn tự động capture log Rx/Tx ra file (thay vì bắt
người dùng copy tay từ console), ban đầu tưởng chỉ cần:
1. Redirect MỖI stdout (giữ nguyên stdin) - SAI: xác nhận live vẫn crash.
2. Thêm `creationflags=CREATE_NEW_CONSOLE` - VẪN SAI, vẫn crash ngay sau
   "Press ESC to exit" (~1 giây), xác nhận qua process.poll() - tiến trình
   chết thật, không phải hiện tượng do môi trường test.

Lý do thật: Python `subprocess.Popen` hễ CÓ truyền bất kỳ tham số
stdin/stdout/stderr nào (kể cả chỉ mỗi `stdout=`), sẽ tự set cờ
`STARTF_USESTDHANDLES` trong STARTUPINFO và PHẢI cấp luôn cả 3 handle -
handle nào không được chỉ định tường minh (ở đây là stdin) sẽ mặc định lấy
NGUYÊN handle stdin của tiến trình CHA, bất kể có `CREATE_NEW_CONSOLE` hay
không. Console mới vẫn được tạo ra (thấy được bằng mắt), nhưng
`GetStdHandle(STD_INPUT_HANDLE)` mà .NET Console dùng lại trỏ về handle đã
bị ghi đè đó, không phải input buffer thật của console mới - nên
`Console.ReadKey()` vẫn coi là "input đã bị redirect" và crash.

FIX THẬT (xác nhận live: tiến trình sống bình thường, không crash): KHÔNG
để Python tự redirect handle nào cả - thay vào đó nhờ `cmd.exe` tự làm
`> logfile 2>&1` NGAY BÊN TRONG console mới (`cmd /c "exe args > log 2>&1"`
chạy qua `shell=True` + `CREATE_NEW_CONSOLE`). cmd.exe chỉ ghi đè ĐÚNG 1
handle (stdout) của chính process con nó tạo ra, không đụng tới STARTUPINFO
ở tầng Python nữa - stdin của console mới giữ nguyên, thật.

Hệ quả: `self._process` (Popen) lúc này là tiến trình `cmd.exe` (wrapper),
KHÔNG PHẢI chính OBDSimulation_CLI.exe - terminate() nhầm object này chỉ
giết cmd.exe, để lại OBDSimulation_CLI.exe mồ côi vẫn giữ cổng COM (xác
nhận live qua Get-CimInstance Win32_Process). Nên sau khi spawn, phải tự dò
lại đúng tiến trình OBDSimulation_CLI.exe thật (qua psutil, so khớp cổng
COM trong cmdline - kỹ thuật giống hệt fallback-scan trong
kill_commandline_process()) rồi lưu handle CỦA NÓ (bọc bằng psutil.Process
để có chung interface is_running()/terminate()/wait()/kill() cho cả 2
nhánh có/không log_file, xem load_sim_file()).
"""

import logging
import os
import subprocess
import sys
import time

import psutil
import serial.tools.list_ports

logger = logging.getLogger(__name__)

# Khi đóng gói bằng PyInstaller, __file__ trỏ vào thư mục temp/bundle, không
# nằm cạnh file .exe đã build - dùng thư mục chứa chính exe đang chạy thay
# vào đó để SimFiles/ và OBDSimulation_CLI_.../ được tìm thấy nằm cạnh nó.
# Khi chạy trực tiếp từ .py, 2 thư mục đó nằm ở gốc project
# (Auto_reverse_DB/), cao hơn 1 cấp so với file này (Auto_reverse_DB/
# simulatorhandle/) - phải lùi lên 1 cấp bằng dirname() thứ 2, nếu không
# đường dẫn sẽ trỏ vào simulatorhandle/SimFiles không tồn tại (bug có sẵn
# từ bản gốc, xác nhận bằng os.path.exists() trả về False khi test live).
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_EXE_PATH = os.path.join(
    _BASE_DIR, "OBDSimulation_CLI_1.3.36.3", "x64", "net9.0", "OBDSimulation_CLI.exe"
)
DEFAULT_SIM_FILE = os.path.join(_BASE_DIR, "SimFiles", "CAN_default.sim")

# File .sim tham chiếu CHỨA SẴN 2 DTC test cố định (P1234/P1278, xác nhận
# live app hiển thị kèm hậu tố status byte "P1234:1E"/"P1278:01") - dùng để
# dò cách app HIỂN THỊ DTC (có/không hậu tố, chữ status dùng - History/
# Pending/...) độc lập với target thật đang reverse, xem
# process.VehicleDataCollector._probe_dtc_read_type().
DTC_INFO_SIM_FILE = os.path.join(_BASE_DIR, "SimFiles", "DTC_info.sim")

# VID:PID của mạch chuyển COM dùng cho simulator - dùng để list_simulator_ports()
# lọc đúng cổng trong danh sách toàn bộ cổng COM đang cắm trên máy.
_SIMULATOR_VID = "0483"
_SIMULATOR_PID = "2010"

_PROCESS_NAME = "OBDSimulation_CLI.exe"

# Thời gian tối đa chờ tiến trình OBDSimulation_CLI.exe thật xuất hiện sau
# khi spawn qua cmd.exe wrapper (xem load_sim_file/_find_process).
_FIND_PROCESS_TIMEOUT_SECONDS = 5.0


def list_simulator_ports():
    """Liệt kê TẤT CẢ cổng COM đang cắm khớp VID:PID của simulator (không chỉ
    cổng đầu tiên như bản cũ) - dùng để tạo 1 SimulatorControl riêng cho mỗi
    cổng khi máy cắm nhiều simulator cùng lúc và cần chạy song song."""
    matched = []
    for port in serial.tools.list_ports.comports():
        if "VID:PID=" not in port.hwid:
            continue
        for part in port.hwid.split():
            if not part.startswith("VID:PID="):
                continue
            vid, pid = part.split("=")[1].split(":")
            if vid == _SIMULATOR_VID and pid == _SIMULATOR_PID:
                matched.append(port.device)
    return matched


class SimulatorControl:
    """Bọc lại việc quản lý tiến trình OBDSimulation_CLI.exe: dò cổng COM,
    nạp file .sim, kill/reload. Handle tiến trình (self._process) và cổng
    COM (self.com) thuộc về từng instance thay vì biến global, nên khởi tạo
    nhiều instance - mỗi instance 1 cổng COM riêng - chạy song song mà
    không giẫm lên nhau.

    self._process luôn là 1 `psutil.Process` (không phải subprocess.Popen)
    trỏ tới đúng tiến trình OBDSimulation_CLI.exe thật, kể cả khi launch
    qua cmd.exe wrapper (xem module docstring) - thống nhất 1 interface
    (is_running/terminate/wait/kill) cho kill_commandline_process() dùng
    chung, không cần phân biệt 2 nhánh có/không log_file.
    """

    def __init__(self, com=None, exe_path=DEFAULT_EXE_PATH, simfile=DEFAULT_SIM_FILE):
        self.com = com
        self.exe_path = exe_path
        self.simfile = simfile
        self._process = None
        self._shell_wrapper_process = None
        self._log_console_process = None

    def load_sim_file(self, com, filepath, log_file=None, open_log_console=True):
        """Chạy OBDSimulation_CLI.exe với cổng COM + file .sim chỉ định,
        không chờ tiến trình kết thúc; giữ lại handle để lần kill kế tiếp
        kết thúc thẳng tiến trình này thay vì phải quét toàn bộ tiến trình.

        `log_file` (optional): đường dẫn file để capture STDOUT của tiến
        trình vào đó (phục vụ SimulatorAnalyzer đọc log Rx/Tx tự động, thay
        vì phải copy tay từ console). Spawn qua `cmd.exe /c "... > log
        2>&1"` trong 1 console MỚI (CREATE_NEW_CONSOLE) - xem giải thích
        đầy đủ trong module docstring về lý do KHÔNG được để Python tự
        redirect (Popen stdout=...) dù có CREATE_NEW_CONSOLE hay không, vẫn
        làm Console.ReadKey() của exe crash. Sau khi spawn, tự dò lại đúng
        tiến trình OBDSimulation_CLI.exe thật (_find_process) vì Popen ở
        đây trỏ tới cmd.exe wrapper, không phải chính exe.

        Không truyền log_file thì hành vi giữ nguyên như cũ (chạy thẳng,
        thừa hưởng console cha, không có gì bị chặn/dừng lại - lý do bản
        gốc không dùng CREATE_NO_WINDOW ở đây).

        `open_log_console`: khi True (mặc định - theo yêu cầu "mỗi lần load
        sim đều muốn thấy console"), tự mở thêm 1 cửa sổ PowerShell RIÊNG
        chạy "Get-Content -Wait" tail file log đó ngay khi có log_file, để
        luôn thấy trực tiếp Rx/Tx mỗi lần load/reload thay vì phải tự mở
        tay. Truyền False để tắt riêng cho 1 lần gọi cụ thể nếu cần.
        """
        self.com = com
        args = [com, filepath, "showdata"]
        if log_file:
            # Mỗi argument phải tự quote riêng - filepath (đường dẫn file
            # .sim riêng theo xe, vd "...Accent (HC)_G 1.6...") chứa dấu
            # cách, join bằng " ".join() không quote sẽ bị cắt cụt tại
            # khoảng trắng đầu tiên khi cmd.exe/exe parse argv, exe nhận
            # nhầm 1 phần đường dẫn làm arg đầu - dẫn tới
            # FileNotFoundException ngay khi mở file (xác nhận live: crash
            # thật, message báo đúng path bị cắt cụt tại dấu cách đầu tiên).
            quoted_args = " ".join(f'"{a}"' for a in args)
            cmd_line = f'"{self.exe_path}" {quoted_args} > "{log_file}" 2>&1'
            self._shell_wrapper_process = subprocess.Popen(
                cmd_line, shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            self._process = self._find_process()
            if self._process is None:
                logger.warning(
                    "load_sim_file: real process %s not found after spawn (com=%s)",
                    _PROCESS_NAME, com,
                )
            if open_log_console:
                tail_command = f"Get-Content -Wait -Tail 50 -Path '{log_file}'"
                self._log_console_process = subprocess.Popen(
                    ["powershell", "-NoExit", "-Command", tail_command],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
        else:
            # Không truyền log_file thì không cần cmd.exe wrapper (không có
            # gì cần redirect), nhưng VẪN cần CREATE_NEW_CONSOLE - xác nhận
            # live: nếu tiến trình Python cha tự nó không có console thật
            # (vd chạy qua 1 harness/tool nào đó), con kế thừa NGUYÊN trạng
            # thái đó dù Popen ở đây không hề truyền stdin/stdout/stderr gì
            # cả, vẫn crash ReadKey y hệt nhánh có log_file. CREATE_NEW_CONSOLE
            # đơn thuần (không kèm STARTUPINFO override handle nào) cấp hẳn
            # console mới cho con, không phụ thuộc trạng thái I/O của cha.
            raw_process = subprocess.Popen(
                [self.exe_path] + args, creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            self._process = psutil.Process(raw_process.pid)

    def _find_process(self, timeout: float = _FIND_PROCESS_TIMEOUT_SECONDS):
        """Dò trong danh sách tiến trình đang chạy để tìm đúng
        OBDSimulation_CLI.exe vừa spawn qua cmd.exe wrapper, so khớp cổng
        COM (self.com) trong command-line - kỹ thuật giống fallback-scan
        của kill_commandline_process(). Thử lặp lại trong `timeout` giây vì
        cmd.exe cần 1 chút thời gian để thật sự khởi chạy tiến trình con.
        Trả về psutil.Process nếu tìm thấy, None nếu hết thời gian.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            for proc in psutil.process_iter(["name"]):
                if proc.info["name"] != _PROCESS_NAME:
                    continue
                try:
                    cmdline = proc.cmdline()
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
                if self.com in cmdline:
                    return proc
            time.sleep(0.2)
        return None

    def kill_commandline_process(self):
        """Kết thúc OBDSimulation_CLI.exe của cổng COM thuộc instance này.
        Nếu instance tự khởi chạy nó gần nhất (trường hợp bình thường), kill
        thẳng bằng handle đó (self._process, luôn là psutil.Process trỏ
        đúng tiến trình exe thật - xem load_sim_file()) - nhanh hơn nhiều
        so với quét toàn bộ tiến trình trên mỗi lần reload. Chỉ quét tiến
        trình khi không có handle sẵn có (vd lần đầu mở app mà có phiên
        chạy cũ còn sót lại từ lần trước) - quét theo COM PORT TRONG
        COMMAND-LINE (qua psutil), không quét theo tên tiến trình, vì tên
        tiến trình giống nhau giữa các simulator đang chạy song song trên
        cổng khác - kill theo tên sẽ giết nhầm simulator khác đang chạy tốt.
        """
        if self._process is not None:
            try:
                if self._process.is_running():
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=2)
                    except psutil.TimeoutExpired:
                        self._process.kill()
            except psutil.NoSuchProcess:
                pass
            self._process = None

            if self._shell_wrapper_process is not None:
                if self._shell_wrapper_process.poll() is None:
                    self._shell_wrapper_process.terminate()
                self._shell_wrapper_process = None
            if self._log_console_process is not None and self._log_console_process.poll() is None:
                self._log_console_process.terminate()
                self._log_console_process = None
            return

        if self.com is None:
            return

        # process_iter(["name"]) rồi mới đọc cmdline riêng từng process
        # trong try/except - nếu gặp 1 tiến trình lạ (khác quyền/session)
        # không đọc được cmdline, psutil ném AccessDenied/NoSuchProcess
        # ngay trong lúc duyệt, làm crash cả vòng lặp nếu fetch cmdline
        # cùng lúc filter theo name (đã xác nhận live gặp đúng lỗi này).
        for proc in psutil.process_iter(["name"]):
            if proc.info["name"] != _PROCESS_NAME:
                continue
            try:
                cmdline = proc.cmdline()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
            if self.com in cmdline:
                proc.kill()

    def do_reload(self, com=None, log_file=None, open_log_console=True):
        """Kill session simulator cũ trên cổng COM chỉ định (hoặc cổng đã
        gắn với instance này, hoặc cổng dò được đầu tiên nếu chưa có) rồi
        nạp lại simfile mặc định. Trả về False nếu simulator chưa cắm hoặc
        có lỗi bất kỳ trong quá trình reload.

        `log_file`/`open_log_console`: xem load_sim_file() - truyền log_file
        để tự động capture log Rx/Tx ra file thay vì phải copy tay từ
        console. open_log_console mặc định True - tự mở cửa sổ PowerShell
        tail file log đó mỗi lần load/reload, theo yêu cầu luôn thấy được
        console.

        Để chạy song song nhiều simulator: gọi list_simulator_ports() 1 lần
        lấy hết các cổng đang cắm, rồi tạo/gọi 1 SimulatorControl(com=...)
        riêng cho từng cổng.
        """
        try:
            com = com or self.com or list_simulator_ports()[0]
            self.com = com
            self.kill_commandline_process()
            self.load_sim_file(com, self.simfile, log_file=log_file, open_log_console=open_log_console)
            return True
        except Exception:
            logger.warning("Simulator not connected - check COM port")
            return False

    def reload_with(self, simfile, log_file=None, open_log_console=True):
        """Chuyển sang nạp `simfile` (khác - hoặc giống - file hiện tại)
        rồi reload ngay - tiện dùng khi cần đổi mục tiêu simfile của MỘT
        instance SimulatorControl đang chạy (vd chuyển giữa các profile/tổ
        hợp Init cần test) thay vì phải kill instance cũ + tạo instance mới
        (do_reload() đã tự kill qua đúng handle của chính instance này ở
        bước đầu tiên, không cần tự kill riêng trước khi gọi hàm này)."""
        self.simfile = simfile
        return self.do_reload(log_file=log_file, open_log_console=open_log_console)
