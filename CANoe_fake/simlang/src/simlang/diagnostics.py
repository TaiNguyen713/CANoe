"""Cấu trúc báo lỗi/cảnh báo dùng chung cho parser/codegen của simlang.

Cùng khuôn mẫu với `canoe_fake/capl/diagnostics.py` trong repo này.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Severity(enum.IntEnum):
    HINT = 0
    INFO = 1
    WARNING = 2
    ERROR = 3

    @property
    def label(self) -> str:
        return {
            Severity.HINT: "Hint",
            Severity.INFO: "Info",
            Severity.WARNING: "Warning",
            Severity.ERROR: "Error",
        }[self]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Một lỗi/cảnh báo gắn với vị trí trong file `.can` gốc.

    `line`/`column` đánh số từ 1 để hiển thị trực tiếp cho người dùng.
    """

    severity: Severity
    code: str
    message: str
    line: int
    column: int
    length: int = 1
    source: str = "simlang"

    def __str__(self) -> str:
        return f"({self.line},{self.column}) {self.severity.label} {self.code}: {self.message}"


@dataclass
class DiagnosticBag:
    max_errors: int = 200
    items: list[Diagnostic] = field(default_factory=list)
    _overflowed: bool = False

    def add(self, diag: Diagnostic) -> None:
        if len(self.items) >= self.max_errors:
            self._overflowed = True
            return
        self.items.append(diag)

    def error(self, code: str, message: str, line: int, column: int, length: int = 1) -> None:
        self.add(Diagnostic(Severity.ERROR, code, message, line, column, length))

    def warning(self, code: str, message: str, line: int, column: int, length: int = 1) -> None:
        self.add(Diagnostic(Severity.WARNING, code, message, line, column, length))

    def info(self, code: str, message: str, line: int, column: int, length: int = 1) -> None:
        self.add(Diagnostic(Severity.INFO, code, message, line, column, length))

    @property
    def overflowed(self) -> bool:
        return self._overflowed

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity is Severity.WARNING]

    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.items)

    def sorted(self) -> list[Diagnostic]:
        return sorted(self.items, key=lambda d: (d.line, d.column, -int(d.severity)))

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)
