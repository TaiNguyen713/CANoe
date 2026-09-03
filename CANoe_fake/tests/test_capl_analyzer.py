"""Kiểm thử analyzer: lỗi ngữ nghĩa, include, và cây outline."""

from __future__ import annotations

from canoe_fake.capl import compile_source
from canoe_fake.capl.diagnostics import Severity


def codes(result) -> set[str]:
    return {d.code for d in result.diagnostics}


def test_clean_file_has_no_errors():
    result = compile_source("""
    variables { msTimer t; long n; }
    on start { setTimer(t, 100); }
    on timer t { n++; write("n=%d", n); setTimer(t, 100); }
    """)
    assert not result.diagnostics.has_errors()


def test_unknown_function_suggests_builtin():
    result = compile_source('on start { wrtie("x"); }')
    errors = [d for d in result.diagnostics.errors if d.code == "C3011"]
    assert errors and "write" in errors[0].message


def test_wrong_argument_count_for_user_function():
    result = compile_source("void f(int a) { }\non start { f(1, 2); }")
    errors = [d for d in result.diagnostics.errors if d.code == "C3010"]
    assert errors and "1 argument" in errors[0].message


def test_timer_handler_requires_declared_timer():
    result = compile_source("on timer missing { }")
    assert "C3005" in codes(result)


def test_settimer_on_non_timer_variable():
    result = compile_source("variables { int x; }\non start { setTimer(x, 10); }")
    assert "C3012" in codes(result)


def test_this_outside_handler_is_error():
    result = compile_source("void f() { x = this.id; }")
    assert "C3008" in codes(result)


def test_invalid_this_member_warns():
    result = compile_source("on message * { x = this.nonsense; }")
    warnings = [d for d in result.diagnostics.warnings if d.code == "C3009"]
    assert warnings


def test_valid_this_members_accepted():
    result = compile_source(
        "on message * { a = this.id + this.dlc + this.byte(0) + this.dir; }")
    assert not [d for d in result.diagnostics if d.code == "C3009"]


def test_duplicate_definitions():
    result = compile_source("variables { int a; int a; }\nvoid f(){}\nvoid f(){}")
    assert "C3001" in codes(result)
    assert "C3002" in codes(result)


def test_non_void_function_without_return_warns():
    result = compile_source("long f() { long x; x = 1; }")
    assert "C3004" in codes(result)


def test_builtin_constants_are_known():
    result = compile_source("on message * { if (this.dir == TX) x = TRUE; }")
    infos = [d for d in result.diagnostics if d.code == "C3100"]
    assert not [d for d in infos if "'TX'" in d.message or "'TRUE'" in d.message]


def test_symbols_outline_structure():
    result = compile_source("""
    variables { int a; msTimer t; }
    on start { }
    void helper() { }
    testcase TC_X() { }
    """)
    kinds = [s.kind for s in result.symbols]
    assert "block" in kinds and "handler" in kinds
    assert "function" in kinds and "testcase" in kinds
    variables_block = next(s for s in result.symbols if s.kind == "block")
    assert {c.name for c in variables_block.children} == {"a", "t"}


# ---------------------------------------------------------------------------
# include
# ---------------------------------------------------------------------------

def test_include_makes_functions_known(tmp_path):
    (tmp_path / "Lib.cin").write_text(
        "double Clamp(double v, double lo, double hi) { return v; }\n"
        "variables { const long kMax = 9; }\n", encoding="utf-8")
    node = tmp_path / "Node.can"
    source = ('includes { #include "Lib.cin" }\n'
              'on start { x = Clamp(1.0, 0.0, 2.0) + kMax; }\n')
    node.write_text(source, encoding="utf-8")

    result = compile_source(source, str(node))
    assert not [d for d in result.diagnostics.errors if d.code == "C3011"]
    assert "Clamp" in result.included.functions


def test_missing_include_warns(tmp_path):
    node = tmp_path / "Node.can"
    source = 'includes { #include "KhongTonTai.cin" }\n'
    node.write_text(source, encoding="utf-8")
    result = compile_source(source, str(node))
    assert "C3014" in codes(result)


def test_nested_include_is_resolved(tmp_path):
    (tmp_path / "Inner.cin").write_text("long Inner() { return 1; }", encoding="utf-8")
    (tmp_path / "Outer.cin").write_text(
        'includes { #include "Inner.cin" }\nlong Outer() { return Inner(); }',
        encoding="utf-8")
    node = tmp_path / "Node.can"
    source = 'includes { #include "Outer.cin" }\non start { x = Inner() + Outer(); }'
    node.write_text(source, encoding="utf-8")

    result = compile_source(source, str(node))
    assert not [d for d in result.diagnostics.errors if d.code == "C3011"]


def test_include_cycle_does_not_hang(tmp_path):
    (tmp_path / "A.cin").write_text('includes { #include "B.cin" }', encoding="utf-8")
    (tmp_path / "B.cin").write_text('includes { #include "A.cin" }', encoding="utf-8")
    node = tmp_path / "Node.can"
    source = 'includes { #include "A.cin" }'
    node.write_text(source, encoding="utf-8")

    result = compile_source(source, str(node))
    assert result.included is not None


def test_diagnostics_bag_is_capped():
    # 400 câu lệnh hỏng nhưng không được sinh quá max_errors chẩn đoán
    result = compile_source("on start {" + "x = ( ;" * 400 + "}")
    assert len(result.diagnostics) <= 200


def test_severity_ordering_for_ui():
    result = compile_source("on strat { wrtie(1); }")
    ordered = result.diagnostics.sorted()
    assert ordered == sorted(ordered, key=lambda d: (d.line, d.column, -int(d.severity)))
    assert any(d.severity is Severity.ERROR for d in ordered)
