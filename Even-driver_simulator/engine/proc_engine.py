"""Stateful TX/RX procedures layered on top of a static ``.sim`` database.

Example ``.proc`` file::

    SIM "SimFiles/example.sim"
    START A_FIRST

    BLOCK A_FIRST
      TX 000007DF 08 03 22 12 34 00 00 00
      RX 000007E8 08 04 62 12 34 01 00 00
      NEXT A_SECOND
    END

    BLOCK A_SECOND
      TX 000007DF 08 03 22 12 34 00 00 00
      RX 000007E8 08 04 62 12 34 00 01 00
      NEXT A_SECOND
    END

``TX`` accepts ``XX`` wildcard bytes.  A block's RX is installed when that
block becomes active.  After its TX is observed, ``NEXT`` is activated, so the
next identical request receives the next state's response.

Reusable blocks can be stored in another file and loaded with
``INCLUDE "common.proc"``. The root file remains responsible for ``SIM`` and
``START``.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from engine.dynamic_response_engine import ResponseDatabase

_TOKEN_RE = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}|[0-9a-f]{3,8}|xx)(?![0-9a-f])")


class ProcSyntaxError(ValueError):
    pass


def _argument(line: str, directive: str) -> str:
    value = line[len(directive) :].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if not value:
        raise ProcSyntaxError(f"{directive} requires a value")
    return value


def frame_tokens(value: str) -> tuple[str, ...]:
    return tuple(token.upper() for token in _TOKEN_RE.findall(value))


def frames_match(pattern: str, actual: str, *, either_wildcard: bool = False) -> bool:
    """Match a frame inside display text, tolerating prefixes such as ``[RX]``."""

    expected = frame_tokens(pattern)
    received = frame_tokens(actual)
    if not expected or len(received) < len(expected):
        return False
    for start in range(len(received) - len(expected) + 1):
        window = received[start : start + len(expected)]
        if all(
            wanted == "XX"
            or (either_wildcard and got == "XX")
            or wanted == got
            for wanted, got in zip(expected, window)
        ):
            return True
    return False


@dataclass(slots=True)
class ProcBlock:
    name: str
    tx: str = ""
    responses: list[str] = field(default_factory=list)
    next_block: str | None = None
    frame_index: int | None = None


@dataclass(slots=True)
class ProcProgram:
    source: Path
    sim_file: Path | None
    start_block: str
    blocks: dict[str, ProcBlock]

    @classmethod
    def load(cls, filename: str | Path) -> "ProcProgram":
        source = Path(filename).resolve()
        blocks: dict[str, ProcBlock] = {}
        settings: dict[str, str | Path | None] = {"sim": None, "start": None}
        visited: set[Path] = set()
        cls._parse_file(source, blocks, settings, visited, is_root=True)

        start = settings["start"]
        if not isinstance(start, str):
            raise ProcSyntaxError(f"{source}: missing START")
        if start not in blocks:
            raise ProcSyntaxError(f"{source}: START references unknown block {start!r}")
        for block in blocks.values():
            if not block.tx:
                raise ProcSyntaxError(f"block {block.name!r}: missing TX")
            if not block.responses:
                raise ProcSyntaxError(f"block {block.name!r}: missing RX")
            if block.next_block is not None and block.next_block not in blocks:
                raise ProcSyntaxError(
                    f"block {block.name!r}: NEXT references unknown block "
                    f"{block.next_block!r}"
                )
        sim_file = settings["sim"]
        return cls(
            source=source,
            sim_file=sim_file if isinstance(sim_file, Path) else None,
            start_block=start,
            blocks=blocks,
        )

    @classmethod
    def _parse_file(
        cls,
        source: Path,
        blocks: dict[str, ProcBlock],
        settings: dict[str, str | Path | None],
        visited: set[Path],
        *,
        is_root: bool,
    ) -> None:
        if source in visited:
            raise ProcSyntaxError(f"recursive INCLUDE detected: {source}")
        if not source.is_file():
            raise FileNotFoundError(source)
        visited.add(source)
        current: ProcBlock | None = None

        for line_number, raw_line in enumerate(
            source.read_text(encoding="utf-8-sig").splitlines(), 1
        ):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            directive = line.split(None, 1)[0].upper()
            try:
                if directive == "INCLUDE" and current is None:
                    included = (source.parent / _argument(line, directive)).resolve()
                    cls._parse_file(
                        included, blocks, settings, visited, is_root=False
                    )
                elif directive == "SIM" and current is None:
                    if not is_root:
                        raise ProcSyntaxError("SIM is only allowed in the root file")
                    settings["sim"] = (
                        source.parent / _argument(line, directive)
                    ).resolve()
                elif directive == "START" and current is None:
                    if not is_root:
                        raise ProcSyntaxError("START is only allowed in the root file")
                    settings["start"] = _argument(line, directive)
                elif directive == "BLOCK" and current is None:
                    name = _argument(line, directive)
                    if name in blocks:
                        raise ProcSyntaxError(f"duplicate block {name!r}")
                    current = ProcBlock(name=name)
                    blocks[name] = current
                elif directive == "TX" and current is not None:
                    current.tx = _argument(line, directive)
                elif directive == "RX" and current is not None:
                    current.responses.append(_argument(line, directive))
                elif directive == "NEXT" and current is not None:
                    current.next_block = _argument(line, directive)
                elif directive == "FRAME_INDEX" and current is not None:
                    current.frame_index = int(_argument(line, directive), 0)
                elif directive == "END" and current is not None:
                    current = None
                else:
                    raise ProcSyntaxError(f"unexpected directive {directive!r}")
            except (ProcSyntaxError, ValueError) as exc:
                raise ProcSyntaxError(f"{source}:{line_number}: {exc}") from exc

        if current is not None:
            raise ProcSyntaxError(f"{source}: block {current.name!r} has no END")
        visited.remove(source)


@dataclass(frozen=True, slots=True)
class ProcTransition:
    previous: str
    current: str


class ProcController:
    """Apply procedure states to an already loaded vendor database."""

    def __init__(self, program: ProcProgram, database: ResponseDatabase, checksum: object):
        self.program = program
        self.database = database
        self.checksum = checksum
        self._active = program.start_block
        self._lock = threading.RLock()
        self._bound = False

    @property
    def active_block(self) -> str:
        with self._lock:
            return self._active

    def bind(self, database_entries: Iterable[object]) -> None:
        """Resolve every TX pattern to its request index and install START RX."""

        entries = list(database_entries)
        for block in self.program.blocks.values():
            if block.frame_index is not None:
                if block.frame_index >= len(entries):
                    raise ValueError(
                        f"block {block.name!r}: FRAME_INDEX {block.frame_index} is out of range"
                    )
                candidates = [block.frame_index]
            else:
                candidates = [
                    index
                    for index, entry in enumerate(entries)
                    if frames_match(block.tx, str(entry.req), either_wildcard=True)
                ]
            if len(candidates) != 1:
                raise ValueError(
                    f"block {block.name!r}: TX must match exactly one .sim request; "
                    f"matched indexes={candidates}. Use FRAME_INDEX to disambiguate."
                )
            block.frame_index = candidates[0]
            response_count = len(entries[candidates[0]].res_s)
            if len(block.responses) > response_count:
                raise ValueError(
                    f"block {block.name!r}: defines {len(block.responses)} RX frame(s), "
                    f"but .sim entry {candidates[0]} has only {response_count}"
                )
        self._bound = True
        self._activate(self._active)

    def handle_tx(self, message: str) -> ProcTransition | None:
        """Consume an observed tester request and prepare the next state."""

        with self._lock:
            if not self._bound:
                raise RuntimeError("controller must be bound before handling TX")
            block = self.program.blocks[self._active]
            if not frames_match(block.tx, message):
                return None
            target = block.next_block or block.name
            previous = self._active
            self._active = target
            self._activate(target)
            return ProcTransition(previous=previous, current=target)

    def _activate(self, name: str) -> None:
        block = self.program.blocks[name]
        if block.frame_index is None:
            raise RuntimeError(f"block {name!r} has not been bound")
        for response_index, response in enumerate(block.responses):
            self.database.OBDDb_UpdateRes(
                response,
                self.checksum,
                block.frame_index,
                response_index,
            )
