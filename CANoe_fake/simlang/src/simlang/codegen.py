"""AST (`.can`) → mã nguồn Python. Người viết `.can` không bao giờ thấy
Python (spec §1) — mọi handler sinh ra là `async def` nhận `ctx`
(`runtime.builtins.Context`) làm tham số đầu, `delay(ms)` dịch thẳng thành
`await asyncio.sleep(ms/1000)` (không chặn luồng, xem §6.3).

Đơn giản hoá có chủ ý (không phải bug): `/` luôn dịch thành true-division
Python — simlang không có type-checker đầy đủ nên không thể luôn biết chắc
hai toán hạng là int hay float để quyết định `//` kiểu C. Ví dụ duy nhất
dùng `/` trong spec (`elapsed() / 3.0`) là chia float, không bị ảnh hưởng.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ast_nodes as ast


class CodegenError(Exception):
    pass


@dataclass
class GeneratedModule:
    source: str
    line_map: dict[int, int]  # dòng Python sinh ra -> dòng .can gốc


_BINARY_PY_OP = {"&&": "and", "||": "or"}
_BITWISE_OPS = {"<<", ">>", "&", "|", "^"}

# builtin cần `await ctx.<method>(...)`
_ASYNC_CTX_BUILTINS = {"output": "output", "outputRaw": "output_raw"}
# builtin gọi đồng bộ qua ctx (KHÔNG await)
_SYNC_CTX_BUILTINS = {
    "write": "write",
    "loadStatic": "load_static",
    "setTimer": "set_timer",
    "cancelTimer": "cancel_timer",
    "elapsed": "elapsed",
}
# hàm thuần, không cần ctx
_DIRECT_BUILTINS = {
    "sin": "math.sin",
    "cos": "math.cos",
    "abs": "abs",
    "min": "min",
    "max": "max",
    "random": "_simlang_random",
}
_ALL_BUILTIN_NAMES = {"delay", *_ASYNC_CTX_BUILTINS, *_SYNC_CTX_BUILTINS, *_DIRECT_BUILTINS}


class _Emitter:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.line_map: dict[int, int] = {}
        self._indent = 0

    def indent(self) -> None:
        self._indent += 1

    def dedent(self) -> None:
        self._indent -= 1

    def emit(self, text: str, can_line: int = 0) -> None:
        self.lines.append(("    " * self._indent) + text)
        if can_line:
            self.line_map[len(self.lines)] = can_line

    def blank(self) -> None:
        self.lines.append("")


class _CodeGen:
    def __init__(self, can_file: ast.CanFile) -> None:
        self.can_file = can_file
        self.e = _Emitter()
        self._global_names: set[str] = {
            d.name for d in (can_file.variables.declarations if can_file.variables else [])
        }
        self._timer_names: set[str] = {
            d.name for d in (can_file.variables.declarations if can_file.variables else [])
            if d.type_name == "msTimer"
        }
        self._counter = 0
        self._registrations: list[str] = []

    def _next_name(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    # -----------------------------------------------------------------
    def build(self) -> GeneratedModule:
        self._emit_header()
        self._emit_globals()
        if self.can_file.on_start:
            self._emit_handler_def("on_start", None, self.can_file.on_start.body, self.can_file.on_start.line)
        if self.can_file.on_stop:
            self._emit_handler_def("on_stop", None, self.can_file.on_stop.body, self.can_file.on_stop.line)
        for req in self.can_file.on_requests:
            self._emit_on_request(req)
        for timer in self.can_file.on_timers:
            self._emit_on_timer(timer)
        for msg in self.can_file.on_messages:
            self._emit_on_message(msg)
        self._emit_register_function()
        self._emit_line_map()
        source = "\n".join(self.e.lines) + "\n"
        return GeneratedModule(source=source, line_map=dict(self.e.line_map))

    # -----------------------------------------------------------------
    def _emit_header(self) -> None:
        self.e.emit('"""Sinh tự động bởi simlang.codegen — KHÔNG sửa tay."""')
        self.e.emit("from __future__ import annotations")
        self.e.blank()
        self.e.emit("import asyncio")
        self.e.emit("import math")
        self.e.blank()
        self.e.emit("from simlang.runtime.builtins import random_ as _simlang_random")
        self.e.emit("from simlang.runtime.timers import TimerHandle as _TimerHandle")
        self.e.blank()

    def _emit_globals(self) -> None:
        if not self.can_file.variables:
            return
        for decl in self.can_file.variables.declarations:
            if decl.type_name == "msTimer":
                self.e.emit(f'{decl.name} = _TimerHandle("{decl.name}")', can_line=decl.line)
            else:
                init = self._gen_expr(decl.initializer) if decl.initializer else "0"
                self.e.emit(f"{decl.name} = {init}", can_line=decl.line)
        self.e.blank()

    # -----------------------------------------------------------------
    def _emit_handler_def(self, name: str, extra_param: str | None, body: ast.Block, line: int) -> None:
        params = "ctx" if extra_param is None else f"ctx, {extra_param}"
        self.e.emit(f"async def {name}({params}):", can_line=line)
        self.e.indent()
        self._emit_body(body, extra_globals=set())
        self.e.dedent()
        self.e.blank()

    def _emit_on_request(self, req: ast.OnRequest) -> None:
        name = self._next_name("handler")
        self.e.emit(f"async def {name}(ctx, msg):", can_line=req.line)
        self.e.indent()
        self._emit_body(req.body, extra_globals=set())
        self.e.dedent()
        self.e.blank()

        data_repr = "None"
        if req.data is not None:
            items = ", ".join(
                f"({b.value}, {b.is_wildcard})" for b in req.data.bytes
            )
            data_repr = f"({items},)" if items else "()"
        self._registrations.append(
            f"dispatch_table.register(can_id={req.can_id}, service={req.service}, "
            f"pid={req.pid!r}, data={data_repr}, fn={name})"
        )

    def _emit_on_timer(self, timer: ast.OnTimer) -> None:
        name = self._next_name("handler_timer")
        self.e.emit(f"async def {name}(ctx):", can_line=timer.line)
        self.e.indent()
        self._emit_body(timer.body, extra_globals=set())
        self.e.dedent()
        self.e.blank()
        self._registrations.append(f'timer_manager.on_expire("{timer.timer_name}", {name})')

    def _emit_on_message(self, msg: ast.OnMessage) -> None:
        name = self._next_name("handler_msg")
        self.e.emit(f"async def {name}(ctx, frame):", can_line=msg.line)
        self.e.indent()
        self._emit_body(msg.body, extra_globals=set())
        self.e.dedent()
        self.e.blank()
        self._registrations.append(f"dispatch_table.register_raw(can_id={msg.can_id}, fn={name})")

    def _emit_register_function(self) -> None:
        self.e.emit("def register(dispatch_table, timer_manager):")
        self.e.indent()
        if not self._registrations:
            self.e.emit("pass")
        for line in self._registrations:
            self.e.emit(line)
        self.e.dedent()

    def _emit_line_map(self) -> None:
        self.e.blank()
        self.e.blank()
        self.e.emit(f"__SIMLANG_LINEMAP__ = {self.e.line_map!r}")

    # -----------------------------------------------------------------
    # thân hàm: quét trước các Assign ghi vào biến global để chèn `global`
    def _emit_body(self, body: ast.Block, extra_globals: set[str]) -> None:
        written = self._collect_global_writes(body) | extra_globals
        if written:
            self.e.emit(f"global {', '.join(sorted(written))}")
        before = len(self.e.lines)
        for stmt in body.statements:
            self._gen_stmt(stmt)
        if len(self.e.lines) == before:
            self.e.emit("pass")

    def _collect_global_writes(self, node) -> set[str]:
        names: set[str] = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Assign) and isinstance(n.target, ast.Identifier):
                if n.target.name in self._global_names:
                    names.add(n.target.name)
        return names

    # -----------------------------------------------------------------
    def _gen_body_indented(self, stmt: ast.Stmt) -> None:
        before = len(self.e.lines)
        self._gen_stmt(stmt)
        if len(self.e.lines) == before:
            self.e.emit("pass")

    def _gen_stmt(self, stmt: ast.Stmt) -> None:
        if isinstance(stmt, ast.ExprStmt):
            self.e.emit(self._gen_expr(stmt.expr), can_line=stmt.line)
        elif isinstance(stmt, ast.Block):
            if not stmt.statements:
                self.e.emit("pass", can_line=stmt.line)
            for s in stmt.statements:
                self._gen_stmt(s)
        elif isinstance(stmt, ast.IfStmt):
            self.e.emit(f"if {self._gen_expr(stmt.condition)}:", can_line=stmt.line)
            self.e.indent()
            self._gen_body_indented(stmt.then_branch)
            self.e.dedent()
            if stmt.else_branch is not None:
                self.e.emit("else:", can_line=stmt.line)
                self.e.indent()
                self._gen_body_indented(stmt.else_branch)
                self.e.dedent()
        elif isinstance(stmt, ast.WhileStmt):
            self.e.emit(f"while {self._gen_expr(stmt.condition)}:", can_line=stmt.line)
            self.e.indent()
            self._gen_body_indented(stmt.body)
            self.e.dedent()
        elif isinstance(stmt, ast.ForStmt):
            self._gen_for(stmt)
        elif isinstance(stmt, ast.SwitchStmt):
            self._gen_switch(stmt)
        else:
            raise CodegenError(f"codegen: chưa hỗ trợ statement '{stmt.kind}'")

    def _gen_for(self, stmt: ast.ForStmt) -> None:
        if stmt.init is not None:
            self.e.emit(self._gen_expr(stmt.init), can_line=stmt.line)
        cond = self._gen_expr(stmt.condition) if stmt.condition is not None else "True"
        self.e.emit(f"while {cond}:", can_line=stmt.line)
        self.e.indent()
        self._gen_body_indented(stmt.body)
        if stmt.step is not None:
            self.e.emit(self._gen_expr(stmt.step), can_line=stmt.line)
        self.e.dedent()

    def _gen_switch(self, stmt: ast.SwitchStmt) -> None:
        self.e.emit(f"match {self._gen_expr(stmt.subject)}:", can_line=stmt.line)
        self.e.indent()
        if not stmt.cases:
            self.e.emit("case _: pass")
        for case in stmt.cases:
            if case.value is None:
                pattern = "_"
            elif isinstance(case.value, ast.Literal):
                pattern = case.value.raw
            else:
                raise CodegenError(
                    "codegen: 'case' chỉ hỗ trợ giá trị literal (Python match/case coi "
                    "tên biến trần là capture-pattern, không phải so sánh bằng)"
                )
            self.e.emit(f"case {pattern}:", can_line=case.line)
            self.e.indent()
            if not case.body:
                self.e.emit("pass")
            for s in case.body:
                self._gen_stmt(s)
            self.e.dedent()
        self.e.dedent()

    # -----------------------------------------------------------------
    def _gen_expr(self, expr: ast.Expr) -> str:
        if isinstance(expr, ast.Literal):
            if expr.literal_type == "string":
                return repr(expr.value)
            return expr.raw  # int/hex/float: text gốc luôn là literal Python hợp lệ
        if isinstance(expr, ast.Identifier):
            return expr.name
        if isinstance(expr, ast.Unary):
            if expr.op == "!":
                return f"(not {self._gen_expr(expr.operand)})"
            return f"({expr.op}{self._gen_expr(expr.operand)})"
        if isinstance(expr, ast.Binary):
            py_op = _BINARY_PY_OP.get(expr.op, expr.op)
            left = self._gen_expr(expr.left)
            right = self._gen_expr(expr.right)
            if expr.op in _BITWISE_OPS:
                # C/CAPL tự ép float->int khi dùng toán tử bit; Python thì
                # raise TypeError thẳng (vd `sin(...)` trả float rồi đem
                # `>> 8` — xảy ra THẬT trong chính ví dụ §5.1 của spec, vì
                # rpm được gán bằng biểu thức có sin()). Ép int() cả 2 vế
                # để khớp ngữ nghĩa C, không đổi kết quả khi đã là int sẵn.
                left, right = f"int({left})", f"int({right})"
            return f"({left} {py_op} {right})"
        if isinstance(expr, ast.Assign):
            target = self._gen_expr(expr.target)
            value = self._gen_expr(expr.value)
            return f"{target} {expr.op} {value}"
        if isinstance(expr, ast.Call):
            return self._gen_call(expr)
        raise CodegenError(f"codegen: chưa hỗ trợ expression '{expr.kind}'")

    def _gen_call(self, call: ast.Call) -> str:
        name = call.name
        args = [self._gen_expr(a) for a in call.args]
        arglist = ", ".join(args)
        if name == "delay":
            if len(args) != 1:
                raise CodegenError("delay() cần đúng 1 tham số (số mili-giây)")
            return f"(await asyncio.sleep(({args[0]}) / 1000))"
        if name in _ASYNC_CTX_BUILTINS:
            return f"(await ctx.{_ASYNC_CTX_BUILTINS[name]}({arglist}))"
        if name in _SYNC_CTX_BUILTINS:
            return f"ctx.{_SYNC_CTX_BUILTINS[name]}({arglist})"
        if name in _DIRECT_BUILTINS:
            return f"{_DIRECT_BUILTINS[name]}({arglist})"
        raise CodegenError(
            f"gọi hàm không rõ '{name}' — simlang chỉ hỗ trợ builtin, không có hàm tự định nghĩa "
            f"(xem danh sách builtin trong SPEC_SIMLANG_V2.md §5.4)"
        )


def generate(can_file: ast.CanFile) -> GeneratedModule:
    return _CodeGen(can_file).build()
