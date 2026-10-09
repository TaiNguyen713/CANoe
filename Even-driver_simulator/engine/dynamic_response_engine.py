"""In-memory, event-driven response updates for SimulatorInterface.dll.

The vendor simulator normally loads static request/response pairs from a .sim
file.  This module keeps the vendor matching and transmission logic, but
updates response templates in ``SimulateDataBase`` while the device is running.

Only single-response rules are guaranteed not to expose a mixed update.  The
vendor API updates one response string at a time and provides no transaction
or lock for a multi-frame response.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

logger = logging.getLogger(__name__)

ResponseProvider = Callable[[float, int], str]


class ResponseDatabase(Protocol):
    """Small surface used from the vendor ``SimulateDataBase`` object."""

    def OBDDb_UpdateRes(
        self, response: str, checksum: object, frame_index: int, response_index: int
    ) -> None: ...


@dataclass(slots=True)
class DynamicResponseRule:
    """Periodically calculate and commit one database response.

    ``provider`` receives elapsed seconds since the engine started and the
    zero-based number of this rule's update. It must return the full response
    string accepted by ``OBDDb_UpdateRes`` (the same payload syntax as a .sim
    ``INFO_DATABASE = Res`` line).
    """

    frame_index: int
    response_index: int
    interval_ms: float
    provider: ResponseProvider
    checksum: object
    name: str = "dynamic-response"
    _next_due: float = field(default=0.0, init=False, repr=False)
    _update_count: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.frame_index < 0:
            raise ValueError("frame_index must be >= 0")
        if self.response_index < 0:
            raise ValueError("response_index must be >= 0")
        if self.interval_ms <= 0:
            raise ValueError("interval_ms must be > 0")

    def reset(self, started_at: float) -> None:
        self._next_due = started_at
        self._update_count = 0

    def update(self, database: ResponseDatabase, now: float, started_at: float) -> None:
        response = self.provider(now - started_at, self._update_count)
        if not isinstance(response, str) or not response.strip():
            raise ValueError(f"rule {self.name!r} returned an empty response")
        database.OBDDb_UpdateRes(
            response, self.checksum, self.frame_index, self.response_index
        )
        self._update_count += 1

        # Anchor the schedule instead of using now + interval. This prevents
        # accumulated drift while also skipping missed ticks after a stall.
        interval = self.interval_ms / 1000.0
        self._next_due += interval
        if self._next_due <= now:
            missed = int((now - self._next_due) / interval) + 1
            self._next_due += missed * interval


class DynamicResponseEngine:
    """High-resolution scheduler which updates a loaded simulator database."""

    def __init__(self, database: ResponseDatabase):
        self._database = database
        self._rules: list[DynamicResponseRule] = []
        self._rules_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at = 0.0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def add_rule(self, rule: DynamicResponseRule) -> None:
        with self._rules_lock:
            if self.is_running:
                rule.reset(self._started_at)
            self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        with self._rules_lock:
            for index, rule in enumerate(self._rules):
                if rule.name == name:
                    del self._rules[index]
                    return True
        return False

    def set_response(
        self,
        *,
        frame_index: int,
        response_index: int,
        response: str,
        checksum: object,
    ) -> None:
        """Commit a response immediately, for an external event or test step."""

        if frame_index < 0 or response_index < 0:
            raise ValueError("response indexes must be >= 0")
        if not response.strip():
            raise ValueError("response must not be empty")
        self._database.OBDDb_UpdateRes(
            response, checksum, frame_index, response_index
        )

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._started_at = time.perf_counter()
        with self._rules_lock:
            for rule in self._rules:
                rule.reset(self._started_at)
        self._thread = threading.Thread(
            target=self._run, name="dynamic-simulator", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            now = time.perf_counter()
            next_due: float | None = None
            with self._rules_lock:
                rules = tuple(self._rules)
            for rule in rules:
                if rule._next_due <= now:
                    try:
                        rule.update(self._database, now, self._started_at)
                    except Exception:
                        logger.exception("Dynamic response rule %r failed", rule.name)
                if next_due is None or rule._next_due < next_due:
                    next_due = rule._next_due

            if next_due is None:
                self._stop_event.wait(0.05)
            else:
                self._stop_event.wait(max(0.0, min(next_due - time.perf_counter(), 0.05)))

    def __enter__(self) -> "DynamicResponseEngine":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


class DotNetSimulatorHost:
    """Own an in-process vendor simulator through pythonnet/CoreCLR."""

    def __init__(self, dll_path: str | Path, software_version: str = "Python"):
        self.dll_path = Path(dll_path).resolve()
        self.software_version = software_version
        self.simulator = None
        self._buffer_callback = None
        self._started = False

    def open(
        self, com_port: str, sim_file: str | Path, *, start_device: bool = True
    ) -> ResponseDatabase:
        if self.simulator is not None:
            raise RuntimeError("simulator is already open")
        if not self.dll_path.is_file():
            raise FileNotFoundError(self.dll_path)

        try:
            from pythonnet import load

            load("coreclr")
            import clr
        except ImportError as exc:
            raise RuntimeError(
                "pythonnet is required for the in-process DLL bridge; "
                "install it with: py -m pip install pythonnet"
            ) from exc

        # pythonnet uses sys.path while resolving managed dependencies such as
        # Newtonsoft.Json.dll shipped alongside SimulatorInterface.dll.
        dll_directory = str(self.dll_path.parent)
        if dll_directory not in sys.path:
            sys.path.insert(0, dll_directory)
        clr.AddReference(str(self.dll_path))
        from SimulatorInterface import ObdSimulator

        simulator = ObdSimulator(self.software_version, False)
        if not simulator.OpenConnection(com_port):
            simulator.Close()
            raise RuntimeError(f"cannot open simulator on {com_port}")
        if not simulator.Database_LoadFile(str(Path(sim_file).resolve()), True, True):
            simulator.Close()
            raise RuntimeError(f"cannot load simulation file: {sim_file}")
        self.simulator = simulator
        if start_device:
            self.start()
        return simulator.getSimDB()

    def start(self) -> None:
        if self.simulator is None:
            raise RuntimeError("simulator is not open")
        if not self._started:
            if not self.simulator.StartDevice():
                raise RuntimeError("simulator device did not start")
            self._started = True

    def set_message_handler(
        self, handler: Callable[[str, object, str], None]
    ) -> None:
        """Receive ordered display-buffer messages from the managed DLL."""

        if self.simulator is None:
            raise RuntimeError("simulator is not open")
        from SimulatorInterface import SimulatorApi

        def on_buffer(port_name, message_types, messages):
            for message_type, message in zip(message_types, messages):
                handler(str(port_name), message_type, str(message))

        # Retain the managed delegate for the lifetime of the simulator. If it
        # is garbage-collected, a later callback from the C# thread can crash.
        self._buffer_callback = SimulatorApi.CallbackUpdateBufferConsole(on_buffer)
        SimulatorApi.setCallbackUpdateConsoleBuff(self._buffer_callback)

    def close(self) -> None:
        simulator, self.simulator = self.simulator, None
        if simulator is not None:
            try:
                if self._started:
                    simulator.StopDevice()
            finally:
                simulator.Close()
        self._started = False
        self._buffer_callback = None

    def __enter__(self) -> "DotNetSimulatorHost":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def linear_byte_response(
    template: str,
    byte_token: str,
    start: int,
    end: int,
    duration_seconds: float,
) -> ResponseProvider:
    """Build a provider that replaces one unique token with a ramping byte."""

    if template.count(byte_token) != 1:
        raise ValueError("byte_token must occur exactly once in template")
    if not 0 <= start <= 0xFF or not 0 <= end <= 0xFF:
        raise ValueError("start and end must be byte values")
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be > 0")

    def provider(elapsed: float, _update_count: int) -> str:
        progress = min(max(elapsed / duration_seconds, 0.0), 1.0)
        value = round(start + ((end - start) * progress))
        return template.replace(byte_token, f"{value:02X}")

    return provider
