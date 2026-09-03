"""Engine đo giả lập — sinh lưu lượng bus "như thật" để UI có dữ liệu sống.

Mô hình vật lý rất đơn giản (động cơ, tốc độ xe, đèn, cửa) nhưng đủ để Trace,
Graphics, Statistics và Data window hoạt động giống CANoe thật.

Phase 2: thay lớp này bằng backend nối vào framework thật, giữ nguyên API của
`MeasurementBackend`.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QElapsedTimer, Qt, QTimer

from ..model import codec
from ..model.database import Configuration, MessageDef, NetworkDef
from .base import (BusEvent, BusStatistics, Direction, EventKind,
                   MeasurementBackend, MeasurementState)

#: chu kỳ nhịp mô phỏng (ms) — 20 ms cho cảm giác mượt mà không ngốn CPU
TICK_MS = 20
STATS_INTERVAL_MS = 500


class _MessageScheduler:
    """Theo dõi thời điểm phát kế tiếp của một message tuần hoàn."""

    __slots__ = ("message", "network", "next_due", "jitter_ms")

    def __init__(self, message: MessageDef, network: NetworkDef) -> None:
        self.message = message
        self.network = network
        self.jitter_ms = max(1, message.cycle_time_ms // 20)
        self.next_due = random.uniform(0.0, message.cycle_time_ms / 1000.0)

    def due(self, now: float) -> bool:
        return now >= self.next_due

    def reschedule(self, now: float) -> None:
        jitter = random.uniform(-self.jitter_ms, self.jitter_ms) / 1000.0
        self.next_due = now + self.message.cycle_time_ms / 1000.0 + jitter


class _VehicleModel:
    """Mô hình xe tối giản: quyết định giá trị signal theo thời gian."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.rpm = 800.0
        self.speed = 0.0
        self.throttle = 0.0
        self.temp = 24.0
        self.gear = 0
        self.oil_pressure = 1.4
        self.head_light = 0
        self.door_open = 0
        self.abs_active = 0
        self.ignition = 1
        self._phase = random.uniform(0, math.tau)

    def step(self, t: float, dt: float) -> None:
        # ga theo hình sin để đồ thị nhìn có nhịp
        self._phase += dt * 0.35
        target_throttle = 30.0 + 28.0 * math.sin(self._phase) \
            + 12.0 * math.sin(self._phase * 2.7)
        self.throttle += (max(0.0, target_throttle) - self.throttle) * min(1.0, dt * 3.0)

        target_rpm = 800.0 + self.throttle * 62.0
        self.rpm += (target_rpm - self.rpm) * min(1.0, dt * 2.2)
        self.rpm += random.uniform(-6.0, 6.0)
        self.rpm = max(600.0, min(7200.0, self.rpm))

        target_speed = max(0.0, (self.rpm - 800.0) / 42.0)
        self.speed += (target_speed - self.speed) * min(1.0, dt * 1.1)
        self.speed = max(0.0, min(240.0, self.speed))

        self.temp += (92.0 - self.temp) * min(1.0, dt * 0.05)
        self.oil_pressure = 1.2 + self.rpm / 2600.0

        if self.speed < 5:
            self.gear = 1 if self.throttle > 5 else 0
        else:
            self.gear = min(4, 1 + int(self.speed // 45))

        # phanh gấp ngẫu nhiên -> ABS kích hoạt trong chốc lát
        self.abs_active = 1 if (self.speed > 60 and random.random() < 0.004) else 0
        if random.random() < 0.002:
            self.head_light ^= 1
        if random.random() < 0.0015:
            self.door_open ^= 1


class SimulatedBackend(MeasurementBackend):
    """Engine giả lập chạy trên QTimer của luồng GUI."""

    def __init__(self, config: Configuration, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.vehicle = _VehicleModel()

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(STATS_INTERVAL_MS)
        self._stats_timer.timeout.connect(self._emit_statistics)

        self._clock = QElapsedTimer()
        self._base_time = 0.0
        self._last_tick = 0.0

        self._schedulers: list[_MessageScheduler] = []
        self._stats: dict[int, BusStatistics] = {}
        self._window_counts: dict[int, int] = {}
        self._window_bits: dict[int, int] = {}

        self._sysvars: dict[str, object] = {}
        self._pending_diag: list[tuple[float, str, bytes]] = []

        self.reload_configuration(config)

    # ==================================================================
    # Cấu hình
    # ==================================================================
    def reload_configuration(self, config: Configuration) -> None:
        self.config = config
        self._schedulers = [
            _MessageScheduler(msg, net)
            for net in config.networks
            for msg in net.messages
            if msg.cycle_time_ms > 0
        ]
        self._stats = {
            net.channel: BusStatistics(channel=net.channel, baudrate=net.baudrate)
            for net in config.networks
        }
        self._window_counts = {ch: 0 for ch in self._stats}
        self._window_bits = {ch: 0 for ch in self._stats}
        self._sysvars = {v.qualified_name: v.value for v in config.system_variables}

    def _network_of(self, channel: int) -> NetworkDef | None:
        for net in self.config.networks:
            if net.channel == channel:
                return net
        return None

    # ==================================================================
    # Điều khiển measurement
    # ==================================================================
    def _do_start(self, resumed: bool) -> None:
        if not resumed:
            self.vehicle.reset()
            self._base_time = 0.0
            for stat in self._stats.values():
                stat.frames_total = 0
                stat.tx_count = 0
                stat.rx_count = 0
                stat.error_frames = 0
                stat.peak_load_percent = 0.0
                stat.per_message.clear()
            for sched in self._schedulers:
                sched.next_due = random.uniform(0.0, sched.message.cycle_time_ms / 1000.0)
            self._emit_lifecycle("Measurement started — all CAPL nodes loaded.")
        else:
            self._base_time = self._elapsed
            self._emit_lifecycle("Measurement resumed.")
        self._clock.restart()
        self._last_tick = self._base_time
        self._timer.start()
        self._stats_timer.start()

    def _do_pause(self) -> None:
        self._timer.stop()
        self._stats_timer.stop()
        self._emit_lifecycle("Measurement paused.")

    def _do_stop(self) -> None:
        self._timer.stop()
        self._stats_timer.stop()
        total = sum(s.frames_total for s in self._stats.values())
        self._emit_lifecycle(
            f"Measurement stopped — {total} frame(s) total in {self._elapsed:.2f} s."
        )

    def _emit_lifecycle(self, text: str) -> None:
        self.event_received.emit(BusEvent(
            timestamp=self._elapsed, kind=EventKind.CAPL_WRITE,
            name="System", detail=text, node="CANoe",
        ))

    # ==================================================================
    # Vòng lặp mô phỏng
    # ==================================================================
    def _tick(self) -> None:
        now = self._base_time + self._clock.elapsed() / 1000.0
        dt = max(1e-4, now - self._last_tick)
        self._last_tick = now
        self._elapsed = now

        self.vehicle.step(now, dt)
        batch: list[BusEvent] = []

        for sched in self._schedulers:
            if not sched.due(now):
                continue
            sched.reschedule(now)
            event = self._build_frame(sched.message, sched.network, now)
            batch.append(event)
            self._account(event, sched.network)

        # frame theo sự kiện: DoorStatus khi trạng thái cửa đổi
        if random.random() < dt * 1.2:
            door_msg, door_net = self._find_message("DoorStatus")
            if door_msg is not None and door_net is not None:
                event = self._build_frame(door_msg, door_net, now)
                batch.append(event)
                self._account(event, door_net)

        # error frame hiếm gặp
        if random.random() < dt * 0.08:
            net = random.choice(self.config.networks) if self.config.networks else None
            if net is not None:
                event = BusEvent(timestamp=now, kind=EventKind.ERROR_FRAME,
                                 channel=net.channel, name="ErrorFrame",
                                 direction=Direction.RX, detail="Form Error, bit 42")
                batch.append(event)
                stat = self._stats.get(net.channel)
                if stat:
                    stat.error_frames += 1
                    stat.frames_total += 1

        self._flush_pending_diag(now, batch)
        self._publish_sysvars(now)

        if batch:
            self.events_received.emit(batch)

    def _find_message(self, name: str) -> tuple[MessageDef | None, NetworkDef | None]:
        for net in self.config.networks:
            msg = net.message_by_name(name)
            if msg is not None:
                return msg, net
        return None, None

    def _build_frame(self, msg: MessageDef, net: NetworkDef, now: float) -> BusEvent:
        values = self._signal_values(msg)
        data = codec.encode_message(msg, values) if msg.signals else \
            bytes(random.randrange(256) for _ in range(msg.dlc))
        kind = EventKind.CAN_FD_FRAME if net.bus_type == "CAN FD" else EventKind.CAN_FRAME
        sender = msg.sender
        node = next((n for n in net.nodes if n.name == sender), None)
        direction = Direction.TX if (node and node.kind in ("Simulated", "Tester",
                                                            "Gateway")) else Direction.RX

        for sig in msg.signals:
            if sig.name in values:
                self.signal_updated.emit(f"{msg.name}::{sig.name}", values[sig.name], now)

        return BusEvent(timestamp=now, kind=kind, channel=net.channel,
                        can_id=msg.can_id, name=msg.name, direction=direction,
                        dlc=msg.dlc, data=data, node=sender,
                        is_extended=msg.is_extended)

    def _signal_values(self, msg: MessageDef) -> dict[str, float]:
        v = self.vehicle
        table = {
            "EngineSpeed": v.rpm,
            "EngineTemp": v.temp,
            "ThrottlePos": v.throttle,
            "EngineState": 2.0 if v.rpm > 700 else 0.0,
            "OilPressure": v.oil_pressure,
            "WheelSpeedFL": v.speed + random.uniform(-0.4, 0.4),
            "WheelSpeedFR": v.speed + random.uniform(-0.4, 0.4),
            "WheelSpeedRL": v.speed + random.uniform(-0.4, 0.4),
            "WheelSpeedRR": v.speed + random.uniform(-0.4, 0.4),
            "ABSActive": float(v.abs_active),
            "Gear": float(v.gear),
            "EcoMode": float(v.throttle < 25),
            "ShiftRequest": float(v.gear),
            "HeadLight": float(v.head_light),
            "FlashLight": 0.0,
            "Brightness": 60.0 + 30.0 * math.sin(v._phase * 0.5),
            "DoorFL": float(v.door_open),
            "DoorFR": 0.0,
            "Locked": float(v.speed > 10),
        }
        return {s.name: table[s.name] for s in msg.signals if s.name in table}

    def _account(self, event: BusEvent, net: NetworkDef) -> None:
        stat = self._stats.get(net.channel)
        if stat is None:
            return
        stat.frames_total += 1
        if event.direction is Direction.TX:
            stat.tx_count += 1
        else:
            stat.rx_count += 1
        stat.per_message[event.can_id] = stat.per_message.get(event.can_id, 0) + 1
        self._window_counts[net.channel] = self._window_counts.get(net.channel, 0) + 1
        # khung CAN chuẩn ≈ 47 bit overhead + 8 bit/byte + stuffing ~ 10%
        bits = int((47 + event.dlc * 8) * 1.1)
        self._window_bits[net.channel] = self._window_bits.get(net.channel, 0) + bits

    def _publish_sysvars(self, now: float) -> None:
        updates = {
            "Engine::RPM": round(self.vehicle.rpm, 1),
            "Engine::Temperature": round(self.vehicle.temp, 1),
            "Vehicle::Speed": round(self.vehicle.speed, 1),
            "Vehicle::Gear": self.vehicle.gear,
            "Body::HeadLight": self.vehicle.head_light,
            "Body::DoorOpen": self.vehicle.door_open,
        }
        for name, value in updates.items():
            if self._sysvars.get(name) != value:
                self._sysvars[name] = value
                self.sysvar_changed.emit(name, value)

    def _emit_statistics(self) -> None:
        window_s = STATS_INTERVAL_MS / 1000.0
        for channel, stat in self._stats.items():
            count = self._window_counts.get(channel, 0)
            bits = self._window_bits.get(channel, 0)
            stat.frames_per_second = count / window_s
            stat.bus_load_percent = min(100.0, bits / window_s / stat.baudrate * 100.0)
            stat.peak_load_percent = max(stat.peak_load_percent, stat.bus_load_percent)
            stat.controller_state = "Error active" if stat.error_frames < 12 else "Error passive"
            self._window_counts[channel] = 0
            self._window_bits[channel] = 0
            self.statistics_updated.emit(stat)

    # ==================================================================
    # API tương tác
    # ==================================================================
    def send_frame(self, channel: int, can_id: int, data: bytes,
                   name: str = "", is_extended: bool = False) -> None:
        net = self._network_of(channel)
        msg = net.message_by_id(can_id) if net else None
        event = BusEvent(
            timestamp=self._elapsed,
            kind=EventKind.CAN_FD_FRAME if (net and net.bus_type == "CAN FD")
            else EventKind.CAN_FRAME,
            channel=channel, can_id=can_id,
            name=name or (msg.name if msg else ""),
            direction=Direction.TX, dlc=len(data), data=bytes(data),
            node="Interactive Generator", is_extended=is_extended,
        )
        self.event_received.emit(event)
        if net is not None:
            self._account(event, net)

    def send_diag_request(self, ecu_name: str, request: bytes) -> None:
        ecu = next((e for e in self.config.diag_ecus if e.name == ecu_name), None)
        if ecu is None:
            self.write_line(f"ECU '{ecu_name}' not found in the configuration.", "Diagnostics")
            return
        now = self._elapsed
        self.event_received.emit(BusEvent(
            timestamp=now, kind=EventKind.DIAG_REQUEST, channel=2,
            can_id=ecu.request_id, name=f"{ecu.name}.Request",
            direction=Direction.TX, dlc=len(request), data=bytes(request),
            node="Tester", detail=_describe_uds(request),
        ))
        # phản hồi tới sau 8..45 ms như ECU thật
        delay = random.uniform(0.008, 0.045)
        response = self._lookup_response(ecu, request)
        self._pending_diag.append((now + delay, ecu_name, response))

    def _lookup_response(self, ecu, request: bytes) -> bytes:
        for service in ecu.services:
            if bytes(service.request_bytes) == bytes(request):
                return bytes(service.response_bytes)
        if request:
            # Negative response: 0x7F <SID> <NRC=0x11 Service not supported>
            return bytes((0x7F, request[0], 0x11))
        return b""

    def _flush_pending_diag(self, now: float, batch: list[BusEvent]) -> None:
        if not self._pending_diag:
            return
        remaining: list[tuple[float, str, bytes]] = []
        for due, ecu_name, response in self._pending_diag:
            if due > now:
                remaining.append((due, ecu_name, response))
                continue
            ecu = next((e for e in self.config.diag_ecus if e.name == ecu_name), None)
            batch.append(BusEvent(
                timestamp=now, kind=EventKind.DIAG_RESPONSE, channel=2,
                can_id=ecu.response_id if ecu else 0,
                name=f"{ecu_name}.Response", direction=Direction.RX,
                dlc=len(response), data=response, node=ecu_name,
                detail=_describe_uds(response),
            ))
        self._pending_diag = remaining

    def set_sysvar(self, qualified_name: str, value) -> None:
        self._sysvars[qualified_name] = value
        var = self.config.sysvar(qualified_name)
        if var is not None:
            var.value = value
        # phản hồi ngược vào mô hình xe để thao tác trên panel có tác dụng
        if qualified_name == "Body::HeadLight":
            self.vehicle.head_light = int(value)
        elif qualified_name == "Body::DoorOpen":
            self.vehicle.door_open = int(value)
        elif qualified_name == "Engine::IgnitionOn":
            self.vehicle.ignition = int(value)
        self.sysvar_changed.emit(qualified_name, value)

    def get_sysvar(self, qualified_name: str):
        return self._sysvars.get(qualified_name)

    def write_line(self, text: str, source: str = "CAPL") -> None:
        self.event_received.emit(BusEvent(
            timestamp=self._elapsed, kind=EventKind.CAPL_WRITE,
            name=source, detail=text, node=source,
        ))


# ---------------------------------------------------------------------------

_UDS_SERVICES = {
    0x10: "DiagnosticSessionControl", 0x11: "ECUReset",
    0x14: "ClearDiagnosticInformation", 0x19: "ReadDTCInformation",
    0x22: "ReadDataByIdentifier", 0x23: "ReadMemoryByAddress",
    0x27: "SecurityAccess", 0x28: "CommunicationControl",
    0x2E: "WriteDataByIdentifier", 0x2F: "InputOutputControlByIdentifier",
    0x31: "RoutineControl", 0x34: "RequestDownload", 0x35: "RequestUpload",
    0x36: "TransferData", 0x37: "RequestTransferExit",
    0x3E: "TesterPresent", 0x85: "ControlDTCSetting",
}

_UDS_NRC = {
    0x10: "General reject", 0x11: "Service not supported",
    0x12: "Sub-function not supported", 0x13: "Incorrect message length",
    0x22: "Conditions not correct", 0x31: "Request out of range",
    0x33: "Security access denied", 0x35: "Invalid key",
    0x78: "Response pending",
}


def _describe_uds(payload: bytes) -> str:
    """Diễn giải ngắn gọn một primitive UDS để hiển thị ở cột Detail."""
    if not payload:
        return ""
    sid = payload[0]
    if sid == 0x7F and len(payload) >= 3:
        service = _UDS_SERVICES.get(payload[1], f"0x{payload[1]:02X}")
        nrc = _UDS_NRC.get(payload[2], f"NRC 0x{payload[2]:02X}")
        return f"Negative response — {service}: {nrc}"
    if sid & 0x40 and (sid - 0x40) in _UDS_SERVICES:
        return f"Positive response — {_UDS_SERVICES[sid - 0x40]}"
    if sid in _UDS_SERVICES:
        return f"Request — {_UDS_SERVICES[sid]}"
    return f"SID 0x{sid:02X}"
