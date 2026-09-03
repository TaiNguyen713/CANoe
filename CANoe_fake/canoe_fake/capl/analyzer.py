"""Lightweight semantic checks on the CAPL AST.

The parser only catches syntax errors. The analyzer makes an additional pass
to flag common issues a real CAPL compiler would also report: calling an
undefined function, duplicate names, misusing `this`, a missing `return`,
and using `setTimer` on a non-timer variable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ast_nodes as ast
from . import builtins as bi
from . import keywords as kw
from .diagnostics import DiagnosticBag
from .includes import IncludedSymbols

_TIMER_FUNCS: frozenset[str] = frozenset({"setTimer", "setTimerCyclic", "cancelTimer",
                                          "isTimerActive"})
_TIMER_TYPES: frozenset[str] = frozenset({"timer", "msTimer", "mstimer"})


@dataclass
class Symbol:
    """A symbol used to build the outline tree and power autocomplete."""
    name: str
    kind: str            # function | testcase | handler | variable | struct | enum | param
    detail: str = ""
    line: int = 0
    column: int = 0
    children: list["Symbol"] = field(default_factory=list)


@dataclass
class AnalysisResult:
    unit: ast.CaplFile
    diagnostics: DiagnosticBag
    symbols: list[Symbol] = field(default_factory=list)
    global_names: set[str] = field(default_factory=set)
    function_names: set[str] = field(default_factory=set)
    included: IncludedSymbols | None = None


class Analyzer:
    def __init__(self, unit: ast.CaplFile, diagnostics: DiagnosticBag,
                 included: IncludedSymbols | None = None) -> None:
        self.unit = unit
        self.diag = diagnostics
        self.included = included or IncludedSymbols()
        #: functions/vars pulled from .cin files — treated as already existing
        self.globals: dict[str, ast.VarDecl] = dict(self.included.globals)
        self.functions: dict[str, ast.FunctionDecl] = dict(self.included.functions)
        self._external_globals: set[str] = set(self.included.globals)
        self.struct_names: set[str] = {s.name for s in unit.structs} | self.included.types
        self.enum_members: set[str] = {
            m.name for e in unit.enums for m in e.members
        }

    # ------------------------------------------------------------------
    def run(self) -> AnalysisResult:
        self._report_missing_includes()
        self._collect_globals()
        self._collect_functions()

        for block in self.unit.variables:
            for decl in block.declarations:
                self._check_expr(decl.initializer, scope=set(self.globals), context="")

        for fn in self.unit.functions:
            self._check_function(fn)
        for tc in self.unit.testcases:
            self._check_function(tc)
        for handler in self.unit.handlers:
            self._check_handler(handler)

        return AnalysisResult(
            unit=self.unit,
            diagnostics=self.diag,
            symbols=self._build_symbols(),
            global_names=set(self.globals),
            function_names=set(self.functions),
            included=self.included,
        )

    def _report_missing_includes(self) -> None:
        if not self.included.missing or self.unit.includes is None:
            return
        block = self.unit.includes
        for target in self.included.missing:
            self.diag.warning(
                "C3014",
                f"Included file not found: '{target}'. "
                "Functions declared in that file will be reported as undefined.",
                block.line, block.column, max(1, len(target)),
            )

    # ------------------------------------------------------------------
    def _collect_globals(self) -> None:
        local: set[str] = set()
        for block in self.unit.variables:
            for decl in block.declarations:
                if decl.name in local:
                    prev = self.globals[decl.name]
                    self.diag.error(
                        "C3001",
                        f"Global variable '{decl.name}' was already declared on line {prev.line}.",
                        decl.line, decl.column, len(decl.name),
                    )
                    continue
                if decl.name in self._external_globals:
                    self.diag.warning(
                        "C3013",
                        f"Variable '{decl.name}' has the same name as a variable in an "
                        "included file — this declaration will shadow that one.",
                        decl.line, decl.column, len(decl.name),
                    )
                local.add(decl.name)
                self.globals[decl.name] = decl

    def _collect_functions(self) -> None:
        local: set[str] = set()
        for fn in list(self.unit.functions) + list(self.unit.testcases):
            if fn.body is None:
                continue      # forward declaration
            if fn.name in local:
                prev = self.functions[fn.name]
                self.diag.error(
                    "C3002",
                    f"Function '{fn.name}' was already defined on line {prev.line}.",
                    fn.line, fn.column, len(fn.name),
                )
                continue
            local.add(fn.name)
            if bi.is_builtin(fn.name):
                self.diag.warning(
                    "C3003",
                    f"'{fn.name}' has the same name as a built-in CAPL function — "
                    "your definition will shadow the original.",
                    fn.line, fn.column, len(fn.name),
                )
            self.functions[fn.name] = fn

    # ------------------------------------------------------------------
    def _check_function(self, fn: ast.FunctionDecl) -> None:
        scope = set(self.globals) | {p.name for p in fn.params if p.name}
        if fn.body is not None:
            self._check_stmt(fn.body, scope, context="")
            if fn.return_type not in ("void", "") and not _has_return_with_value(fn.body):
                self.diag.warning(
                    "C3004",
                    f"Function '{fn.name}' declares a return type of '{fn.return_type}' "
                    "but has no 'return <value>;' statement.",
                    fn.line, fn.column, len(fn.name),
                )

    def _check_handler(self, handler: ast.EventHandler) -> None:
        scope = set(self.globals)
        # `on timer t` — variable t must be declared as a timer type
        if handler.event_type == "timer" and handler.selector:
            name = handler.selector.split()[0]
            decl = self.globals.get(name)
            if decl is None:
                self.diag.error(
                    "C3005",
                    f"Timer '{name}' was not declared in the 'variables' block. "
                    f"Add: msTimer {name};",
                    handler.line, handler.column, len(handler.display_name),
                )
            elif decl.type_name.split()[-1] not in _TIMER_TYPES:
                self.diag.error(
                    "C3006",
                    f"'{name}' has type '{decl.type_name}', not timer/msTimer.",
                    handler.line, handler.column, len(handler.display_name),
                )
        if handler.body is not None:
            self._check_stmt(handler.body, scope, context=handler.event_type)

    # ------------------------------------------------------------------
    def _check_stmt(self, stmt, scope: set[str], context: str) -> None:
        if stmt is None:
            return

        if isinstance(stmt, ast.Block):
            inner = set(scope)
            for s in stmt.statements:
                self._check_stmt(s, inner, context)
            return

        if isinstance(stmt, ast.VarDecl):
            if stmt.name in scope and stmt.name not in self.globals:
                self.diag.warning(
                    "C3007",
                    f"Variable '{stmt.name}' shadows a variable with the same name in an outer scope.",
                    stmt.line, stmt.column, len(stmt.name),
                )
            self._check_expr(stmt.initializer, scope, context)
            for dim in stmt.array_dims:
                self._check_expr(dim, scope, context)
            scope.add(stmt.name)
            return

        if isinstance(stmt, ast.ExprStmt):
            self._check_expr(stmt.expr, scope, context)
            return
        if isinstance(stmt, ast.IfStmt):
            self._check_expr(stmt.condition, scope, context)
            self._check_stmt(stmt.then_branch, set(scope), context)
            self._check_stmt(stmt.else_branch, set(scope), context)
            return
        if isinstance(stmt, ast.WhileStmt):
            self._check_expr(stmt.condition, scope, context)
            self._check_stmt(stmt.body, set(scope), context)
            return
        if isinstance(stmt, ast.DoWhileStmt):
            self._check_stmt(stmt.body, set(scope), context)
            self._check_expr(stmt.condition, scope, context)
            return
        if isinstance(stmt, ast.ForStmt):
            inner = set(scope)
            self._check_stmt(stmt.init, inner, context)
            self._check_expr(stmt.condition, inner, context)
            self._check_expr(stmt.step, inner, context)
            self._check_stmt(stmt.body, inner, context)
            return
        if isinstance(stmt, ast.SwitchStmt):
            self._check_expr(stmt.subject, scope, context)
            self._check_stmt(stmt.body, set(scope), context)
            return
        if isinstance(stmt, ast.CaseLabel):
            self._check_expr(stmt.value, scope, context)
            return
        if isinstance(stmt, ast.ReturnStmt):
            self._check_expr(stmt.value, scope, context)
            return

    # ------------------------------------------------------------------
    def _check_expr(self, expr, scope: set[str], context: str) -> None:
        if isinstance(expr, list):
            for item in expr:
                self._check_expr(item, scope, context)
            return
        # skip scalar fields (str/int/bool) of the AST node
        if not isinstance(expr, ast.Node):
            return

        if isinstance(expr, ast.ThisExpr):
            if not context:
                self.diag.error(
                    "C3008",
                    "'this' can only be used inside an event handler "
                    "(on message / on timer / on sysvar ...).",
                    expr.line, expr.column, 4,
                )
            return

        if isinstance(expr, ast.Member):
            self._check_this_member(expr, context)
            self._check_expr(expr.obj, scope, context)
            return

        if isinstance(expr, ast.Call):
            self._check_call(expr, scope, context)
            for arg in expr.args:
                self._check_expr(arg, scope, context)
            return

        if isinstance(expr, ast.Identifier):
            self._check_identifier(expr, scope)
            return

        for value in vars(expr).values():
            if isinstance(value, (ast.Node, list)):
                self._check_expr(value, scope, context)

    def _check_identifier(self, expr: ast.Identifier, scope: set[str]) -> None:
        name = expr.name
        if name in scope or name in self.functions or name in self.enum_members:
            return
        if name in kw.CONSTANTS or bi.is_builtin(name):
            return
        # Message/signal/ECU names come from the database — can't be verified
        # without loading it. Only hinted at Info level to avoid noise.
        self.diag.info(
            "C3100",
            f"'{name}' is not declared in this file. "
            "If this is a name from the database (message/signal/ECU), ignore this hint.",
            expr.line, expr.column, len(name),
        )

    def _check_this_member(self, expr: ast.Member, context: str) -> None:
        if not isinstance(expr.obj, ast.ThisExpr) or not context:
            return
        members = kw.this_members_for(context)
        if not members:
            return
        member = expr.member
        if member in members or f"{member}(x)" in members:
            return
        self.diag.warning(
            "C3009",
            f"'this.{member}' is not a valid property inside 'on {context}'. "
            f"Valid properties: {', '.join(sorted(members)[:8])}...",
            expr.line, expr.column, len(member),
        )

    def _check_call(self, expr: ast.Call, scope: set[str], context: str) -> None:
        name = expr.callee_name
        if not name:
            return

        # `this.byte(0)`, `msg.word(2)` — payload access, not a function call
        if isinstance(expr.callee, ast.Member):
            return

        if name in self.functions:
            fn = self.functions[name]
            required = sum(1 for p in fn.params if p.name)
            if len(expr.args) != required:
                self.diag.error(
                    "C3010",
                    f"Function '{name}' expects {required} argument(s) but got {len(expr.args)}. "
                    f"Signature: {fn.signature}",
                    expr.line, expr.column, len(name),
                )
            return

        builtin = bi.lookup(name)
        if builtin is not None:
            if name in _TIMER_FUNCS and expr.args:
                self._check_timer_argument(name, expr.args[0], scope)
            return

        if name in scope or name in self.struct_names:
            return

        close = _closest_name(name, list(bi.FUNCTIONS) + list(self.functions))
        hint = f" Did you mean to call '{close}'?" if close else ""
        self.diag.error(
            "C3011",
            f"Function '{name}' is not defined and is not a built-in CAPL function.{hint}",
            expr.line, expr.column, len(name),
        )

    def _check_timer_argument(self, func: str, arg, scope: set[str]) -> None:
        if not isinstance(arg, ast.Identifier):
            return
        decl = self.globals.get(arg.name)
        if decl is None:
            return       # local variable — type not tracked at this level
        if decl.type_name.split()[-1] not in _TIMER_TYPES:
            self.diag.error(
                "C3012",
                f"{func}() requires a timer/msTimer argument, "
                f"but '{arg.name}' has type '{decl.type_name}'.",
                arg.line, arg.column, len(arg.name),
            )

    # ------------------------------------------------------------------
    def _build_symbols(self) -> list[Symbol]:
        root: list[Symbol] = []

        if self.unit.includes and self.unit.includes.directives:
            node = Symbol("includes", "block",
                          f"{len(self.unit.includes.directives)} directive(s)",
                          self.unit.includes.line, self.unit.includes.column)
            for directive in self.unit.includes.directives:
                node.children.append(Symbol(directive, "include"))
            root.append(node)

        if self.unit.variables:
            total = sum(len(b.declarations) for b in self.unit.variables)
            node = Symbol("variables", "block", f"{total} variable(s)",
                          self.unit.variables[0].line, self.unit.variables[0].column)
            for block in self.unit.variables:
                for decl in block.declarations:
                    dims = "".join("[]" for _ in decl.array_dims)
                    detail = f"{decl.type_name} {decl.bus_selector}".strip()
                    node.children.append(
                        Symbol(f"{decl.name}{dims}", "variable", detail,
                               decl.line, decl.column)
                    )
            root.append(node)

        for struct in self.unit.structs:
            node = Symbol(struct.name, "struct", f"{len(struct.members)} member(s)",
                          struct.line, struct.column)
            for m in struct.members:
                node.children.append(Symbol(m.name, "variable", m.type_name, m.line, m.column))
            root.append(node)

        for enum in self.unit.enums:
            node = Symbol(enum.name, "enum", f"{len(enum.members)} constant(s)",
                          enum.line, enum.column)
            for m in enum.members:
                node.children.append(Symbol(m.name, "constant", "", m.line, m.column))
            root.append(node)

        for handler in self.unit.handlers:
            root.append(Symbol(handler.display_name, "handler",
                               f"on {handler.event_type}", handler.line, handler.column))

        for fn in self.unit.functions:
            root.append(Symbol(fn.name, "function", fn.signature, fn.line, fn.column))

        for tc in self.unit.testcases:
            root.append(Symbol(tc.name, "testcase", tc.signature, tc.line, tc.column))

        return root


# ---------------------------------------------------------------------------

def _has_return_with_value(node) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.ReturnStmt) and child.value is not None:
            return True
    return False


def _closest_name(word: str, candidates: list[str]) -> str | None:
    import difflib

    matches = difflib.get_close_matches(word, candidates, n=1, cutoff=0.75)
    return matches[0] if matches else None


def analyze(unit: ast.CaplFile, diagnostics: DiagnosticBag,
            included: IncludedSymbols | None = None) -> AnalysisResult:
    return Analyzer(unit, diagnostics, included).run()
