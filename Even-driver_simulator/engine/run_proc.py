"""Command-line runner for a stateful .proc simulation."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from threading import Event

from engine.dynamic_response_engine import DotNetSimulatorHost
from engine.proc_engine import ProcController, ProcProgram


def default_dll_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "OBDSimulation_CLI_1.3.36.3"
        / "x64"
        / "net9.0"
        / "SimulatorInterface.dll"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an event-driven .proc simulator")
    parser.add_argument("proc_file", type=Path)
    parser.add_argument("--com", required=True, help="Simulator port, for example COM5")
    parser.add_argument("--dll", type=Path, default=default_dll_path())
    parser.add_argument("--checksum", default="NONE")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    program = ProcProgram.load(args.proc_file)
    if program.sim_file is None:
        parser.error("the root .proc file must contain SIM")

    stopped = Event()
    with DotNetSimulatorHost(args.dll, "ProcEngine") as host:
        database = host.open(args.com, program.sim_file, start_device=False)
        from SimulatorInterface import enumchecksumprotocol

        try:
            checksum = getattr(enumchecksumprotocol, args.checksum)
        except AttributeError:
            choices = ", ".join(str(value) for value in enumchecksumprotocol.GetValues(enumchecksumprotocol))
            parser.error(f"unknown checksum {args.checksum!r}; available: {choices}")

        controller = ProcController(program, database, checksum)
        controller.bind(database.getlistobddb())

        def on_message(_port: str, _message_type: object, message: str) -> None:
            transition = controller.handle_tx(message)
            if transition is not None:
                logging.info(
                    "PROC transition %s -> %s", transition.previous, transition.current
                )

        host.set_message_handler(on_message)
        host.start()
        logging.info(
            "Simulator started on %s; SIM=%s; state=%s",
            args.com,
            program.sim_file,
            controller.active_block,
        )
        try:
            while not stopped.wait(0.5):
                pass
        except KeyboardInterrupt:
            logging.info("Stopping simulator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
