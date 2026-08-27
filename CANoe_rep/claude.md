Markdown
# Project Plan: CAPL Syntax Learning & Mock Workspace Generator

## Objective
Build a lightweight, zero-dependency local workspace in VS Code to learn and practice CAPL (CAN Access Programming Language) syntax without needing a CANoe license or real execution engine.

## Target Environment & Tools
- VS Code
- Extensions: CAPL Language Support / C/C++
- Language Focus: CAPL Syntax, Event-driven structures, CAN/UDS message handling patterns.

---

## Tasks for Claude Code Execution

### Task 1: Project Structure Setup
Create the following file and directory structure:
```text
capl-learning-workspace/
├── .vscode/
│   ├── settings.json
│   └── extensions.json
├── templates/
│   └── capl_template.can
├── modules/
│   ├── 01_basics_variables.can
│   ├── 02_events_and_timers.can
│   ├── 03_can_message_handling.can
│   ├── 04_uds_diagnostics.can
│   └── 05_system_variables.can
└── README.md
Task 2: VS Code Workspace Configuration
.vscode/extensions.json: Recommend relevant CAPL syntax extensions.

Insert capl-language-support or C/C++ fallback extensions.

.vscode/settings.json: Configure file association for .can and .cin files to map to c or capl syntax highlighting, and set tab indentation to 2 spaces.

Task 3: Generate Practice CAPL Files
Generate the following modular .can files containing syntax examples and inline practice tasks (// TODO: items):

templates/capl_template.can: Standard CAPL boilerplate containing variables, on preStart, on start, on timer, on message, on key, and on stopMeasurement.

modules/01_basics_variables.can: Practice with data types (byte, word, dword, int, long, double), arrays, msTimer, and message declarations.

modules/02_events_and_timers.can: Practice with single-shot and recurring timers (setTimer, cancelTimer, on timer).

modules/03_can_message_handling.can: Practice with CAN frame manipulation (output(), this.id, this.byte(x), this.dlc, this.dir).

modules/04_uds_diagnostics.can: Practice with UDS/TP concepts (diagRequest, diagResponse, diagGetParameter, ISO-TP message handling).

modules/05_system_variables.can: Practice with sysvar syntax (on sysvar, sysGetVariableInt, @sysvar::...).

Task 4: Generate Interactive README.md
Create a README.md file in Vietnamese explaining:

How to open the workspace in VS Code.

How to split the VS Code editor layout to simulate the CANoe CAPL Browser UI.

Essential CAPL syntax rules summary table.

Instructions for Claude Code Engine
Execute the task sequentially from Task 1 to Task 4.

Make sure all .can files contain valid CAPL syntax with clear Vietnamese comment explanations and // TODO: exercises for the user to type manually.

Use UTF-8 encoding for all created files.


---

### Cách dùng file này với Claude Code:
1. Tạo thư mục mới: `mkdir capl-workspace && cd capl-workspace`
2. Tạo file `CLAUDE.md` và dán toàn bộ đoạn code trên vào.
3. Chạy lệnh:
   ```bash
   claude "Read CLAUDE.md and execute all tasks to build the CAPL learning workspace"
Sau khi Claude Code chạy xong, bạn mở thư mục bằng VS Code (code .) là có sẵn một bộ bài tập CAPL phân cấp kèm cấu hình môi trường gõ code.