"""Data model simulating a CAN database (equivalent to CANoe's .dbc file).

Phase 2 can replace this layer with a real .dbc/.arxml loader without touching
the UI — the UI only depends on the dataclasses defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ByteOrder(str, Enum):
    INTEL = "Intel"          # little-endian
    MOTOROLA = "Motorola"    # big-endian


@dataclass(frozen=True)
class SignalDef:
    name: str
    start_bit: int
    bit_length: int
    byte_order: ByteOrder = ByteOrder.INTEL
    is_signed: bool = False
    factor: float = 1.0
    offset: float = 0.0
    minimum: float = 0.0
    maximum: float = 0.0
    unit: str = ""
    comment: str = ""
    value_table: dict[int, str] = field(default_factory=dict)

    def raw_to_phys(self, raw: int) -> float:
        return raw * self.factor + self.offset

    def phys_to_raw(self, phys: float) -> int:
        if self.factor == 0:
            return 0
        return int(round((phys - self.offset) / self.factor))

    def format_value(self, phys: float) -> str:
        raw = self.phys_to_raw(phys)
        if raw in self.value_table:
            return f"{self.value_table[raw]} ({raw})"
        text = f"{phys:.3f}".rstrip("0").rstrip(".")
        return f"{text} {self.unit}".strip()


@dataclass(frozen=True)
class MessageDef:
    name: str
    can_id: int
    dlc: int
    sender: str = ""
    cycle_time_ms: int = 0        # 0 ⇒ event-driven only
    is_extended: bool = False
    comment: str = ""
    signals: tuple[SignalDef, ...] = ()

    @property
    def id_text(self) -> str:
        return f"0x{self.can_id:08X}x" if self.is_extended else f"0x{self.can_id:03X}"

    def signal(self, name: str) -> SignalDef | None:
        for s in self.signals:
            if s.name == name:
                return s
        return None


@dataclass(frozen=True)
class NodeDef:
    name: str
    kind: str = "ECU"             # ECU | Simulated | Tester | Gateway
    description: str = ""
    tx_messages: tuple[str, ...] = ()
    rx_messages: tuple[str, ...] = ()
    capl_file: str = ""
    address: int = 0              # diagnostic address (if any)


@dataclass(frozen=True)
class NetworkDef:
    name: str
    bus_type: str = "CAN"         # CAN | CAN FD | LIN | FlexRay | Ethernet
    channel: int = 1
    baudrate: int = 500_000
    data_baudrate: int = 2_000_000
    database: str = ""
    nodes: tuple[NodeDef, ...] = ()
    messages: tuple[MessageDef, ...] = ()

    @property
    def baudrate_text(self) -> str:
        return f"{self.baudrate // 1000} kBaud"

    def message_by_id(self, can_id: int) -> MessageDef | None:
        for m in self.messages:
            if m.can_id == can_id:
                return m
        return None

    def message_by_name(self, name: str) -> MessageDef | None:
        for m in self.messages:
            if m.name == name:
                return m
        return None


@dataclass
class SystemVariable:
    namespace: str
    name: str
    var_type: str = "int"         # int | float | string | data
    value: float | int | str = 0
    minimum: float = 0.0
    maximum: float = 0.0
    unit: str = ""
    comment: str = ""

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}::{self.name}" if self.namespace else self.name


@dataclass
class DiagService:
    """A UDS diagnostic service in the simulated CDD/ODX file."""
    name: str
    sid: int
    sub_function: int | None = None
    request_bytes: tuple[int, ...] = ()
    response_bytes: tuple[int, ...] = ()
    description: str = ""

    @property
    def request_text(self) -> str:
        return " ".join(f"{b:02X}" for b in self.request_bytes)

    @property
    def response_text(self) -> str:
        return " ".join(f"{b:02X}" for b in self.response_bytes)


@dataclass
class DiagEcu:
    name: str
    request_id: int
    response_id: int
    description: str = ""
    services: list[DiagService] = field(default_factory=list)


@dataclass
class Configuration:
    """The whole open configuration — equivalent to a CANoe .cfg file."""
    name: str = "Untitled"
    path: str = ""
    networks: list[NetworkDef] = field(default_factory=list)
    system_variables: list[SystemVariable] = field(default_factory=list)
    diag_ecus: list[DiagEcu] = field(default_factory=list)
    modified: bool = False

    @property
    def title(self) -> str:
        return f"{self.name}{' *' if self.modified else ''}"

    def all_messages(self) -> list[MessageDef]:
        out: list[MessageDef] = []
        for net in self.networks:
            out.extend(net.messages)
        return out

    def all_nodes(self) -> list[NodeDef]:
        out: list[NodeDef] = []
        for net in self.networks:
            out.extend(net.nodes)
        return out

    def network(self, name: str) -> NetworkDef | None:
        for net in self.networks:
            if net.name == name:
                return net
        return None

    def sysvar(self, qualified: str) -> SystemVariable | None:
        for v in self.system_variables:
            if v.qualified_name == qualified:
                return v
        return None


# ---------------------------------------------------------------------------
# Sample configuration — simulates a demo vehicle like CANoe's Sample
# Configuration
# ---------------------------------------------------------------------------

def demo_configuration() -> Configuration:
    engine_data = MessageDef(
        name="EngineData", can_id=0x100, dlc=8, sender="Engine", cycle_time_ms=100,
        comment="Engine data, sent every 100 ms",
        signals=(
            SignalDef("EngineSpeed", 0, 16, factor=0.25, unit="rpm",
                      minimum=0, maximum=8000, comment="Crankshaft speed"),
            SignalDef("EngineTemp", 16, 8, factor=1.0, offset=-40, unit="degC",
                      minimum=-40, maximum=215),
            SignalDef("ThrottlePos", 24, 8, factor=0.4, unit="%", minimum=0, maximum=100),
            SignalDef("EngineState", 32, 4, value_table={0: "Off", 1: "Cranking",
                                                         2: "Running", 3: "Fault"}),
            SignalDef("OilPressure", 40, 8, factor=0.05, unit="bar", minimum=0, maximum=12),
        ),
    )
    abs_data = MessageDef(
        name="ABSdata", can_id=0x1A0, dlc=8, sender="ABS", cycle_time_ms=20,
        comment="Wheel speeds and ABS state",
        signals=(
            SignalDef("WheelSpeedFL", 0, 12, factor=0.1, unit="km/h", maximum=350),
            SignalDef("WheelSpeedFR", 12, 12, factor=0.1, unit="km/h", maximum=350),
            SignalDef("WheelSpeedRL", 24, 12, factor=0.1, unit="km/h", maximum=350),
            SignalDef("WheelSpeedRR", 36, 12, factor=0.1, unit="km/h", maximum=350),
            SignalDef("ABSActive", 48, 1, value_table={0: "Inactive", 1: "Active"}),
        ),
    )
    gear_box = MessageDef(
        name="GearBoxInfo", can_id=0x3FC, dlc=4, sender="Gateway", cycle_time_ms=200,
        signals=(
            SignalDef("Gear", 0, 4, value_table={0: "P", 1: "R", 2: "N", 3: "D", 4: "S"}),
            SignalDef("EcoMode", 4, 1, value_table={0: "Off", 1: "On"}),
            SignalDef("ShiftRequest", 8, 8),
        ),
    )
    light_state = MessageDef(
        name="LightState", can_id=0x470, dlc=2, sender="Body", cycle_time_ms=500,
        signals=(
            SignalDef("HeadLight", 0, 1, value_table={0: "Off", 1: "On"}),
            SignalDef("FlashLight", 1, 1, value_table={0: "Off", 1: "On"}),
            SignalDef("Brightness", 8, 8, factor=0.5, unit="%", maximum=100),
        ),
    )
    door_status = MessageDef(
        name="DoorStatus", can_id=0x520, dlc=1, sender="Body",
        comment="Sent only on change (event-driven)",
        signals=(
            SignalDef("DoorFL", 0, 1, value_table={0: "Closed", 1: "Open"}),
            SignalDef("DoorFR", 1, 1, value_table={0: "Closed", 1: "Open"}),
            SignalDef("Locked", 4, 1, value_table={0: "Unlocked", 1: "Locked"}),
        ),
    )
    diag_req = MessageDef(name="DiagRequest_Body", can_id=0x710, dlc=8,
                          sender="Tester", comment="ISO-TP request to the Body ECU")
    diag_res = MessageDef(name="DiagResponse_Body", can_id=0x718, dlc=8,
                          sender="Body", comment="ISO-TP response from the Body ECU")

    powertrain = NetworkDef(
        name="CAN 1 — Powertrain", bus_type="CAN", channel=1, baudrate=500_000,
        database="PowerTrain.dbc",
        nodes=(
            NodeDef("Engine", "Simulated", "Simulated engine node",
                    tx_messages=("EngineData",), capl_file="Engine.can"),
            NodeDef("ABS", "Simulated", "Simulated ABS braking system node",
                    tx_messages=("ABSdata",), rx_messages=("EngineData",),
                    capl_file="ABS.can"),
            NodeDef("Gateway", "Gateway", "Forwards traffic between Powertrain and Comfort",
                    tx_messages=("GearBoxInfo",),
                    rx_messages=("EngineData", "ABSdata"), capl_file="Gateway.can"),
        ),
        messages=(engine_data, abs_data, gear_box),
    )
    comfort = NetworkDef(
        name="CAN 2 — Comfort", bus_type="CAN FD", channel=2, baudrate=500_000,
        data_baudrate=2_000_000, database="Comfort.dbc",
        nodes=(
            NodeDef("Body", "ECU", "Real body ECU on the test bench",
                    tx_messages=("LightState", "DoorStatus", "DiagResponse_Body"),
                    address=0x718),
            NodeDef("Tester", "Tester", "Diagnostic tester node",
                    tx_messages=("DiagRequest_Body",), capl_file="Tester.can",
                    address=0x710),
        ),
        messages=(light_state, door_status, diag_req, diag_res),
    )

    sysvars = [
        SystemVariable("Engine", "RPM", "float", 800.0, 0, 8000, "rpm",
                       "Engine speed shown on the panel"),
        SystemVariable("Engine", "Temperature", "float", 82.0, -40, 215, "degC"),
        SystemVariable("Engine", "IgnitionOn", "int", 1, 0, 1, "",
                       "Ignition switch"),
        SystemVariable("Vehicle", "Speed", "float", 0.0, 0, 350, "km/h"),
        SystemVariable("Vehicle", "Gear", "int", 0, 0, 5),
        SystemVariable("Body", "HeadLight", "int", 0, 0, 1),
        SystemVariable("Body", "DoorOpen", "int", 0, 0, 1),
        SystemVariable("Test", "CycleCount", "int", 0, 0, 1_000_000),
    ]

    body_ecu = DiagEcu(
        name="Body", request_id=0x710, response_id=0x718,
        description="Body ECU — supports UDS over ISO-TP",
        services=[
            DiagService("DiagnosticSessionControl_Default", 0x10, 0x01,
                        (0x10, 0x01), (0x50, 0x01, 0x00, 0x32, 0x01, 0xF4),
                        "Switch back to the default diagnostic session"),
            DiagService("DiagnosticSessionControl_Extended", 0x10, 0x03,
                        (0x10, 0x03), (0x50, 0x03, 0x00, 0x32, 0x01, 0xF4),
                        "Switch to the extended session"),
            DiagService("ECUReset_HardReset", 0x11, 0x01,
                        (0x11, 0x01), (0x51, 0x01), "Restart the ECU"),
            DiagService("ReadDataByIdentifier_VIN", 0x22, None,
                        (0x22, 0xF1, 0x90),
                        (0x62, 0xF1, 0x90) + tuple(b"WVWZZZ1JZXW000001"),
                        "Read the VIN (DID 0xF190)"),
            DiagService("ReadDataByIdentifier_SwVersion", 0x22, None,
                        (0x22, 0xF1, 0x95), (0x62, 0xF1, 0x95, 0x01, 0x04, 0x02),
                        "Read the software version (DID 0xF195)"),
            DiagService("ReadDTCInformation", 0x19, 0x02,
                        (0x19, 0x02, 0xFF),
                        (0x59, 0x02, 0xFF, 0x90, 0x12, 0x34, 0x08),
                        "Read DTCs by status"),
            DiagService("ClearDiagnosticInformation", 0x14, None,
                        (0x14, 0xFF, 0xFF, 0xFF), (0x54,), "Clear all DTCs"),
            DiagService("SecurityAccess_RequestSeed", 0x27, 0x01,
                        (0x27, 0x01), (0x67, 0x01, 0xA5, 0x5A, 0x12, 0x34),
                        "Request a seed to unlock security access"),
            DiagService("TesterPresent", 0x3E, 0x00,
                        (0x3E, 0x00), (0x7E, 0x00), "Keep the diagnostic session alive"),
            DiagService("RoutineControl_StartSelfTest", 0x31, 0x01,
                        (0x31, 0x01, 0x02, 0x03), (0x71, 0x01, 0x02, 0x03, 0x00),
                        "Run a self-test routine"),
        ],
    )

    return Configuration(
        name="DemoVehicle.cfg",
        networks=[powertrain, comfort],
        system_variables=sysvars,
        diag_ecus=[body_ecu],
    )
