"""CAPL code snippets for the editor and the CAPL Browser's 'Insert Template' menu.

`${n:placeholder}` marks a cursor stop; the editor replaces it with the default
text and selects the first placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Snippet:
    trigger: str
    title: str
    category: str
    body: str
    description: str = ""


SNIPPETS: tuple[Snippet, ...] = (
    # -- File skeleton ---------------------------------------------------------
    Snippet(
        "caplfile", "Full CAPL File Skeleton", "Boilerplate",
        '/*@!Encoding:65001*/\n'
        'includes\n{\n  // #include "helpers.cin"\n}\n\n'
        'variables\n{\n'
        '  msTimer ${1:cyclicTimer};\n'
        '  message ${2:0x100} ${3:txMsg};\n'
        '  int gCounter = 0;\n'
        '}\n\n'
        'on preStart\n{\n  // initialize before the bus goes active\n}\n\n'
        'on start\n{\n  setTimer(${1:cyclicTimer}, 100);\n}\n\n'
        'on timer ${1:cyclicTimer}\n{\n'
        '  output(${3:txMsg});\n'
        '  setTimer(${1:cyclicTimer}, 100);\n}\n\n'
        'on stopMeasurement\n{\n  write("Sent %d frame(s)", gCounter);\n}\n',
        "The standard skeleton: includes, variables, preStart, start, timer, stopMeasurement.",
    ),
    # -- Blocks --------------------------------------------------------------
    Snippet("variables", "variables Block", "Block",
            'variables\n{\n  ${1:int counter = 0;}\n}\n',
            "Declares a node's global variables."),
    Snippet("includes", "includes Block", "Block",
            'includes\n{\n  #include "${1:library.cin}"\n}\n',
            "Embeds a shared .cin file."),
    Snippet("struct", "struct Declaration", "Block",
            'struct ${1:MyStruct}\n{\n  byte ${2:field};\n};\n', ""),
    Snippet("enum", "enum Declaration", "Block",
            'enum ${1:State}\n{\n  ${2:kIdle} = 0,\n  kActive = 1\n};\n', ""),

    # -- Event handlers --------------------------------------------------------
    Snippet("onprestart", "on preStart", "Event",
            'on preStart\n{\n  ${1:// runs before the measurement starts}\n}\n', ""),
    Snippet("onstart", "on start", "Event",
            'on start\n{\n  ${1:// runs when the measurement starts}\n}\n', ""),
    Snippet("onstop", "on stopMeasurement", "Event",
            'on stopMeasurement\n{\n  ${1:// clean up on stop}\n}\n', ""),
    Snippet("onmessage", "on message", "Event",
            'on message ${1:*}\n{\n'
            '  write("RX ID=0x%X DLC=%d B0=0x%02X", this.id, this.dlc, this.byte(0));\n}\n',
            "Catches a CAN frame by name, ID, or '*' for all frames."),
    Snippet("ontimer", "on timer", "Event",
            'on timer ${1:t}\n{\n  ${2:// expired}\n  setTimer(${1:t}, ${3:100});\n}\n',
            "Call setTimer again inside the body to make the timer cyclic."),
    Snippet("onkey", "on key", "Event",
            "on key '${1:a}'\n{\n  ${2:write(\"Key pressed\");}\n}\n", ""),
    Snippet("onsysvar", "on sysvar", "Event",
            'on sysvar ${1:NS}::${2:Var}\n{\n'
            '  write("%s = %d", "${2:Var}", @sysvar::${1:NS}::${2:Var});\n}\n', ""),
    Snippet("onsignal", "on signal", "Event",
            'on signal ${1:SignalName}\n{\n  write("value = %f", $${1:SignalName});\n}\n', ""),
    Snippet("onenvvar", "on envVar", "Event",
            'on envVar ${1:EnvName}\n{\n  ${2:// value changed}\n}\n', ""),
    Snippet("onerrorframe", "on errorFrame", "Event",
            'on errorFrame\n{\n  write("Error frame on channel %d", this.can);\n}\n', ""),
    Snippet("onbusoff", "on busOff", "Event",
            'on busOff\n{\n  write("Bus-off! Resetting controller...");\n  resetCan();\n}\n', ""),
    Snippet("ondiagrequest", "on diagRequest", "Diagnostics",
            'on diagRequest ${1:ECU}.${2:Service}\n{\n'
            '  diagSendResponse(this.resp);\n}\n', ""),
    Snippet("ondiagresponse", "on diagResponse", "Diagnostics",
            'on diagResponse ${1:ECU}.${2:Service}\n{\n'
            '  if (diagIsNegativeResponse(this))\n'
            '    write("NRC = 0x%02X", diagGetResponseCode(this));\n'
            '  else\n'
            '    write("Positive response");\n}\n', ""),
    Snippet("onlinframe", "on linFrame", "LIN",
            'on linFrame ${1:*}\n{\n  write("LIN ID=0x%X DLC=%d", this.id, this.dlc);\n}\n', ""),
    Snippet("onfrframe", "on frFrame", "FlexRay",
            'on frFrame ${1:*}\n{\n  write("FR slot=%d cycle=%d", this.slotID, this.cycle);\n}\n', ""),
    Snippet("onethernetpacket", "on ethernetPacket", "Ethernet",
            'on ethernetPacket ${1:*}\n{\n  write("ETH %d byte(s)", this.size);\n}\n', ""),

    # -- Common patterns ----------------------------------------------------------
    Snippet("sendcyclic", "Send Cyclic Frame", "Pattern",
            'variables\n{\n  msTimer tCyclic;\n  message ${1:0x100} ${2:txMsg};\n}\n\n'
            'on start\n{\n  setTimer(tCyclic, ${3:100});\n}\n\n'
            'on timer tCyclic\n{\n'
            '  ${2:txMsg}.byte(0) = ${2:txMsg}.byte(0) + 1;\n'
            '  output(${2:txMsg});\n'
            '  setTimer(tCyclic, ${3:100});\n}\n', ""),
    Snippet("udsrequest", "Send UDS Request", "Diagnostics",
            'variables\n{\n  diagRequest ${1:ECU}.${2:ReadDataByIdentifier} req;\n}\n\n'
            "on key 'd'\n{\n"
            '  diagSetParameter(req, "DataIdentifier", ${3:0xF190});\n'
            '  diagSendRequest(req);\n}\n\n'
            'on diagResponse ${1:ECU}.${2:ReadDataByIdentifier}\n{\n'
            '  byte data[64];\n'
            '  long len;\n'
            '  len = diagGetPrimitiveData(this, data, elCount(data));\n'
            '  write("Received %d byte(s)", len);\n}\n', ""),
    Snippet("testcase", "Test Case (Test Feature Set)", "Test",
            'testcase ${1:TC_MyCheck}()\n{\n'
            '  TestCaseTitle("${1:TC_MyCheck}", "${2:Test case description}");\n'
            '  TestStep("1", "Prepare conditions");\n\n'
            '  if (TestWaitForMessage(${3:MsgName}, 1000) == 1)\n'
            '    TestStepPass("2", "Received the expected frame");\n'
            '  else\n'
            '    TestStepFail("2", "Timeout while waiting for the frame");\n}\n', ""),
    Snippet("testmodule", "Test Module Skeleton", "Test",
            'variables\n{\n  // variables shared across testcases\n}\n\n'
            'testcase ${1:TC_001}()\n{\n'
            '  TestCaseTitle("${1:TC_001}", "${2:Objective}");\n'
            '  TestStepPass("1", "OK");\n}\n\n'
            'void MainTest()\n{\n'
            '  TestModuleTitle("${3:Module name}");\n'
            '  ${1:TC_001}();\n}\n', ""),
    Snippet("forloop", "for Loop", "Control Flow",
            'for (${1:i} = 0; ${1:i} < ${2:8}; ${1:i}++)\n{\n  ${3:}\n}\n', ""),
    Snippet("switch", "switch Block", "Control Flow",
            'switch (${1:value})\n{\n'
            '  case ${2:0}:\n    ${3:}\n    break;\n\n'
            '  default:\n    break;\n}\n', ""),
    Snippet("payloadloop", "Iterate Frame Payload", "Pattern",
            'for (i = 0; i < this.dlc; i++)\n{\n'
            '  write("byte[%d] = 0x%02X", i, this.byte(i));\n}\n', ""),
)


def by_category() -> dict[str, list[Snippet]]:
    out: dict[str, list[Snippet]] = {}
    for s in SNIPPETS:
        out.setdefault(s.category, []).append(s)
    return out


def find(trigger: str) -> Snippet | None:
    for s in SNIPPETS:
        if s.trigger == trigger:
            return s
    return None


def expand(body: str) -> tuple[str, int]:
    """Strips placeholder markers, returns (text, position of the first cursor stop)."""
    import re

    cursor = -1
    out: list[str] = []
    pos = 0
    for match in re.finditer(r"\$\{(\d+):([^}]*)\}", body):
        out.append(body[pos:match.start()])
        if cursor < 0:
            cursor = sum(len(p) for p in out)
        out.append(match.group(2))
        pos = match.end()
    out.append(body[pos:])
    text = "".join(out)
    return text, (cursor if cursor >= 0 else len(text))
