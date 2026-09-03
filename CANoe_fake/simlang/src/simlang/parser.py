"""Lark → AST cho ngôn ngữ `.can`. Ném `SimlangSyntaxError` (có line/column)
khi cú pháp sai — không bao giờ trả về AST một phần im lặng."""

from __future__ import annotations

from pathlib import Path

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import UnexpectedInput

from . import ast_nodes as ast

_GRAMMAR_PATH = Path(__file__).resolve().parents[2] / "grammar" / "simlang.lark"


class SimlangSyntaxError(Exception):
    def __init__(self, message: str, line: int, column: int):
        super().__init__(f"({line}:{column}) {message}")
        self.message = message
        self.line = line
        self.column = column


def _pos(tok_or_tree) -> tuple[int, int]:
    meta = getattr(tok_or_tree, "meta", None)
    if meta is not None and not getattr(meta, "empty", False):
        return meta.line, meta.column
    if isinstance(tok_or_tree, Token):
        return tok_or_tree.line or 0, tok_or_tree.column or 0
    return 0, 0


@v_args(meta=True)
class _AstBuilder(Transformer):
    """Mỗi phương thức khớp tên rule/alt trong simlang.lark. `meta` (nhờ
    v_args(meta=True)) mang line/column của toàn bộ rule đó."""

    # ---- top level ----
    def start(self, meta, children):
        can_file = ast.CanFile(line=1, column=1)
        for child in children:
            if isinstance(child, ast.VariablesBlock):
                can_file.variables = child
            elif isinstance(child, ast.OnStart):
                can_file.on_start = child
            elif isinstance(child, ast.OnStop):
                can_file.on_stop = child
            elif isinstance(child, ast.OnTimer):
                can_file.on_timers.append(child)
            elif isinstance(child, ast.OnMessage):
                can_file.on_messages.append(child)
            elif isinstance(child, ast.OnRequest):
                can_file.on_requests.append(child)
        return can_file

    def event_handler(self, meta, children):
        return children[0]

    def variables_block(self, meta, children):
        line, col = meta.line, meta.column
        return ast.VariablesBlock(line=line, column=col, declarations=list(children))

    def var_decl(self, meta, children):
        line, col = meta.line, meta.column
        type_tok: Token = children[0]
        # array_suffix (nếu có) đứng TRƯỚC NAME, initializer đứng SAU NAME —
        # quét theo kiểu thay vì vị trí cố định vì cả hai đều optional độc lập.
        is_array = False
        array_size = None
        name_tok: Token | None = None
        initializer = None
        for item in children[1:]:
            if isinstance(item, _ArraySuffix):
                is_array = True
                array_size = item.size
            elif isinstance(item, ast.Expr):
                initializer = item
            elif isinstance(item, Token):
                name_tok = item
        return ast.VarDecl(
            line=line, column=col,
            type_name=str(type_tok), name=str(name_tok),
            is_array=is_array, array_size=array_size, initializer=initializer,
        )

    def array_suffix(self, meta, children):
        size = int(children[0]) if children else None
        return _ArraySuffix(size)

    # ---- event handlers ----
    def on_start(self, meta, children):
        return ast.OnStart(line=meta.line, column=meta.column, body=children[0])

    def on_stop(self, meta, children):
        return ast.OnStop(line=meta.line, column=meta.column, body=children[0])

    def on_timer(self, meta, children):
        name_tok, body = children
        return ast.OnTimer(line=meta.line, column=meta.column, timer_name=str(name_tok), body=body)

    def on_message(self, meta, children):
        can_id_expr, body = children
        return ast.OnMessage(line=meta.line, column=meta.column, can_id=can_id_expr.value, body=body)

    def on_request(self, meta, children):
        can_id_expr = children[0]
        service_expr = children[1]
        rest = children[2:]
        pid = None
        data = None
        body = None
        for item in rest:
            if isinstance(item, _PidClause):
                pid = item.value
            elif isinstance(item, ast.DataClause):
                data = item
            elif isinstance(item, ast.Block):
                body = item
        return ast.OnRequest(
            line=meta.line, column=meta.column,
            can_id=can_id_expr.value, service=service_expr.value,
            pid=pid, data=data, body=body,
        )

    def pid_clause(self, meta, children):
        return _PidClause(children[0].value)

    def data_clause(self, meta, children):
        return ast.DataClause(line=meta.line, column=meta.column, bytes=list(children))

    def byte_concrete(self, meta, children):
        return ast.ByteMatch(line=meta.line, column=meta.column, value=children[0].value)

    def byte_wild(self, meta, children):
        return ast.ByteMatch(line=meta.line, column=meta.column, is_wildcard=True)

    # ---- statements ----
    def block(self, meta, children):
        return ast.Block(line=meta.line, column=meta.column, statements=list(children))

    def if_stmt(self, meta, children):
        cond = children[0]
        then_b = children[1]
        else_b = children[2] if len(children) > 2 else None
        return ast.IfStmt(line=meta.line, column=meta.column, condition=cond, then_branch=then_b, else_branch=else_b)

    def while_stmt(self, meta, children):
        cond, body = children
        return ast.WhileStmt(line=meta.line, column=meta.column, condition=cond, body=body)

    def for_stmt(self, meta, children):
        # grammar dùng [expr] (maybe_placeholders=True) nên children LUÔN
        # có đúng 4 phần tử theo thứ tự cố định: init, cond, step, body —
        # không lệch vị trí dù thiếu clause nào.
        init, cond, step, body = children
        return ast.ForStmt(line=meta.line, column=meta.column, init=init, condition=cond, step=step, body=body)

    def switch_stmt(self, meta, children):
        subject, *cases = children
        return ast.SwitchStmt(line=meta.line, column=meta.column, subject=subject, cases=list(cases))

    def case_value(self, meta, children):
        value, *body = children
        return ast.CaseClause(line=meta.line, column=meta.column, value=value, body=list(body))

    def case_default(self, meta, children):
        return ast.CaseClause(line=meta.line, column=meta.column, value=None, body=list(children))

    def expr_stmt(self, meta, children):
        return ast.ExprStmt(line=meta.line, column=meta.column, expr=children[0])

    # ---- expressions ----
    def assign_expr(self, meta, children):
        target, op_tok, value = children
        return ast.Assign(line=meta.line, column=meta.column, op=str(op_tok), target=target, value=value)

    def or_expr(self, meta, children):
        # OR_OP/AND_OP là terminal CÓ TÊN (khác "&","|","^" ẩn danh) nên
        # KHÔNG bị Lark tự lọc khỏi cây — 3 children (left, op, right).
        left, _op_tok, right = children
        return ast.Binary(line=meta.line, column=meta.column, op="||", left=left, right=right)

    def and_expr(self, meta, children):
        left, _op_tok, right = children
        return ast.Binary(line=meta.line, column=meta.column, op="&&", left=left, right=right)

    def bitor_expr(self, meta, children):
        return self._binary(meta, "|", children)

    def bitxor_expr(self, meta, children):
        return self._binary(meta, "^", children)

    def bitand_expr(self, meta, children):
        return self._binary(meta, "&", children)

    def eq_expr(self, meta, children):
        left, op_tok, right = children
        return ast.Binary(line=meta.line, column=meta.column, op=str(op_tok), left=left, right=right)

    def rel_expr(self, meta, children):
        left, op_tok, right = children
        return ast.Binary(line=meta.line, column=meta.column, op=str(op_tok), left=left, right=right)

    def shift_expr(self, meta, children):
        left, op_tok, right = children
        return ast.Binary(line=meta.line, column=meta.column, op=str(op_tok), left=left, right=right)

    def add_expr(self, meta, children):
        left, op_tok, right = children
        return ast.Binary(line=meta.line, column=meta.column, op=str(op_tok), left=left, right=right)

    def mul_expr(self, meta, children):
        left, op_tok, right = children
        return ast.Binary(line=meta.line, column=meta.column, op=str(op_tok), left=left, right=right)

    def _binary(self, meta, op, children):
        left, right = children
        return ast.Binary(line=meta.line, column=meta.column, op=op, left=left, right=right)

    def unary_expr(self, meta, children):
        op_tok, operand = children
        return ast.Unary(line=meta.line, column=meta.column, op=str(op_tok), operand=operand)

    def call_expr(self, meta, children):
        name_tok, args = children
        return ast.Call(line=meta.line, column=meta.column, name=str(name_tok), args=args)

    def call_suffix(self, meta, children):
        return list(children)

    def hexint(self, meta, children):
        tok = children[0]
        return ast.Literal(line=meta.line, column=meta.column, value=int(str(tok), 16), raw=str(tok), literal_type="hex")

    def dec_literal(self, meta, children):
        tok = children[0]
        return ast.Literal(line=meta.line, column=meta.column, value=int(str(tok)), raw=str(tok), literal_type="int")

    def float_literal(self, meta, children):
        tok = children[0]
        return ast.Literal(line=meta.line, column=meta.column, value=float(str(tok)), raw=str(tok), literal_type="float")

    def string_literal(self, meta, children):
        tok = children[0]
        raw = str(tok)
        return ast.Literal(line=meta.line, column=meta.column, value=raw[1:-1], raw=raw, literal_type="string")

    def identifier(self, meta, children):
        tok = children[0]
        return ast.Identifier(line=meta.line, column=meta.column, name=str(tok))


class _ArraySuffix:
    def __init__(self, size: int | None):
        self.size = size


class _PidClause:
    def __init__(self, value: int):
        self.value = value


def _build_lark_parser() -> Lark:
    grammar_text = _GRAMMAR_PATH.read_text(encoding="utf-8")
    return Lark(grammar_text, parser="lalr", propagate_positions=True, maybe_placeholders=True)


_lark_parser: Lark | None = None


def _get_lark_parser() -> Lark:
    global _lark_parser
    if _lark_parser is None:
        _lark_parser = _build_lark_parser()
    return _lark_parser


def parse(source: str, path: str = "<string>") -> ast.CanFile:
    parser = _get_lark_parser()
    try:
        tree = parser.parse(source)
    except UnexpectedInput as exc:
        line = getattr(exc, "line", 0) or 0
        column = getattr(exc, "column", 0) or 0
        raise SimlangSyntaxError(str(exc).splitlines()[0], line, column) from exc
    can_file = _AstBuilder().transform(tree)
    can_file.path = path
    return can_file


def parse_file(path: str | Path) -> ast.CanFile:
    p = Path(path)
    return parse(p.read_text(encoding="utf-8"), path=str(p))
