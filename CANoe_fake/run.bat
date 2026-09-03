@echo off
REM Khoi dong CANoe Fake. Tu tao venv va cai PySide6 trong lan chay dau tien.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [CANoe Fake] Tao moi truong ao lan dau...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q || goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt -q || goto :error
)

".venv\Scripts\python.exe" main.py %*
goto :eof

:error
echo [CANoe Fake] Khoi tao that bai. Kiem tra Python 3.10+ da co trong PATH chua.
exit /b 1
