"""CAPL syntax dictionary: keywords, data types, event types, operators.

This module is the single "source of truth" for every other component
(lexer, parser, highlighter, completer). Add new CAPL syntax here.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Top-level declaration blocks
# ---------------------------------------------------------------------------

BLOCK_KEYWORDS: frozenset[str] = frozenset(
    {
        "variables",   # variables { ... }  – a node's global variables
        "includes",    # includes { #include "lib.cin" }
        "export",      # export variables / export function
        "import",      # import from another node
        "testcase",    # Test Feature Set
        "testfunction",
        "testfixture",
        "namespace",   # namespace for sysvars / test units
    }
)

# ---------------------------------------------------------------------------
# Control-flow keywords
# ---------------------------------------------------------------------------

CONTROL_KEYWORDS: frozenset[str] = frozenset(
    {
        "if",
        "else",
        "while",
        "for",
        "do",
        "switch",
        "case",
        "default",
        "break",
        "continue",
        "return",
        "goto",
    }
)

# ---------------------------------------------------------------------------
# Declaration / modifier keywords
# ---------------------------------------------------------------------------

DECL_KEYWORDS: frozenset[str] = frozenset(
    {
        "struct",
        "enum",
        "union",
        "typedef",
        "const",
        "static",
        "extern",
        "volatile",
        "sizeof",
        "this",
        "on",
        "using",
    }
)

# ---------------------------------------------------------------------------
# Scalar data types
# ---------------------------------------------------------------------------

SCALAR_TYPES: frozenset[str] = frozenset(
    {
        "void",
        "char",
        "byte",     # unsigned 8-bit
        "int",      # signed 16-bit
        "word",     # unsigned 16-bit
        "long",     # signed 32-bit
        "dword",    # unsigned 32-bit
        "int64",    # signed 64-bit
        "qword",    # unsigned 64-bit
        "float",
        "double",
        "enum",
    }
)

# ---------------------------------------------------------------------------
# CAPL-specific object types (bus objects, timers, diagnostics, ...)
# ---------------------------------------------------------------------------

OBJECT_TYPES: frozenset[str] = frozenset(
    {
        # Timer
        "timer",                 # second resolution
        "msTimer",               # millisecond resolution
        "mstimer",
        # CAN
        "message",
        "multiplexed_message",
        "canMessage",
        "errorFrame",
        # LIN
        "linFrame",
        "linMessage",
        "linSlaveResponse",
        "linUnconditionalFrame",
        "linEventTriggeredFrame",
        "linSporadicFrame",
        # FlexRay
        "frFrame",
        "frPDU",
        # Ethernet
        "ethernetPacket",
        "ethernetPhyState",
        # PDU / signal / service
        "pdu",
        "signal",
        "serviceEvent",
        # Diagnostics
        "diagRequest",
        "diagResponse",
        # Other
        "sysvar",
        "sysvarMember",
        "envVar",
        "association",
        "dbNode",
        "dbLookup",
        "char",
    }
)

DATA_TYPES: frozenset[str] = SCALAR_TYPES | OBJECT_TYPES

# ---------------------------------------------------------------------------
# Event types used after the `on` keyword
# ---------------------------------------------------------------------------
#: mapping event -> short description, shown in tooltips / the completer
EVENT_TYPES: dict[str, str] = {
    # --- Measurement lifecycle -------------------------------------------
    "preStart": "Runs before the measurement starts (bus not yet active)",
    "prestart": "Lowercase alias of preStart",
    "start": "Runs when the measurement starts (bus already active)",
    "preStop": "Runs right before the measurement stops",
    "stopMeasurement": "Runs when the measurement ends — used for cleanup",
    # --- Timer / key ----------------------------------------------------
    "timer": "Fires when a timer/msTimer expires",
    "key": "Fires when a key is pressed in the Write/Trace window",
    # --- CAN --------------------------------------------------------------
    "message": "Receives a CAN frame (by name, ID, or `*` for all frames)",
    "errorFrame": "Receives an error frame on the CAN bus",
    "busOff": "Node transitions to the bus-off state",
    "errorActive": "Error counter returns to the error-active range",
    "errorPassive": "Error counter exceeds the error-passive threshold",
    "warningLimit": "Error counter reaches the warning threshold (96)",
    "canOverload": "Overload frame on the CAN bus",
    # --- Signal / system variable / environment variable -----------------
    "signal": "Signal value changes",
    "signal_update": "Signal is updated (even if the value doesn't change)",
    "signal_change": "Alias of on signal",
    "sysvar": "System variable value changes",
    "sysvar_update": "System variable is written (even if the value doesn't change)",
    "envVar": "Environment variable changes",
    # --- Diagnostics -------------------------------------------------------
    "diagRequest": "Receives a diagnostic request (on the simulated ECU side)",
    "diagResponse": "Receives a diagnostic response (on the tester side)",
    # --- LIN ----------------------------------------------------------------
    "linFrame": "Receives a complete LIN frame",
    "linHeader": "Receives a LIN header (before the response part)",
    "linSlaveResponse": "Receives the response part from a LIN slave",
    "linSleepModeEvent": "LIN sleep-mode enter/exit event",
    "linWakeupFrame": "Receives a LIN wakeup frame",
    "linErrSlvNoResp": "Error: slave did not respond",
    "linErrChecksum": "Error: wrong LIN checksum",
    "linErrTransm": "LIN transmission error",
    "linErrRecSync": "LIN receive synchronization error",
    "linErrHeader": "LIN header error",
    "linSchedulerModeChange": "LIN schedule table changed",
    # --- FlexRay -------------------------------------------------------------
    "frFrame": "Receives a FlexRay frame",
    "frPDU": "Receives a FlexRay PDU",
    "frStartCycle": "Start of a FlexRay cycle",
    "frError": "FlexRay error",
    "frSymbol": "Receives a FlexRay symbol",
    "frPOCState": "FlexRay controller's POC state changes",
    # --- Ethernet -------------------------------------------------------------
    "ethernetPacket": "Receives an Ethernet packet",
    "ethernetStatus": "Ethernet link status changes",
    "ethernetPhyState": "Ethernet PHY state changes",
    # --- PDU / service ----------------------------------------------------------
    "pdu": "Receives a PDU (bus-independent)",
    "serviceEvent": "Service event (SOME/IP, AUTOSAR)",
    # --- Other --------------------------------------------------------------------
    "a429Word": "Receives an ARINC 429 word",
    "mostAmsMessage": "Receives a MOST AMS message",
    "j1939Pg": "Receives a J1939 Parameter Group",
    "j1939DTC": "Receives a J1939 DTC",
    "valueChange": "A monitored object's value changes",
}

# ---------------------------------------------------------------------------
# Built-in constants
# ---------------------------------------------------------------------------

CONSTANTS: frozenset[str] = frozenset(
    {
        # logic / math
        "TRUE", "FALSE", "NULL", "PI", "E",
        # frame direction (this.dir)
        "RX", "TX", "TXREQUEST", "Rx", "Tx",
        # Test Feature Set verdicts
        "kTestVerdictPassed",
        "kTestVerdictFailed",
        "kTestVerdictNone",
        "kTestVerdictInconclusive",
        "kTestVerdictErrorInTestSystem",
        # results of the TestWaitFor* functions
        "kEventTimeout",
        "kEventOccurred",
        # destination for writeEx / writeLineEx
        "kWriteWindow",
        "kTraceWindow",
        "kLogFile",
        # CAN frame flags
        "kCanStandardId",
        "kCanExtendedId",
        "kCanFdFlag",
        # replay state
        "kReplayStopped",
        "kReplayRunning",
        "kReplaySuspended",
        # LIN checksum
        "kLinChecksumClassic",
        "kLinChecksumEnhanced",
    }
)

# ---------------------------------------------------------------------------
# `this` properties per event context
# ---------------------------------------------------------------------------
#: used by the completer: typing `this.` inside `on message` suggests id/dlc/byte...
THIS_MEMBERS: dict[str, dict[str, str]] = {
    "message": {
        "id": "dword — CAN identifier (flag bits stripped)",
        "ID": "dword — alias of id",
        "dlc": "byte — Data Length Code",
        "DLC": "byte — alias of dlc",
        "can": "byte — CAN channel number (1..n)",
        "CAN": "byte — alias of can",
        "dir": "byte — direction: RX (0) or TX (1)",
        "DIR": "byte — alias of dir",
        "rtr": "byte — Remote Transmission Request flag",
        "RTR": "byte — alias of rtr",
        "type": "dword — frame type (standard/extended)",
        "time": "dword — timestamp (10 µs tick)",
        "TIME": "dword — alias of time",
        "simulated": "byte — 1 if the frame was generated by a simulated node",
        "msgChannel": "byte — channel the frame was received on",
        "byte(x)": "byte — access payload byte x (0..7)",
        "word(x)": "word — read 2 bytes starting at word position x",
        "dword(x)": "dword — read 4 bytes starting at dword position x",
        "qword(x)": "qword — read 8 bytes",
        "long(x)": "long — read 4 signed bytes",
        "int(x)": "int — read 2 signed bytes",
        "FDF": "byte — CAN FD flag",
        "BRS": "byte — Bit Rate Switch flag (CAN FD)",
        "ESI": "byte — Error State Indicator flag (CAN FD)",
    },
    "diagRequest": {
        "primitiveSize": "long — total primitive size (bytes)",
        "responseCode": "long — response code",
        "resp": "diagResponse — the matching response",
        "byte(x)": "byte — byte x of the raw data",
    },
    "diagResponse": {
        "primitiveSize": "long — total primitive size (bytes)",
        "responseCode": "long — NRC if this is a negative response",
        "byte(x)": "byte — byte x of the raw data",
    },
    "linFrame": {
        "id": "dword — LIN frame ID (0..0x3F)",
        "dlc": "byte — number of data bytes",
        "byte(x)": "byte — payload byte x",
        "time": "dword — timestamp",
        "dir": "byte — transfer direction",
        "checksum": "byte — checksum value",
        "SleepModeEvent": "byte — sleep-mode event",
    },
    "frFrame": {
        "slotID": "dword — slot ID within the FlexRay cycle",
        "cycle": "byte — cycle number",
        "dlc": "byte — data length",
        "byte(x)": "byte — payload byte x",
        "channelMask": "byte — channel A/B",
    },
    "ethernetPacket": {
        "size": "long — packet length (bytes)",
        "byte(x)": "byte — packet byte x",
        "dir": "byte — transfer direction",
        "channel": "byte — Ethernet channel",
    },
    "sysvar": {
        "name": "char[] — system variable name",
        "namespace": "char[] — namespace containing the variable",
    },
    "errorFrame": {
        "can": "byte — CAN channel",
        "time": "dword — timestamp",
        "dir": "byte — direction",
    },
    "key": {},
    "timer": {},
}

# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

#: sorted longest-first so the lexer matches greedily (maximal munch)
OPERATORS: tuple[str, ...] = tuple(
    sorted(
        (
            ">>=", "<<=", "...",
            "==", "!=", "<=", ">=", "&&", "||", "<<", ">>",
            "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
            "++", "--", "->", "::",
            "+", "-", "*", "/", "%", "=", "<", ">", "!", "~", "&", "|", "^",
            "?", ":", ".", ",", ";", "@", "$",
            "(", ")", "[", "]", "{", "}",
        ),
        key=len,
        reverse=True,
    )
)

OPEN_BRACKETS: dict[str, str] = {"(": ")", "[": "]", "{": "}"}
CLOSE_BRACKETS: dict[str, str] = {v: k for k, v in OPEN_BRACKETS.items()}

# ---------------------------------------------------------------------------
# Combined sets
# ---------------------------------------------------------------------------

ALL_KEYWORDS: frozenset[str] = (
    BLOCK_KEYWORDS | CONTROL_KEYWORDS | DECL_KEYWORDS | DATA_TYPES
)


def is_keyword(word: str) -> bool:
    return word in ALL_KEYWORDS


def is_type(word: str) -> bool:
    return word in DATA_TYPES


def is_event_type(word: str) -> bool:
    return word in EVENT_TYPES


def this_members_for(event_type: str) -> dict[str, str]:
    """Return the valid `this.` properties for a given event type."""
    if event_type in THIS_MEMBERS:
        return THIS_MEMBERS[event_type]
    # numeric message ID / `*` selectors still belong to the message context
    if event_type.startswith("message"):
        return THIS_MEMBERS["message"]
    return {}
