# CANoe Fake — Phase 1

A simulated **Vector CANoe** user interface written in Python + PySide6, with
a **complete CAPL language layer**: syntax highlighting, code completion, a
lexer, an AST-producing parser, and semantic checks.

> Not affiliated with Vector Informatik GmbH. This is a learning / prototyping
> tool, **not for real bus measurement**.

---

## 1. Running it

```bat
run.bat
```

The first run creates a `.venv` and installs `PySide6` automatically. Or do it
manually:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

Command-line options:

```bat
main.py --workspace D:\path\to\capl\folder
```

Run the tests:

```bat
.venv\Scripts\python.exe -m pytest
```

---

## 2. What's in the UI

Switch between **desktops** using the tab bar at the bottom of the window (or
`Ctrl+1..6`), just like CANoe.

| Desktop | Contents |
|---|---|
| **Measurement Setup** | Data-flow diagram: bus → filter → Trace / Statistics / Write / Logging. Double-click a block to open the matching window. |
| **Simulation Setup** | Network diagram: bus line with 120 Ω termination resistors, ECU / simulated nodes hanging off the bus. Double-click a node to open its CAPL file. |
| **Trace** | Real-time list of bus events: Time, Chn, ID, Name, Dir, DLC, Data, Node. Filterable by text and by event type, with freeze display and auto-scroll. |
| **CAPL Browser** | File tree + outline, multi-tab editor, build problems list. |
| **Diagnostics** | UDS service tree per ECU, send requests, view decoded responses with NRC, diagnostic trace. |
| **Test** | Test Module tree scanned from real CAPL source, runs and produces a Test Report with verdicts. |

Two docked windows are shared across every desktop:

- **Write Window** (`Alt+1`) — 4 tabs: System, CAPL, Diagnostics, Test.
- **Statistics** (`Alt+2`) — bus load, frames/s, Tx/Rx, error frames, a load-over-time chart.

Main shortcuts: `F9` starts the measurement, `F8` pauses, `Ctrl+F9` stops,
`F7` compiles the CAPL file, `F5` runs the Test Module, `F1` opens the CAPL
syntax reference, `Ctrl+L` clears the Trace.

---

## 3. The CAPL language layer

Everything lives in `canoe_fake/capl/`, **with no Qt dependency** — reusable
in Phase 2 or from a CLI script.

```python
from canoe_fake.capl import compile_source

result = compile_source(open("Engine.can", encoding="utf-8").read(), "Engine.can")

result.unit          # AST — CaplFile
result.diagnostics   # errors/warnings, with line/column/length
result.symbols       # outline tree: functions, handlers, variables, testcases
result.included      # symbols pulled in from #included .cin files
```

### Components

| File | Role |
|---|---|
| `keywords.py` | **71 keywords + data types**, **49 event types**, **28 built-in constants**, **52 `this.` properties** across 10 event contexts, the operator table. |
| `builtins.py` | **254 built-in functions** with signature, return type, and description, grouped into **18 categories** (Output, String, Math, Bit/Memory, Timer, CAN/Bus, Signal, System Variable, Diagnostics, Test Feature Set, File I/O, Panel, Logging/Replay, Measurement, LIN, FlexRay, Ethernet, J1939). |
| `lexer.py` | Tokenizer that keeps trivia so the highlighter and parser share one analysis pass. |
| `parser.py` | Recursive-descent parser → AST, with panic-mode error recovery. |
| `ast_nodes.py` | AST node definitions; every node carries `line`/`column`. |
| `analyzer.py` | Semantic checks + builds the outline tree. |
| `includes.py` | Recursively resolves `#include` (cycle-safe) so functions in `.cin` files are treated as already existing. |
| `diagnostics.py` | `Diagnostic` / `DiagnosticBag` with 4 severities: Error, Warning, Info, Hint. |
| `snippets.py` | 28 code snippets for the CAPL Browser's **Insert Template** menu. |

### Supported syntax

- Top-level blocks: `includes`, `variables`, `export variables`, `struct`, `enum`,
  function definitions, `testcase`, `testfunction`.
- Event handlers: 49 types — CAN (`on message`, `on errorFrame`, `on busOff`,
  `on errorPassive`…), timer, key, signal, sysvar, envVar, diagnostics, LIN,
  FlexRay, Ethernet, PDU, J1939, MOST, ARINC 429.
- Declarations with a selector: `message 0x100 tx;`, `message CAN1.EngineData rx;`,
  `diagRequest Body.Reset req;`, multi-dimensional arrays, initializer lists.
- Expressions: the full 10 operator-precedence levels, ternary, casts `(byte)x`,
  `sizeof`, postfix `++/--`, member access `a.b`, `a->b`, `a[i]`, function calls,
  `this.byte(0)`, `@sysvar::NS::Var`, `$SignalName`, scoped names `A::B::C`.
- Statements: `if/else`, `while`, `do…while`, `for`, `switch/case/default`,
  `break`, `continue`, `return`, `goto` + labels.

### Errors the analyzer catches

| Code | Meaning |
|---|---|
| `C0001`–`C0005` | Lexical errors: unterminated comment/string/char literal, invalid hex number. |
| `C1001`–`C1018` | Syntax errors, with a position and the missing character. |
| `C2001`, `C2002` | Unknown event type (with a "did you mean…" hint), event with an unexpected selector. |
| `C3001`, `C3002` | Duplicate global variable / function name. |
| `C3004` | Function declares a return type but is missing `return`. |
| `C3005`, `C3006` | `on timer X` where `X` isn't declared, or isn't a timer type. |
| `C3008` | Using `this` outside an event handler. |
| `C3009` | Invalid `this.` property for the current event type. |
| `C3010` | Function called with the wrong number of arguments. |
| `C3011` | Undefined function (with a closest-name suggestion). |
| `C3012` | `setTimer()` called with a non-timer variable. |
| `C3013`, `C3014` | Variable shadowing one from an included file; included file not found. |

### Editor

Line numbers (with error/warning dots), lexer-based highlighting, red/yellow
wavy underlines for errors, tooltips showing error descriptions or built-in
function signatures, bracket matching, auto-indent, auto-closing
brackets/quotes, `Ctrl+/` to toggle comments, `Ctrl+Space` for code
completion, `Ctrl+G` to go to a line.

Completion is context-aware: typing `this.` inside `on message` only shows
the valid CAN-frame properties; inside `on diagResponse` it shows the
diagnostic primitive's properties.

### Syntax reference

`F1` (or **Tools → CAPL Syntax Reference**) opens a window listing **484
entries**: every keyword, type, event, `this` property, constant, built-in
function, and snippet — searchable by name or description, with an
**Insert into Editor** button.

---

## 4. Directory layout

```text
CANoe_fake/
├── main.py                     # entry point
├── run.bat                     # creates the venv + runs the app
├── requirements.txt
├── capl/                       # sample CAPL workspace
│   ├── Engine.can              # simulated engine node (timer, output, sysvar)
│   ├── ABS.can                 # frame reception, arrays, bit ops, busOff/errorFrame
│   ├── Gateway.can             # struct, enum, switch, routes between 2 networks
│   ├── Tester.can              # UDS: diagRequest/diagResponse, NRC, TesterPresent
│   ├── TestModule.can          # 4 testcases for the Test Feature Set
│   └── Helpers.cin             # shared library (CRC-8, Clamp…)
├── canoe_fake/
│   ├── capl/                   # THE LANGUAGE LAYER — no Qt dependency
│   ├── model/                  # bus database, configuration, signal codec
│   │   ├── database.py         # NetworkDef, NodeDef, MessageDef, SignalDef, DiagEcu
│   │   └── codec.py            # Intel/Motorola, factor/offset, signed/unsigned
│   ├── backend/                # THE BOUNDARY FOR PHASE 2
│   │   ├── base.py             # MeasurementBackend (abstract) + BusEvent
│   │   └── simulated.py        # the simulated engine used in Phase 1
│   └── ui/
│       ├── main_window.py      # main window, menus, toolbars, desktops
│       ├── theme.py            # CANoe-style color palette + stylesheet
│       ├── icons.py            # icons drawn with QPainter, no image files needed
│       ├── capl/               # editor, highlighter, completer, browser
│       ├── windows/            # Trace, Write, Statistics, Diagnostics, Test, Setup
│       └── dialogs/            # CAPL syntax reference
└── tests/                      # 64 tests for the lexer, parser, analyzer, codec, UI
```

---

## 5. Phase 2 — where to plug in your framework

The UI talks **only** to `canoe_fake.backend.base.MeasurementBackend`. To swap
the simulated engine for a real framework:

```python
from canoe_fake.backend.base import (BusEvent, Direction, EventKind,
                                     MeasurementBackend)

class MyBackend(MeasurementBackend):
    def _do_start(self, resumed: bool) -> None:
        ...   # open channels, load nodes, start receiving frames

    def _do_pause(self) -> None: ...
    def _do_stop(self) -> None: ...

    def send_frame(self, channel, can_id, data, name="", is_extended=False): ...
    def send_diag_request(self, ecu, request): ...
    def set_sysvar(self, qualified_name, value): ...
    def get_sysvar(self, qualified_name): ...
    def write_line(self, text, source="CAPL"): ...
```

When a new frame arrives, emit the signal:

```python
self.events_received.emit([BusEvent(
    timestamp=t, kind=EventKind.CAN_FRAME, channel=1, can_id=0x100,
    name="EngineData", direction=Direction.RX, dlc=8, data=payload)])
```

Then pass it to the main window:

```python
MainWindow(config=my_config, backend=MyBackend())
```

No widget needs to change.

### Three remaining extension points

1. **Load a real database** — replace `canoe_fake/model/database.py::demo_configuration()`
   with a `.dbc`/`.arxml` loader; the UI only depends on the dataclasses in that file.
2. **Execute CAPL** — `result.unit` is already a full AST with `line`/`column`
   on every node; write an interpreter that walks this tree (start at:
   `EventHandler` → `Block` → `Stmt`).
3. **Run real tests** — replace `_SimulatedRunner` in
   `canoe_fake/ui/windows/test_feature_set.py` with a real execution engine;
   the module tree and report plumbing stay the same.

---

## 6. Known limitations of Phase 1

- **CAPL code is not executed.** The parser produces an AST and reports
  syntax/semantic errors, but there is no interpreter yet. The Test window
  simulates the test progression and notes that explicitly in the report.
- **Bus data is simulated** — generated from a simple vehicle model in
  `backend/simulated.py`, not connected to real hardware.
- **Message/signal/ECU names from the database aren't verified** during CAPL
  compilation (the analyzer reports them at Info level, code `C3100`, rather
  than as an error, since no real database is loaded).
- **`.cfg` files can't be read/written yet** — the configuration is built in
  code, in `model/database.py`.
- No Graphics window, Panel Designer, Interactive Generator, or Logging block
  yet (out of scope for the agreed Phase 1).
