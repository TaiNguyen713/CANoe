"""Các nút cây cú pháp trừu tượng (AST) của CAPL.

Phase 2 sẽ đi trên cây này để thực thi. Mọi nút đều mang `line`/`column` để
engine báo lỗi runtime đúng vị trí trong editor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    literal_type: str = "int"      # int | float | string | char


@dataclass
class Identifier(Expr):
    name: str = ""


@dataclass
class ThisExpr(Expr):
    """Từ khoá `this` — đối tượng sự kiện hiện hành."""


@dataclass
class ScopedName(Expr):
    """Tên có phân cấp namespace: `sysvar::Engine::RPM`, `Door::Lock`."""
    parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "::".join(self.parts)


@dataclass
class SysVarAccess(Expr):
    """Truy cập trực tiếp system variable: `@sysvar::NS::Var` hoặc `@NS::Var`."""
    path: ScopedName | None = None


@dataclass
class SignalAccess(Expr):
    """Truy cập signal theo cú pháp `$SignalName` hoặc `$Message::Signal`."""
    path: ScopedName | None = None
    raw_value: bool = False        # True cho `$...` dạng raw (hậu tố .raw)


@dataclass
class Unary(Expr):
    op: str = ""
    operand: Expr | None = None
    postfix: bool = False          # True cho `x++` / `x--`


@dataclass
class Binary(Expr):
    op: str = ""
    left: Expr | None = None
    right: Expr | None = None


@dataclass
class Assign(Expr):
    op: str = "="                  # = += -= *= /= %= &= |= ^= <<= >>=
    target: Expr | None = None
    value: Expr | None = None


@dataclass
class Ternary(Expr):
    condition: Expr | None = None
    if_true: Expr | None = None
    if_false: Expr | None = None


@dataclass
class Call(Expr):
    callee: Expr | None = None
    args: list[Expr] = field(default_factory=list)

    @property
    def callee_name(self) -> str:
        c = self.callee
        if isinstance(c, Identifier):
            return c.name
        if isinstance(c, ScopedName):
            return c.parts[-1] if c.parts else ""
        if isinstance(c, Member):
            return c.member
        return ""


@dataclass
class Member(Expr):
    """Truy cập thành viên: `this.id`, `msg.byte`, `req.resp`."""
    obj: Expr | None = None
    member: str = ""
    arrow: bool = False            # True nếu dùng toán tử `->`


@dataclass
class Index(Expr):
    obj: Expr | None = None
    index: Expr | None = None


@dataclass
class Cast(Expr):
    type_name: str = ""
    operand: Expr | None = None


@dataclass
class SizeOf(Expr):
    operand: Expr | str | None = None


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
class EmptyStmt(Stmt):
    pass


@dataclass
class VarDecl(Stmt):
    """Một biến (hoặc mảng) được khai báo.

    `array_dims` chứa biểu thức kích thước; `[]` không ghi kích thước ⇒ None.
    """
    type_name: str = ""
    name: str = ""
    array_dims: list[Expr | None] = field(default_factory=list)
    initializer: Expr | list[Expr] | None = None
    is_const: bool = False
    is_static: bool = False
    is_export: bool = False
    # với `message 0x100 msg;` hoặc `message EngineData msg;`
    bus_selector: str = ""

    @property
    def is_array(self) -> bool:
        return bool(self.array_dims)


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
class DoWhileStmt(Stmt):
    body: Stmt | None = None
    condition: Expr | None = None


@dataclass
class ForStmt(Stmt):
    init: Stmt | None = None
    condition: Expr | None = None
    step: Expr | None = None
    body: Stmt | None = None


@dataclass
class SwitchStmt(Stmt):
    subject: Expr | None = None
    body: Block | None = None


@dataclass
class CaseLabel(Stmt):
    value: Expr | None = None      # None ⇒ `default:`

    @property
    def is_default(self) -> bool:
        return self.value is None


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class ReturnStmt(Stmt):
    value: Expr | None = None


@dataclass
class GotoStmt(Stmt):
    label: str = ""


@dataclass
class LabelStmt(Stmt):
    name: str = ""


# ---------------------------------------------------------------------------
# Khai báo cấp cao nhất
# ---------------------------------------------------------------------------

@dataclass
class Parameter(Node):
    type_name: str = ""
    name: str = ""
    array_dims: list[Expr | None] = field(default_factory=list)
    is_reference: bool = False

    @property
    def text(self) -> str:
        dims = "[]" * len(self.array_dims)
        return f"{self.type_name} {self.name}{dims}"


@dataclass
class IncludesBlock(Node):
    directives: list[str] = field(default_factory=list)


@dataclass
class VariablesBlock(Node):
    declarations: list[VarDecl] = field(default_factory=list)
    is_export: bool = False


@dataclass
class StructDecl(Node):
    name: str = ""
    members: list[VarDecl] = field(default_factory=list)


@dataclass
class EnumMember(Node):
    name: str = ""
    value: Expr | None = None


@dataclass
class EnumDecl(Node):
    name: str = ""
    members: list[EnumMember] = field(default_factory=list)


@dataclass
class FunctionDecl(Node):
    return_type: str = "void"
    name: str = ""
    params: list[Parameter] = field(default_factory=list)
    body: Block | None = None
    is_export: bool = False

    @property
    def signature(self) -> str:
        args = ", ".join(p.text for p in self.params)
        return f"{self.return_type} {self.name}({args})"


@dataclass
class TestCaseDecl(FunctionDecl):
    """`testcase Name(...) { ... }` — Test Feature Set."""
    is_test_function: bool = False   # True nếu khai báo bằng `testfunction`


@dataclass
class EventHandler(Node):
    """`on <event_type> <selector> { ... }`.

    - `event_type`: message, timer, key, sysvar, start, ...
    - `selector`: tên/ID đối tượng, `*` cho tất cả, rỗng nếu event không cần.
    """
    event_type: str = ""
    selector: str = ""
    body: Block | None = None

    @property
    def display_name(self) -> str:
        return f"on {self.event_type} {self.selector}".strip()


@dataclass
class CaplFile(Node):
    """Nút gốc của một file .can / .cin."""
    path: str = ""
    includes: IncludesBlock | None = None
    variables: list[VariablesBlock] = field(default_factory=list)
    structs: list[StructDecl] = field(default_factory=list)
    enums: list[EnumDecl] = field(default_factory=list)
    functions: list[FunctionDecl] = field(default_factory=list)
    testcases: list[TestCaseDecl] = field(default_factory=list)
    handlers: list[EventHandler] = field(default_factory=list)

    def global_variables(self) -> list[VarDecl]:
        out: list[VarDecl] = []
        for block in self.variables:
            out.extend(block.declarations)
        return out

    def summary(self) -> str:
        return (
            f"{len(self.global_variables())} biến, {len(self.functions)} hàm, "
            f"{len(self.handlers)} event handler, {len(self.testcases)} testcase"
        )


# ---------------------------------------------------------------------------
# Duyệt cây
# ---------------------------------------------------------------------------

def walk(node: Any):
    """Duyệt đệ quy mọi nút AST con (thứ tự pre-order)."""
    if isinstance(node, Node):
        yield node
        for value in vars(node).values():
            yield from walk(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from walk(item)
