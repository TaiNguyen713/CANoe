"""Recursive-descent parser for CAPL.

The parser produces a `CaplFile` (AST) and a `DiagnosticBag`. It has a
panic-mode error-recovery mechanism: on invalid syntax, it skips ahead to the
nearest `;` or `}` and continues, so an error near the top of a file doesn't
wipe out the rest of the tree.
"""

from __future__ import annotations

from . import ast_nodes as ast
from . import keywords as kw
from .diagnostics import DiagnosticBag
from .lexer import Lexer, Token, TokenKind

#: các kiểu đối tượng bus cho phép đặt "selector" giữa kiểu và tên biến,
#: ví dụ `message 0x100 msg;` hay `diagRequest Door.Lock req;`
_SELECTOR_TYPES: frozenset[str] = frozenset(
    {
        "message", "multiplexed_message", "canMessage",
        "diagRequest", "diagResponse",
        "linFrame", "linMessage", "linSlaveResponse",
        "linUnconditionalFrame", "linEventTriggeredFrame", "linSporadicFrame",
        "frFrame", "frPDU", "pdu", "ethernetPacket", "signal", "serviceEvent",
    }
)

#: event không nhận selector — `on start`, `on preStart`, ...
_NO_SELECTOR_EVENTS: frozenset[str] = frozenset(
    {
        "start", "preStart", "prestart", "preStop", "stopMeasurement",
        "busOff", "errorActive", "errorPassive", "warningLimit", "canOverload",
        "errorFrame", "frStartCycle", "ethernetStatus",
    }
)

_ASSIGN_OPS: frozenset[str] = frozenset(
    {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}
)

_MODIFIERS: frozenset[str] = frozenset({"const", "static", "extern", "volatile", "export"})


class ParseError(Exception):
    """Internal exception used to jump to the nearest synchronization point."""


class Parser:
    def __init__(self, source: str, path: str = "",
                 diagnostics: DiagnosticBag | None = None) -> None:
        self.source = source
        self.path = path
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticBag()
        self.tokens: list[Token] = Lexer(source, self.diagnostics).tokenize()
        self.index = 0
        #: tên struct/enum do người dùng định nghĩa, dùng để nhận diện khai báo biến
        self.user_types: set[str] = set()
        #: struct/enum khai báo lồng bên trong variables{} hoặc thân hàm
        self._nested_structs: list[ast.StructDecl] = []
        self._nested_enums: list[ast.EnumDecl] = []

    # ==================================================================
    # Tiện ích duyệt token
    # ==================================================================
    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def peek(self, offset: int = 0) -> Token:
        i = min(self.index + offset, len(self.tokens) - 1)
        return self.tokens[i]

    def at_end(self) -> bool:
        return self.current.kind is TokenKind.EOF

    def advance(self) -> Token:
        tok = self.current
        if not self.at_end():
            self.index += 1
        return tok

    def check_op(self, *ops: str) -> bool:
        return self.current.is_op(*ops)

    def check_kw(self, *words: str) -> bool:
        return self.current.is_kw(*words)

    def match_op(self, *ops: str) -> Token | None:
        if self.check_op(*ops):
            return self.advance()
        return None

    def match_kw(self, *words: str) -> Token | None:
        if self.check_kw(*words):
            return self.advance()
        return None

    def expect_op(self, op: str, context: str = "") -> Token:
        if self.check_op(op):
            return self.advance()
        self._error("C1001", f"Missing '{op}'{f' {context}' if context else ''}, "
                             f"but found {self._describe(self.current)}.")
        raise ParseError

    def expect_identifier(self, context: str = "") -> Token:
        if self.current.kind is TokenKind.IDENTIFIER:
            return self.advance()
        self._error("C1002", f"Expected an identifier{f' {context}' if context else ''}, "
                             f"but found {self._describe(self.current)}.")
        raise ParseError

    @staticmethod
    def _describe(tok: Token) -> str:
        if tok.kind is TokenKind.EOF:
            return "end of file"
        return f"'{tok.value}'"

    def _error(self, code: str, message: str, tok: Token | None = None) -> None:
        t = tok or self.current
        self.diagnostics.error(code, message, t.line, t.column,
                               max(len(t.value), 1), t.offset)

    def _warn(self, code: str, message: str, tok: Token | None = None) -> None:
        t = tok or self.current
        self.diagnostics.warning(code, message, t.line, t.column,
                                 max(len(t.value), 1), t.offset)

    def _synchronize(self) -> None:
        """Skip tokens until it's safe to resume parsing."""
        depth = 0
        while not self.at_end():
            tok = self.current
            if tok.is_op("{"):
                depth += 1
            elif tok.is_op("}"):
                if depth == 0:
                    self.advance()
                    return
                depth -= 1
            elif tok.is_op(";") and depth == 0:
                self.advance()
                return
            elif depth == 0 and tok.is_kw("on", "variables", "includes", "testcase",
                                          "testfunction", "export", "struct", "enum"):
                return
            self.advance()

    # ==================================================================
    # Cấp cao nhất
    # ==================================================================
    def parse(self) -> ast.CaplFile:
        unit = ast.CaplFile(line=1, column=1, path=self.path)
        while not self.at_end():
            start_index = self.index
            try:
                self._parse_top_level(unit)
            except ParseError:
                self._synchronize()
            # chốt an toàn: nếu một vòng lặp không tiêu thụ token nào, ép tiến 1 bước
            if self.index == start_index and not self.at_end():
                self.advance()
        unit.structs.extend(self._nested_structs)
        unit.enums.extend(self._nested_enums)
        return unit

    def _parse_top_level(self, unit: ast.CaplFile) -> None:
        tok = self.current

        if tok.is_op(";"):
            self.advance()
            return

        if tok.kind is TokenKind.PREPROCESSOR:
            # #pragma / #include nằm ngoài khối includes vẫn hợp lệ
            if unit.includes is None:
                unit.includes = ast.IncludesBlock(tok.line, tok.column)
            unit.includes.directives.append(tok.value.strip())
            self.advance()
            return

        if tok.is_kw("includes"):
            unit.includes = self._parse_includes_block(unit.includes)
            return

        is_export = False
        if tok.is_kw("export"):
            # `export` có thể đứng trước variables / function / testcase
            if self.peek(1).is_kw("variables"):
                self.advance()
                block = self._parse_variables_block()
                block.is_export = True
                unit.variables.append(block)
                return
            is_export = True
            self.advance()
            tok = self.current

        if tok.is_kw("variables"):
            unit.variables.append(self._parse_variables_block())
            return

        if tok.is_kw("on"):
            unit.handlers.append(self._parse_event_handler())
            return

        if tok.is_kw("testcase", "testfunction"):
            unit.testcases.append(self._parse_testcase(is_export))
            return

        if tok.is_kw("struct") and self.peek(1).kind is TokenKind.IDENTIFIER \
                and self.peek(2).is_op("{"):
            decl = self._parse_struct_decl()
            unit.structs.append(decl)
            return

        if tok.is_kw("enum") and self.peek(1).kind is TokenKind.IDENTIFIER \
                and self.peek(2).is_op("{"):
            decl = self._parse_enum_decl()
            unit.enums.append(decl)
            return

        # còn lại: khai báo hàm ở cấp file
        if self._looks_like_function():
            unit.functions.append(self._parse_function(is_export))
            return

        self._error(
            "C1003",
            f"Unrecognized top-level declaration at {self._describe(tok)}. "
            "Outside a function only these are allowed: includes, variables, "
            "on <event>, testcase, struct, enum, or a function definition.",
        )
        raise ParseError

    # ------------------------------------------------------------------
    def _parse_includes_block(self, existing: ast.IncludesBlock | None) -> ast.IncludesBlock:
        tok = self.advance()   # 'includes'
        block = existing or ast.IncludesBlock(tok.line, tok.column)
        self.expect_op("{", "after the 'includes' keyword")
        while not self.at_end() and not self.check_op("}"):
            cur = self.current
            if cur.kind is TokenKind.PREPROCESSOR:
                block.directives.append(cur.value.strip())
                self.advance()
            elif cur.is_op(";"):
                self.advance()
            else:
                self._error("C1004",
                            "An 'includes' block may only contain preprocessor "
                            f"directives like #include \"file.cin\", but found {self._describe(cur)}.")
                self.advance()
        self.expect_op("}", "to close the 'includes' block")
        return block

    # ------------------------------------------------------------------
    def _parse_variables_block(self) -> ast.VariablesBlock:
        tok = self.advance()   # 'variables'
        block = ast.VariablesBlock(tok.line, tok.column)
        self.expect_op("{", "after the 'variables' keyword")
        while not self.at_end() and not self.check_op("}"):
            start_index = self.index
            try:
                if self.check_op(";"):
                    self.advance()
                    continue
                if self.check_kw("struct") and self.peek(2).is_op("{"):
                    self._nested_structs.append(self._parse_struct_decl())
                    continue
                if self.check_kw("enum") and self.peek(2).is_op("{"):
                    self._nested_enums.append(self._parse_enum_decl())
                    continue
                block.declarations.extend(self._parse_declaration())
            except ParseError:
                self._synchronize()
            if self.index == start_index and not self.at_end():
                self.advance()
        self.expect_op("}", "to close the 'variables' block")
        return block

    # ------------------------------------------------------------------
    def _parse_struct_decl(self) -> ast.StructDecl:
        tok = self.advance()   # 'struct'
        name_tok = self.expect_identifier("for the struct name")
        decl = ast.StructDecl(tok.line, tok.column, name=name_tok.value)
        self.user_types.add(name_tok.value)
        self.expect_op("{", "after the struct name")
        while not self.at_end() and not self.check_op("}"):
            start_index = self.index
            try:
                if self.check_op(";"):
                    self.advance()
                    continue
                decl.members.extend(self._parse_declaration())
            except ParseError:
                self._synchronize()
            if self.index == start_index and not self.at_end():
                self.advance()
        self.expect_op("}", "to close the struct")
        self.match_op(";")
        return decl

    def _parse_enum_decl(self) -> ast.EnumDecl:
        tok = self.advance()   # 'enum'
        name_tok = self.expect_identifier("for the enum name")
        decl = ast.EnumDecl(tok.line, tok.column, name=name_tok.value)
        self.user_types.add(name_tok.value)
        self.expect_op("{", "after the enum name")
        while not self.at_end() and not self.check_op("}"):
            if self.check_op(","):
                self.advance()
                continue
            member_tok = self.expect_identifier("for the enum constant name")
            member = ast.EnumMember(member_tok.line, member_tok.column, name=member_tok.value)
            if self.match_op("="):
                member.value = self._parse_ternary()
            decl.members.append(member)
            if not self.check_op(",") and not self.check_op("}"):
                self._error("C1005", "Enum constants must be separated by ','.")
                raise ParseError
        self.expect_op("}", "to close the enum")
        self.match_op(";")
        return decl

    # ------------------------------------------------------------------
    def _parse_event_handler(self) -> ast.EventHandler:
        on_tok = self.advance()   # 'on'
        ev = self.current
        if ev.kind not in (TokenKind.IDENTIFIER, TokenKind.KEYWORD, TokenKind.TYPE):
            self._error("C1006", f"'on' must be followed by an event type name, found {self._describe(ev)}.")
            raise ParseError
        event_type = self.advance().value

        if not kw.is_event_type(event_type):
            close = _closest(event_type, kw.EVENT_TYPES)
            hint = f" Did you mean 'on {close}'?" if close else ""
            self._warn("C2001",
                       f"'{event_type}' is not a known CAPL event type.{hint}", ev)

        # selector: mọi token cho tới dấu '{'
        selector_parts: list[str] = []
        while not self.at_end() and not self.check_op("{"):
            if self.check_op(";"):
                self._error("C1007",
                            f"Handler 'on {event_type}' is missing its body — a {{ ... }} block is required.")
                raise ParseError
            selector_parts.append(self.advance().value)
        selector = " ".join(selector_parts).replace(" :: ", "::").replace(" . ", ".")

        if event_type in _NO_SELECTOR_EVENTS and selector:
            self._warn("C2002",
                       f"'on {event_type}' does not take a selector; '{selector}' will be ignored.", ev)
        elif event_type not in _NO_SELECTOR_EVENTS and not selector \
                and kw.is_event_type(event_type):
            self._error("C1008",
                        f"'on {event_type}' requires a selector "
                        "(a name, an ID, or '*' for all).", ev)

        handler = ast.EventHandler(on_tok.line, on_tok.column,
                                   event_type=event_type, selector=selector)
        handler.body = self._parse_block()
        return handler

    # ------------------------------------------------------------------
    def _parse_testcase(self, is_export: bool) -> ast.TestCaseDecl:
        tok = self.advance()   # 'testcase' | 'testfunction'
        is_test_function = tok.value == "testfunction"

        return_type = "void"
        # `testfunction` có thể có kiểu trả về: testfunction long Check(...)
        if is_test_function and (self.current.kind is TokenKind.TYPE
                                 or self.current.value in self.user_types):
            if self.peek(1).kind is TokenKind.IDENTIFIER:
                return_type = self._parse_type_name()

        name_tok = self.expect_identifier("for the testcase name")
        decl = ast.TestCaseDecl(tok.line, tok.column, name=name_tok.value,
                                return_type=return_type, is_export=is_export,
                                is_test_function=is_test_function)
        decl.params = self._parse_parameter_list()
        decl.body = self._parse_block()
        return decl

    # ------------------------------------------------------------------
    def _looks_like_function(self) -> bool:
        """Distinguish `long foo(...)` (a function) from `long foo;` (a variable) at file scope."""
        save = self.index
        try:
            if not self._at_type_start():
                return False
            try:
                self._parse_type_name()
            except ParseError:
                return False
            if self.current.kind is not TokenKind.IDENTIFIER:
                return False
            return self.peek(1).is_op("(")
        finally:
            self.index = save

    def _at_type_start(self) -> bool:
        tok = self.current
        if tok.kind is TokenKind.TYPE:
            return True
        if tok.is_kw(*_MODIFIERS):
            return True
        if tok.kind is TokenKind.IDENTIFIER and tok.value in self.user_types:
            return True
        return False

    def _parse_type_name(self) -> str:
        """Reads the type portion, including modifiers and `struct X` / `enum X`."""
        parts: list[str] = []
        while self.check_kw(*_MODIFIERS):
            parts.append(self.advance().value)

        tok = self.current
        if tok.is_kw("struct", "enum", "union"):
            parts.append(self.advance().value)
            if self.current.kind is TokenKind.IDENTIFIER:
                parts.append(self.advance().value)
        elif tok.kind is TokenKind.TYPE:
            parts.append(self.advance().value)
        elif tok.kind is TokenKind.IDENTIFIER and tok.value in self.user_types:
            parts.append(self.advance().value)
        else:
            self._error("C1009", f"Expected a data type, found {self._describe(tok)}.")
            raise ParseError

        # con trỏ dạng `char*` (hiếm nhưng hợp lệ trong CAPL cho tham số)
        while self.check_op("*"):
            parts.append(self.advance().value)
        return " ".join(parts)

    def _parse_parameter_list(self) -> list[ast.Parameter]:
        self.expect_op("(", "to open the parameter list")
        params: list[ast.Parameter] = []
        if self.match_op(")"):
            return params
        while True:
            tok = self.current
            if tok.kind is TokenKind.TYPE and tok.value == "void" and self.peek(1).is_op(")"):
                self.advance()
                break
            type_name = self._parse_type_name()
            is_ref = bool(self.match_op("&"))
            name = ""
            if self.current.kind is TokenKind.IDENTIFIER:
                name = self.advance().value
            param = ast.Parameter(tok.line, tok.column, type_name=type_name,
                                  name=name, is_reference=is_ref)
            while self.check_op("["):
                self.advance()
                if self.check_op("]"):
                    param.array_dims.append(None)
                else:
                    param.array_dims.append(self._parse_ternary())
                self.expect_op("]", "to close the array declaration")
            params.append(param)
            if not self.match_op(","):
                break
        self.expect_op(")", "to close the parameter list")
        return params

    def _parse_function(self, is_export: bool) -> ast.FunctionDecl:
        tok = self.current
        return_type = self._parse_type_name()
        name_tok = self.expect_identifier("for the function name")
        fn = ast.FunctionDecl(tok.line, tok.column, return_type=return_type,
                              name=name_tok.value, is_export=is_export)
        fn.params = self._parse_parameter_list()
        if self.match_op(";"):
            fn.body = None      # khai báo trước (forward declaration)
            return fn
        fn.body = self._parse_block()
        return fn

    # ==================================================================
    # Khai báo biến
    # ==================================================================
    def _parse_declaration(self) -> list[ast.VarDecl]:
        start = self.current
        modifiers: list[str] = []
        while self.check_kw(*_MODIFIERS):
            modifiers.append(self.advance().value)

        base_type = self._parse_type_name()
        is_const = "const" in modifiers
        is_static = "static" in modifiers
        is_export = "export" in modifiers

        decls: list[ast.VarDecl] = []
        while True:
            selector, name_tok = self._parse_declarator_head(base_type)
            decl = ast.VarDecl(
                name_tok.line, name_tok.column,
                type_name=base_type, name=name_tok.value,
                is_const=is_const, is_static=is_static, is_export=is_export,
                bus_selector=selector,
            )
            while self.check_op("["):
                self.advance()
                if self.check_op("]"):
                    decl.array_dims.append(None)
                else:
                    decl.array_dims.append(self._parse_ternary())
                self.expect_op("]", "to close the array declaration")
            if self.match_op("="):
                decl.initializer = self._parse_initializer()
            decls.append(decl)
            if not self.match_op(","):
                break

        if not self.match_op(";"):
            self._error("C1010",
                        f"Missing ';' after the declaration of '{decls[-1].name}'.", start)
            raise ParseError
        return decls

    def _parse_declarator_head(self, base_type: str) -> tuple[str, Token]:
        """Split the selector (if any) off from the variable name.

        `message 0x100 msg;` -> selector='0x100', name='msg'
        `message msg;`       -> selector='',      name='msg'
        """
        simple_type = base_type.split()[-1] if base_type else ""
        if simple_type not in _SELECTOR_TYPES:
            return "", self.expect_identifier(f"for the variable name of type '{base_type}'")

        parts: list[Token] = []
        while True:
            tok = self.current
            if tok.kind in (TokenKind.IDENTIFIER, TokenKind.NUMBER):
                parts.append(self.advance())
            elif tok.is_op(".", "::", "*"):
                parts.append(self.advance())
            else:
                break
            # dừng khi token kế tiếp báo hiệu đã hết phần đầu khai báo
            nxt = self.current
            if nxt.is_op(";", ",", "[", "=") or nxt.kind is TokenKind.EOF:
                break

        if not parts:
            self._error("C1011", f"Declaration of '{base_type}' is missing a variable name.")
            raise ParseError

        name_tok = parts[-1]
        if name_tok.kind is not TokenKind.IDENTIFIER:
            self._error("C1012",
                        f"The variable name for type '{base_type}' must be an identifier, "
                        f"found '{name_tok.value}'.", name_tok)
            raise ParseError
        selector = "".join(t.value for t in parts[:-1]).strip()
        return selector, name_tok

    def _parse_initializer(self) -> ast.Expr | list[ast.Expr]:
        if self.check_op("{"):
            open_tok = self.advance()
            items: list[ast.Expr] = []
            while not self.at_end() and not self.check_op("}"):
                if self.check_op(","):
                    self.advance()
                    continue
                if self.check_op("{"):
                    nested = self._parse_initializer()
                    items.append(nested if isinstance(nested, ast.Expr)
                                 else ast.Literal(open_tok.line, open_tok.column,
                                                  value=nested, raw="{...}",
                                                  literal_type="array"))
                    continue
                items.append(self._parse_ternary())
            self.expect_op("}", "to close the initializer list")
            return items
        return self._parse_assignment()

    # ==================================================================
    # Câu lệnh
    # ==================================================================
    def _parse_block(self) -> ast.Block:
        open_tok = self.expect_op("{", "to open the statement block")
        block = ast.Block(open_tok.line, open_tok.column)
        while not self.at_end() and not self.check_op("}"):
            start_index = self.index
            try:
                stmt = self._parse_statement()
                if stmt is not None:
                    block.statements.append(stmt)
            except ParseError:
                self._synchronize()
            if self.index == start_index and not self.at_end():
                self.advance()
        self.expect_op("}", "to close the statement block")
        return block

    def _parse_statement(self) -> ast.Stmt | None:
        tok = self.current

        if tok.is_op("{"):
            return self._parse_block()
        if tok.is_op(";"):
            self.advance()
            return ast.EmptyStmt(tok.line, tok.column)
        if tok.kind is TokenKind.PREPROCESSOR:
            self.advance()
            return None

        if tok.is_kw("if"):
            return self._parse_if()
        if tok.is_kw("while"):
            return self._parse_while()
        if tok.is_kw("do"):
            return self._parse_do_while()
        if tok.is_kw("for"):
            return self._parse_for()
        if tok.is_kw("switch"):
            return self._parse_switch()
        if tok.is_kw("case"):
            self.advance()
            value = self._parse_ternary()
            self.expect_op(":", "after the 'case' label")
            return ast.CaseLabel(tok.line, tok.column, value=value)
        if tok.is_kw("default") and self.peek(1).is_op(":"):
            self.advance()
            self.advance()
            return ast.CaseLabel(tok.line, tok.column, value=None)
        if tok.is_kw("break"):
            self.advance()
            self.expect_op(";", "after 'break'")
            return ast.BreakStmt(tok.line, tok.column)
        if tok.is_kw("continue"):
            self.advance()
            self.expect_op(";", "after 'continue'")
            return ast.ContinueStmt(tok.line, tok.column)
        if tok.is_kw("return"):
            self.advance()
            value = None if self.check_op(";") else self._parse_expression()
            self.expect_op(";", "after 'return'")
            return ast.ReturnStmt(tok.line, tok.column, value=value)
        if tok.is_kw("goto"):
            self.advance()
            label = self.expect_identifier("for the goto label")
            self.expect_op(";", "after 'goto'")
            return ast.GotoStmt(tok.line, tok.column, label=label.value)
        if tok.is_kw("struct") and self.peek(1).kind is TokenKind.IDENTIFIER \
                and self.peek(2).is_op("{"):
            return self._parse_struct_decl()
        if tok.is_kw("enum") and self.peek(1).kind is TokenKind.IDENTIFIER \
                and self.peek(2).is_op("{"):
            return self._parse_enum_decl()

        # nhãn cho goto: `label:`
        if tok.kind is TokenKind.IDENTIFIER and self.peek(1).is_op(":") \
                and not self.peek(1).is_op("::"):
            self.advance()
            self.advance()
            return ast.LabelStmt(tok.line, tok.column, name=tok.value)

        if self._at_declaration_start():
            decls = self._parse_declaration()
            if len(decls) == 1:
                return decls[0]
            block = ast.Block(decls[0].line, decls[0].column)
            block.statements.extend(decls)
            return block

        expr = self._parse_expression()
        self.expect_op(";", "at the end of the statement")
        return ast.ExprStmt(tok.line, tok.column, expr=expr)

    def _at_declaration_start(self) -> bool:
        tok = self.current
        if tok.kind is TokenKind.TYPE:
            # `message` cũng có thể mở đầu biểu thức? Không — trong CAPL nó luôn là kiểu.
            return True
        if tok.is_kw(*_MODIFIERS):
            return True
        if tok.is_kw("struct", "enum", "union"):
            return True
        if tok.kind is TokenKind.IDENTIFIER and tok.value in self.user_types \
                and self.peek(1).kind is TokenKind.IDENTIFIER:
            return True
        return False

    def _parse_if(self) -> ast.IfStmt:
        tok = self.advance()
        self.expect_op("(", "after 'if'")
        cond = self._parse_expression()
        self.expect_op(")", "to close the 'if' condition")
        node = ast.IfStmt(tok.line, tok.column, condition=cond)
        node.then_branch = self._parse_statement()
        if self.match_kw("else"):
            node.else_branch = self._parse_statement()
        return node

    def _parse_while(self) -> ast.WhileStmt:
        tok = self.advance()
        self.expect_op("(", "after 'while'")
        cond = self._parse_expression()
        self.expect_op(")", "to close the 'while' condition")
        node = ast.WhileStmt(tok.line, tok.column, condition=cond)
        node.body = self._parse_statement()
        return node

    def _parse_do_while(self) -> ast.DoWhileStmt:
        tok = self.advance()
        node = ast.DoWhileStmt(tok.line, tok.column)
        node.body = self._parse_statement()
        if not self.match_kw("while"):
            self._error("C1013", "A 'do' block must end with 'while (condition);'.")
            raise ParseError
        self.expect_op("(", "after 'while'")
        node.condition = self._parse_expression()
        self.expect_op(")", "to close the 'while' condition")
        self.expect_op(";", "after 'do ... while (...)'")
        return node

    def _parse_for(self) -> ast.ForStmt:
        tok = self.advance()
        self.expect_op("(", "after 'for'")
        node = ast.ForStmt(tok.line, tok.column)

        if self.check_op(";"):
            self.advance()
        elif self._at_declaration_start():
            decls = self._parse_declaration()   # đã tự tiêu thụ dấu ';'
            if len(decls) == 1:
                node.init = decls[0]
            else:
                blk = ast.Block(decls[0].line, decls[0].column)
                blk.statements.extend(decls)
                node.init = blk
        else:
            init_expr = self._parse_expression()
            self.expect_op(";", "after the 'for' initializer")
            node.init = ast.ExprStmt(init_expr.line, init_expr.column, expr=init_expr)

        if not self.check_op(";"):
            node.condition = self._parse_expression()
        self.expect_op(";", "after the 'for' condition")

        if not self.check_op(")"):
            node.step = self._parse_expression()
        self.expect_op(")", "to close the 'for' header")
        node.body = self._parse_statement()
        return node

    def _parse_switch(self) -> ast.SwitchStmt:
        tok = self.advance()
        self.expect_op("(", "after 'switch'")
        subject = self._parse_expression()
        self.expect_op(")", "to close the 'switch' expression")
        node = ast.SwitchStmt(tok.line, tok.column, subject=subject)
        node.body = self._parse_block()
        return node

    # ==================================================================
    # Biểu thức
    # ==================================================================
    def _parse_expression(self) -> ast.Expr:
        """A full expression, including the comma operator (used in 'for')."""
        expr = self._parse_assignment()
        while self.check_op(","):
            tok = self.advance()
            right = self._parse_assignment()
            expr = ast.Binary(tok.line, tok.column, op=",", left=expr, right=right)
        return expr

    def _parse_assignment(self) -> ast.Expr:
        left = self._parse_ternary()
        if self.current.kind is TokenKind.OPERATOR and self.current.value in _ASSIGN_OPS:
            tok = self.advance()
            value = self._parse_assignment()
            if not _is_assignable(left):
                self._error("C1014",
                            "The left-hand side of an assignment must be a variable, an "
                            "array element, a struct member, a sysvar, or a signal.", tok)
            return ast.Assign(tok.line, tok.column, op=tok.value, target=left, value=value)
        return left

    def _parse_ternary(self) -> ast.Expr:
        cond = self._parse_binary(0)
        if self.check_op("?"):
            tok = self.advance()
            if_true = self._parse_assignment()
            self.expect_op(":", "in the '? :' conditional expression")
            if_false = self._parse_ternary()
            return ast.Ternary(tok.line, tok.column, condition=cond,
                               if_true=if_true, if_false=if_false)
        return cond

    #: mức ưu tiên toán tử nhị phân, thấp -> cao
    _BINARY_LEVELS: tuple[tuple[str, ...], ...] = (
        ("||",),
        ("&&",),
        ("|",),
        ("^",),
        ("&",),
        ("==", "!="),
        ("<", ">", "<=", ">="),
        ("<<", ">>"),
        ("+", "-"),
        ("*", "/", "%"),
    )

    def _parse_binary(self, level: int) -> ast.Expr:
        if level >= len(self._BINARY_LEVELS):
            return self._parse_unary()
        ops = self._BINARY_LEVELS[level]
        left = self._parse_binary(level + 1)
        while self.current.kind is TokenKind.OPERATOR and self.current.value in ops:
            tok = self.advance()
            right = self._parse_binary(level + 1)
            left = ast.Binary(tok.line, tok.column, op=tok.value, left=left, right=right)
        return left

    def _parse_unary(self) -> ast.Expr:
        tok = self.current

        if tok.is_op("++", "--", "-", "+", "!", "~", "&", "*"):
            self.advance()
            operand = self._parse_unary()
            return ast.Unary(tok.line, tok.column, op=tok.value, operand=operand)

        if tok.is_kw("sizeof"):
            self.advance()
            if self.match_op("("):
                if self._at_type_start():
                    type_name = self._parse_type_name()
                    self.expect_op(")", "to close 'sizeof'")
                    return ast.SizeOf(tok.line, tok.column, operand=type_name)
                inner = self._parse_expression()
                self.expect_op(")", "to close 'sizeof'")
                return ast.SizeOf(tok.line, tok.column, operand=inner)
            return ast.SizeOf(tok.line, tok.column, operand=self._parse_unary())

        # ép kiểu: (byte)x  — chỉ khi trong ngoặc đúng là một tên kiểu
        if tok.is_op("(") and self._is_cast_ahead():
            self.advance()
            type_name = self._parse_type_name()
            self.expect_op(")", "to close the type cast")
            operand = self._parse_unary()
            return ast.Cast(tok.line, tok.column, type_name=type_name, operand=operand)

        return self._parse_postfix()

    def _is_cast_ahead(self) -> bool:
        nxt = self.peek(1)
        if nxt.kind is TokenKind.TYPE and nxt.value != "void":
            after = self.peek(2)
            return after.is_op(")") or after.is_op("*")
        return False

    def _parse_postfix(self) -> ast.Expr:
        expr = self._parse_primary()
        while True:
            tok = self.current
            if tok.is_op("("):
                self.advance()
                args: list[ast.Expr] = []
                if not self.check_op(")"):
                    while True:
                        args.append(self._parse_assignment())
                        if not self.match_op(","):
                            break
                self.expect_op(")", "to close the argument list")
                expr = ast.Call(tok.line, tok.column, callee=expr, args=args)
            elif tok.is_op("["):
                self.advance()
                index = self._parse_expression()
                self.expect_op("]", "to close the array access")
                expr = ast.Index(tok.line, tok.column, obj=expr, index=index)
            elif tok.is_op(".", "->"):
                self.advance()
                member = self.current
                if member.kind not in (TokenKind.IDENTIFIER, TokenKind.KEYWORD,
                                       TokenKind.TYPE, TokenKind.NUMBER):
                    self._error("C1015",
                                f"'{tok.value}' must be followed by a member name, "
                                f"found {self._describe(member)}.")
                    raise ParseError
                self.advance()
                expr = ast.Member(tok.line, tok.column, obj=expr,
                                  member=member.value, arrow=tok.value == "->")
            elif tok.is_op("++", "--"):
                self.advance()
                expr = ast.Unary(tok.line, tok.column, op=tok.value,
                                 operand=expr, postfix=True)
            else:
                return expr

    def _parse_primary(self) -> ast.Expr:
        tok = self.current

        if tok.kind is TokenKind.NUMBER:
            self.advance()
            return _number_literal(tok)

        if tok.kind is TokenKind.STRING:
            self.advance()
            return ast.Literal(tok.line, tok.column, value=_unquote(tok.value),
                               raw=tok.value, literal_type="string")

        if tok.kind is TokenKind.CHAR:
            self.advance()
            return ast.Literal(tok.line, tok.column, value=_unquote(tok.value),
                               raw=tok.value, literal_type="char")

        if tok.is_kw("this"):
            self.advance()
            return ast.ThisExpr(tok.line, tok.column)

        if tok.is_op("@"):
            self.advance()
            path = self._parse_scoped_name("after '@' to access a system variable")
            return ast.SysVarAccess(tok.line, tok.column, path=path)

        if tok.is_op("$"):
            self.advance()
            path = self._parse_scoped_name("after '$' to access a signal")
            raw = False
            if self.check_op(".") and self.peek(1).value in ("raw", "phys"):
                self.advance()
                raw = self.advance().value == "raw"
            return ast.SignalAccess(tok.line, tok.column, path=path, raw_value=raw)

        if tok.is_op("("):
            self.advance()
            inner = self._parse_expression()
            self.expect_op(")", "to close the parenthesized expression")
            return inner

        if tok.kind is TokenKind.IDENTIFIER or tok.kind is TokenKind.TYPE:
            if self.peek(1).is_op("::"):
                return self._parse_scoped_name()
            self.advance()
            return ast.Identifier(tok.line, tok.column, name=tok.value)

        if tok.kind is TokenKind.KEYWORD and tok.value in kw.CONSTANTS:
            self.advance()
            return ast.Identifier(tok.line, tok.column, name=tok.value)

        self._error("C1016", f"Unexpected {self._describe(tok)} in expression.")
        raise ParseError

    def _parse_scoped_name(self, context: str = "") -> ast.ScopedName:
        tok = self.current
        if tok.kind not in (TokenKind.IDENTIFIER, TokenKind.TYPE, TokenKind.KEYWORD):
            self._error("C1017", f"Expected a name{f' {context}' if context else ''}, "
                                 f"found {self._describe(tok)}.")
            raise ParseError
        parts = [self.advance().value]
        while self.check_op("::"):
            self.advance()
            nxt = self.current
            if nxt.kind not in (TokenKind.IDENTIFIER, TokenKind.TYPE, TokenKind.KEYWORD):
                self._error("C1018", f"'::' must be followed by a name, found {self._describe(nxt)}.")
                raise ParseError
            parts.append(self.advance().value)
        return ast.ScopedName(tok.line, tok.column, parts=parts)


# ---------------------------------------------------------------------------
# Hàm phụ trợ
# ---------------------------------------------------------------------------

def _is_assignable(expr: ast.Expr) -> bool:
    if isinstance(expr, (ast.Identifier, ast.Index, ast.Member,
                         ast.SysVarAccess, ast.SignalAccess, ast.ScopedName)):
        return True
    if isinstance(expr, ast.Unary) and expr.op == "*" and not expr.postfix:
        return True
    if isinstance(expr, ast.Call):
        # `this.byte(0) = 5` hợp lệ trong CAPL
        return isinstance(expr.callee, ast.Member)
    return False


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        body = raw[1:-1]
    else:
        body = raw.lstrip("\"'")
    return (body.replace("\\n", "\n").replace("\\t", "\t")
                .replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\"))


def _number_literal(tok: "Token") -> ast.Literal:
    text = tok.value.rstrip("uUlLfF")
    try:
        if text[:2].lower() == "0x":
            return ast.Literal(tok.line, tok.column, value=int(text, 16),
                               raw=tok.value, literal_type="int")
        if text[:2].lower() == "0b":
            return ast.Literal(tok.line, tok.column, value=int(text[2:], 2),
                               raw=tok.value, literal_type="int")
        if "." in text or "e" in text.lower():
            return ast.Literal(tok.line, tok.column, value=float(text),
                               raw=tok.value, literal_type="float")
        return ast.Literal(tok.line, tok.column, value=int(text, 10),
                           raw=tok.value, literal_type="int")
    except ValueError:
        return ast.Literal(tok.line, tok.column, value=0,
                           raw=tok.value, literal_type="int")


def _closest(word: str, candidates) -> str | None:
    """Suggest the closest matching name (used for 'did you mean...' hints)."""
    import difflib

    matches = difflib.get_close_matches(word, list(candidates), n=1, cutoff=0.7)
    return matches[0] if matches else None


def parse(source: str, path: str = "") -> tuple[ast.CaplFile, DiagnosticBag]:
    """Parse CAPL source, returning (AST, diagnostics)."""
    p = Parser(source, path)
    unit = p.parse()
    return unit, p.diagnostics
