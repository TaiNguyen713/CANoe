"""Các nút cây cú pháp trừu tượng (AST) của ngôn ngữ `.can`.

Cùng khuôn mẫu với `canoe_fake/capl/ast_nodes.py` trong repo này: mọi nút
đều mang `line`/`column` để báo lỗi runtime đúng vị trí trong file `.can`
gốc — xem `codegen.py`'s `__SIMLANG_LINEMAP__`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


# ---------------------------------------------------------------------------
# Nút gốc
# ---------------------------------------------------------------------------


@dataclass
class Node:
    line: int = 0
    column: int = 0

    @property
    def kind(self) -> str:
        return type(self).__name__


def walk(node: Any) -> Iterator[Node]:
    """Duyệt pre-order toàn bộ cây, đệ quy qua mọi field là Node/list/tuple."""
    if isinstance(node, Node):
        yield node
        for value in vars(node).values():
            yield from walk(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item)


# ---------------------------------------------------------------------------
# Biểu thức
# ---------------------------------------------------------------------------


@dataclass
class Expr(Node):
    pass


@dataclass
class Literal(Expr):
    value: Any = None
    raw: str = ""
    literal_type: str = "int"  # int | float | string | hex


@dataclass
class Identifier(Expr):
    name: str = ""


@dataclass
class Unary(Expr):
    op: str = ""
    operand: Expr | None = None


@dataclass
class Binary(Expr):
    op: str = ""
    left: Expr | None = None
    right: Expr | None = None


@dataclass
class Assign(Expr):
    op: str = "="
    target: Expr | None = None
    value: Expr | None = None


@dataclass
class Call(Expr):
    name: str = ""  # simlang không có callee tuỳ ý — luôn là tên builtin trần
    args: list[Expr] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Câu lệnh
# ---------------------------------------------------------------------------


@dataclass
class Stmt(Node):
    pass


@dataclass
class Block(Stmt):
    statements: list[Stmt] = field(default_factory=list)


@dataclass
class ExprStmt(Stmt):
    expr: Expr | None = None


@dataclass
class VarDecl(Stmt):
    type_name: str = ""  # int|long|float|double|char|byte|msTimer
    name: str = ""
    is_array: bool = False  # byte[]/char[] -> type_name="byte"/"char", is_array=True
    array_size: int | None = None
    initializer: Expr | None = None


@dataclass
class IfStmt(Stmt):
    condition: Expr | None = None
    then_branch: Stmt | None = None
    else_branch: Stmt | None = None


@dataclass
class WhileStmt(Stmt):
    condition: Expr | None = None
    body: Stmt | None = None


@dataclass
class ForStmt(Stmt):
    init: Stmt | None = None
    condition: Expr | None = None
    step: Expr | None = None
    body: Stmt | None = None


@dataclass
class CaseClause(Node):
    value: Expr | None = None  # None == default
    body: list[Stmt] = field(default_factory=list)


@dataclass
class SwitchStmt(Stmt):
    subject: Expr | None = None
    cases: list[CaseClause] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Mẫu khớp cho `data <bytes>` — KHÔNG phải biểu thức, chỉ dùng cho dispatch
# ---------------------------------------------------------------------------


@dataclass
class ByteMatch(Node):
    value: int | None = None  # None khi là wildcard
    is_wildcard: bool = False


@dataclass
class DataClause(Node):
    bytes: list[ByteMatch] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cấp cao nhất
# ---------------------------------------------------------------------------


@dataclass
class VariablesBlock(Node):
    declarations: list[VarDecl] = field(default_factory=list)


@dataclass
class OnStart(Node):
    body: Block | None = None


@dataclass
class OnStop(Node):
    body: Block | None = None


@dataclass
class OnTimer(Node):
    timer_name: str = ""
    body: Block | None = None


@dataclass
class OnMessage(Node):
    can_id: int = 0
    body: Block | None = None


@dataclass
class OnRequest(Node):
    can_id: int = 0
    service: int = 0
    pid: int | None = None
    data: DataClause | None = None
    body: Block | None = None

    @property
    def specificity(self) -> int:
        """0=chỉ service, +1=có pid, +2=có data — khớp độ ưu tiên dispatch
        (data > pid > service) trong runtime/dispatch.py."""
        return (2 if self.data is not None else 0) + (1 if self.pid is not None else 0)


@dataclass
class CanFile(Node):
    path: str = ""
    variables: VariablesBlock | None = None
    on_start: OnStart | None = None
    on_stop: OnStop | None = None
    on_timers: list[OnTimer] = field(default_factory=list)
    on_messages: list[OnMessage] = field(default_factory=list)
    on_requests: list[OnRequest] = field(default_factory=list)
