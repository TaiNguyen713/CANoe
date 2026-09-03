"""Test cho grammar + parser (M2) — mọi cú pháp §5 của SPEC_SIMLANG_V2.md
phải parse được, lỗi cú pháp phải mang đúng line/column."""

from __future__ import annotations

import pytest

from simlang import ast_nodes as ast
from simlang.parser import SimlangSyntaxError, parse

SPEC_5_1_EXAMPLE = '''
variables {
    int  dtcCleared = 0;
    int  rpm = 800;
    msTimer rpmTimer;
}

on start {
    loadStatic("2008_Audi_A6.sim");
    setTimer(rpmTimer, 100);
}

// responsePending
on request 0x7E0 service 0x31 {
    output(0x7F, 0x31, 0x78);
    delay(2000);
    output(0x7F, 0x31, 0x78);
    delay(2000);
    output(0x71, 0x01, 0x02, 0x03);
}

// trạng thái sau erase
on request 0x7DF service 0x04 {
    dtcCleared = 1;
    output(0x44);
}

on request 0x7DF service 0x03 {
    if (dtcCleared)
        output(0x43, 0x00);
    else
        output(0x43, 0x02, 0x01, 0x33, 0x01, 0x71);
}

// live data theo thời gian
on timer rpmTimer {
    rpm = 800 + 1100 * sin(elapsed() / 3.0);
    setTimer(rpmTimer, 100);
}

on request 0x7DF service 0x01 pid 0x0C {
    output(0x41, 0x0C, (rpm * 4) >> 8, (rpm * 4) & 0xFF);
}
'''


def test_full_5_1_example_parses():
    f = parse(SPEC_5_1_EXAMPLE, path="example_5_1.can")
    assert [d.name for d in f.variables.declarations] == ["dtcCleared", "rpm", "rpmTimer"]
    assert f.variables.declarations[2].type_name == "msTimer"
    assert len(f.on_start.body.statements) == 2
    assert [ (r.can_id, r.service, r.pid) for r in f.on_requests ] == [
        (0x7E0, 0x31, None),
        (0x7DF, 0x04, None),
        (0x7DF, 0x03, None),
        (0x7DF, 0x01, 0x0C),
    ]
    assert f.on_timers[0].timer_name == "rpmTimer"
    if_stmt = f.on_requests[2].body.statements[0]
    assert isinstance(if_stmt, ast.IfStmt)
    assert if_stmt.else_branch is not None


def test_variables_block_all_types():
    f = parse(
        "variables { int a; long b; float c; double d; char e; byte[] f; "
        "char[8] g; msTimer h; }"
    )
    decls = {d.name: d for d in f.variables.declarations}
    assert decls["a"].type_name == "int" and not decls["a"].is_array
    assert decls["f"].type_name == "byte" and decls["f"].is_array
    assert decls["g"].type_name == "char" and decls["g"].is_array and decls["g"].array_size == 8
    assert decls["h"].type_name == "msTimer"


def test_all_six_event_handler_forms():
    f = parse(
        """
        on start { write(1); }
        on stop { write(1); }
        on timer t1 { write(1); }
        on message 0x100 { write(1); }
        on request 0x7DF service 0x01 { output(1); }
        on request 0x7DF service 0x01 pid 0x0C { output(1); }
        on request 0x7DF service 0x01 data 0x02 xx { output(1); }
        on request 0x7DF service 0x01 pid 0x0C data 0x02 xx { output(1); }
        """
    )
    assert f.on_start is not None
    assert f.on_stop is not None
    assert f.on_timers[0].timer_name == "t1"
    assert f.on_messages[0].can_id == 0x100
    assert len(f.on_requests) == 4


def test_on_request_specificity_ranking():
    f = parse(
        """
        on request 0x7DF service 0x01 { output(1); }
        on request 0x7DF service 0x01 pid 0x0C { output(1); }
        on request 0x7DF service 0x01 data 0x02 xx { output(1); }
        on request 0x7DF service 0x01 pid 0x0C data 0x02 xx { output(1); }
        """
    )
    assert [r.specificity for r in f.on_requests] == [0, 1, 2, 3]


def test_data_clause_wildcard_and_concrete():
    f = parse("on request 0x7DF service 0x01 data 0x02 0x10 xx XX { output(1); }")
    bytes_ = f.on_requests[0].data.bytes
    assert [b.is_wildcard for b in bytes_] == [False, False, True, True]
    assert bytes_[0].value == 0x02


@pytest.mark.parametrize(
    "stmt",
    [
        "if (1) write(1);",
        "if (1) write(1); else write(2);",
        "while (1) write(1);",
        "for (i = 0; i < 10; i = i + 1) write(i);",
        "for (;;) write(1);",
        "switch (x) { case 1: write(1); case 2: write(2); default: write(0); }",
        "x = 1;",
        "{ write(1); write(2); }",
    ],
)
def test_every_statement_form_parses(stmt):
    parse(f"on start {{ {stmt} }}")


def test_dangling_else_binds_to_nearest_if():
    f = parse("on start { if (1) if (2) write(1); else write(2); }")
    outer_if = f.on_start.body.statements[0]
    assert isinstance(outer_if, ast.IfStmt)
    assert outer_if.else_branch is None  # else thuộc về if bên trong
    inner_if = outer_if.then_branch
    assert isinstance(inner_if, ast.IfStmt)
    assert inner_if.else_branch is not None


@pytest.mark.parametrize(
    "expr, expected_op",
    [
        ("1 + 2", "+"), ("1 - 2", "-"), ("1 * 2", "*"), ("1 / 2", "/"), ("1 % 2", "%"),
        ("1 << 2", "<<"), ("1 >> 2", ">>"),
        ("1 & 2", "&"), ("1 | 2", "|"), ("1 ^ 2", "^"),
        ("1 == 2", "=="), ("1 != 2", "!="),
        ("1 < 2", "<"), ("1 > 2", ">"), ("1 <= 2", "<="), ("1 >= 2", ">="),
        ("1 && 2", "&&"), ("1 || 2", "||"),
    ],
)
def test_every_binary_operator(expr, expected_op):
    f = parse(f"on start {{ x = {expr}; }}")
    assign = f.on_start.body.statements[0].expr
    assert isinstance(assign, ast.Assign)
    assert isinstance(assign.value, ast.Binary)
    assert assign.value.op == expected_op


@pytest.mark.parametrize("op", ["=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="])
def test_every_assignment_operator(op):
    f = parse(f"on start {{ x {op} 1; }}")
    assign = f.on_start.body.statements[0].expr
    assert assign.op == op


@pytest.mark.parametrize("op", ["!", "-", "~"])
def test_every_unary_operator(op):
    f = parse(f"on start {{ x = {op}1; }}")
    value = f.on_start.body.statements[0].expr.value
    assert isinstance(value, ast.Unary)
    assert value.op == op


def test_operator_precedence_mul_before_add():
    f = parse("on start { x = 1 + 2 * 3; }")
    value = f.on_start.body.statements[0].expr.value
    assert isinstance(value, ast.Binary) and value.op == "+"
    assert isinstance(value.right, ast.Binary) and value.right.op == "*"


def test_shift_does_not_get_confused_with_relational():
    """Bug đã sửa trong lúc build: '>>' từng bị lexer tách nhầm thành 2
    token '>' '>' (REL_OP) do xung đột priority với SHIFT_OP."""
    f = parse("on start { x = (rpm * 4) >> 8; }")
    value = f.on_start.body.statements[0].expr.value
    assert isinstance(value, ast.Binary)
    assert value.op == ">>"


def test_hex_decimal_float_string_literals():
    f = parse('on start { write(0x7E0, 42, 3.14, "hello"); }')
    call = f.on_start.body.statements[0].expr
    assert isinstance(call, ast.Call)
    a, b, c, d = call.args
    assert (a.value, a.literal_type) == (0x7E0, "hex")
    assert (b.value, b.literal_type) == (42, "int")
    assert (c.value, c.literal_type) == (3.14, "float")
    assert (d.value, d.literal_type) == ("hello", "string")


def test_line_comment_and_block_comment_ignored():
    f = parse(
        "on start { // dòng chú thích\n"
        "/* khối\n   nhiều dòng */ write(1); }"
    )
    assert len(f.on_start.body.statements) == 1


def test_call_with_no_args_and_nested_calls():
    f = parse("on start { x = elapsed() + sin(1); }")
    value = f.on_start.body.statements[0].expr.value
    assert isinstance(value, ast.Binary)
    assert value.left.name == "elapsed" and value.left.args == []
    assert value.right.name == "sin"


def test_line_column_present_on_every_node():
    f = parse("on start { x = 1; }")
    assign = f.on_start.body.statements[0].expr
    assert assign.line == 1
    assert assign.column > 0


def test_syntax_error_reports_line_number():
    src = "on start {\n    write(1\n}\n"
    with pytest.raises(SimlangSyntaxError) as exc_info:
        parse(src)
    assert exc_info.value.line == 3


def test_syntax_error_on_missing_semicolon():
    with pytest.raises(SimlangSyntaxError):
        parse("on start { x = 1 }")


def test_ecu_scoped_names_not_supported_yet_is_plain_identifier():
    """§5.6: không có testcase/on key/on envVar/.dbc — chỉ kiểm tra rằng
    tên định danh thường (không có `::`) vẫn parse bình thường."""
    f = parse("on start { x = rpm; }")
    assert f.on_start.body.statements[0].expr.value.name == "rpm"
