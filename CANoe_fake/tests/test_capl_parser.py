"""Kiểm thử parser CAPL: cấu trúc AST và khả năng phục hồi lỗi."""

from __future__ import annotations

from canoe_fake.capl import ast_nodes as ast
from canoe_fake.capl import parse


def test_parses_all_top_level_blocks():
    unit, diags = parse("""
    includes { #include "lib.cin" }
    variables { int a = 1; }
    on start { a = 2; }
    void f(int x) { }
    testcase TC_A() { }
    """)
    assert not diags.has_errors()
    assert unit.includes is not None and len(unit.includes.directives) == 1
    assert [d.name for d in unit.global_variables()] == ["a"]
    assert [h.event_type for h in unit.handlers] == ["start"]
    assert [f.name for f in unit.functions] == ["f"]
    assert [t.name for t in unit.testcases] == ["TC_A"]


def test_bus_object_selector_is_separated_from_name():
    unit, diags = parse("""
    variables {
      message 0x100 tx;
      message EngineData rx;
      message CAN1.Door door;
      diagRequest Body.Reset req;
      msTimer t;
    }
    """)
    assert not diags.has_errors()
    decls = {d.name: d for d in unit.global_variables()}
    assert decls["tx"].bus_selector == "0x100"
    assert decls["rx"].bus_selector == "EngineData"
    assert decls["door"].bus_selector == "CAN1.Door"
    assert decls["req"].bus_selector == "Body.Reset"
    assert decls["t"].bus_selector == ""
    assert decls["t"].type_name == "msTimer"


def test_array_and_initializer_list():
    unit, _ = parse("variables { byte d[4] = {1, 2, 3, 4}; int m[2][3]; }")
    decls = {d.name: d for d in unit.global_variables()}
    assert decls["d"].is_array and len(decls["d"].initializer) == 4
    assert len(decls["m"].array_dims) == 2


def test_struct_and_enum_inside_variables_are_kept():
    unit, diags = parse("""
    variables {
      struct P { int x; int y; };
      enum State { kOff = 0, kOn = 1 };
      struct P origin;
    }
    """)
    assert not diags.has_errors()
    assert [s.name for s in unit.structs] == ["P"]
    assert [e.name for e in unit.enums] == ["State"]
    assert [m.name for m in unit.enums[0].members] == ["kOff", "kOn"]


def test_operator_precedence():
    unit, _ = parse("on start { x = 1 + 2 * 3; }")
    assign = unit.handlers[0].body.statements[0].expr
    assert isinstance(assign, ast.Assign)
    top = assign.value
    assert isinstance(top, ast.Binary) and top.op == "+"
    assert isinstance(top.right, ast.Binary) and top.right.op == "*"


def test_control_flow_statements():
    unit, diags = parse("""
    on start {
      int i;
      for (i = 0; i < 8; i++) { if (i > 4) break; else continue; }
      while (i) i--;
      do { i++; } while (i < 3);
      switch (i) { case 1: break; default: break; }
    }
    """)
    assert not diags.has_errors()
    body = unit.handlers[0].body.statements
    types = [type(s).__name__ for s in body]
    assert types == ["VarDecl", "ForStmt", "WhileStmt", "DoWhileStmt", "SwitchStmt"]


def test_this_member_and_payload_access():
    unit, diags = parse("on message * { x = this.byte(0) + this.dlc; this.byte(1) = 5; }")
    assert not diags.has_errors()
    stmts = unit.handlers[0].body.statements
    assert isinstance(stmts[1].expr, ast.Assign)


def test_sysvar_and_signal_access():
    unit, diags = parse("on start { @sysvar::Engine::RPM = $EngineSpeed; }")
    assert not diags.has_errors()
    assign = unit.handlers[0].body.statements[0].expr
    assert isinstance(assign.target, ast.SysVarAccess)
    assert assign.target.path.text == "sysvar::Engine::RPM"
    assert isinstance(assign.value, ast.SignalAccess)


def test_cast_and_ternary():
    unit, diags = parse("on start { b = (byte)(x > 3 ? 1 : 0); }")
    assert not diags.has_errors()
    value = unit.handlers[0].body.statements[0].expr.value
    assert isinstance(value, ast.Cast) and value.type_name == "byte"


def test_missing_semicolon_reports_error_with_position():
    _unit, diags = parse("variables {\n  int a\n  int b;\n}")
    errors = diags.errors
    assert errors and errors[0].code == "C1010"
    assert errors[0].line == 2


def test_recovers_after_error_and_keeps_parsing():
    unit, diags = parse("""
    on start { x = ( ; }
    void good() { }
    on stopMeasurement { }
    """)
    assert diags.has_errors()
    assert [f.name for f in unit.functions] == ["good"]
    assert "stopMeasurement" in [h.event_type for h in unit.handlers]


def test_unknown_event_type_warns_with_suggestion():
    _unit, diags = parse("on strat { }")
    warnings = [d for d in diags.warnings if d.code == "C2001"]
    assert warnings and "start" in warnings[0].message


def test_handler_without_body_is_error():
    _unit, diags = parse("on timer t;")
    assert any(d.code == "C1007" for d in diags.errors)


def test_export_variables_and_function():
    unit, diags = parse("export variables { int shared; }\nexport void api() { }")
    assert not diags.has_errors()
    assert unit.variables[0].is_export
    assert unit.functions[0].is_export


def test_parser_never_hangs_on_garbage():
    # chuỗi rác không được làm parser lặp vô hạn
    unit, diags = parse("}}} ??? @@@ ;;; {{{ ")
    assert isinstance(unit, ast.CaplFile)
    assert diags.has_errors()
