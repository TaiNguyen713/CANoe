"""Kiểm thử lexer CAPL."""

from __future__ import annotations

from canoe_fake.capl.diagnostics import DiagnosticBag
from canoe_fake.capl.lexer import TokenKind, tokenize


def kinds(source: str) -> list[TokenKind]:
    return [t.kind for t in tokenize(source) if t.kind is not TokenKind.EOF]


def values(source: str) -> list[str]:
    return [t.value for t in tokenize(source) if t.kind is not TokenKind.EOF]


def test_keyword_type_identifier_split():
    assert kinds("byte x") == [TokenKind.TYPE, TokenKind.IDENTIFIER]
    assert kinds("if (x)") == [TokenKind.KEYWORD, TokenKind.OPERATOR,
                               TokenKind.IDENTIFIER, TokenKind.OPERATOR]


def test_numbers():
    assert values("0x1F 0b1010 42 3.14 1e3 1.5e-2 100UL") == [
        "0x1F", "0b1010", "42", "3.14", "1e3", "1.5e-2", "100UL"]
    assert all(k is TokenKind.NUMBER for k in kinds("0x1F 0b1010 42 3.14"))


def test_comment_not_confused_by_string():
    toks = tokenize('write("a // b"); // thật sự là comment', include_trivia=True)
    strings = [t for t in toks if t.kind is TokenKind.STRING]
    comments = [t for t in toks if t.kind is TokenKind.COMMENT]
    assert strings[0].value == '"a // b"'
    assert len(comments) == 1


def test_block_comment_and_preprocessor():
    toks = tokenize('/* nhiều\ndòng */ #include "x.cin"', include_trivia=True)
    assert any(t.kind is TokenKind.COMMENT and "nhiều" in t.value for t in toks)
    assert any(t.kind is TokenKind.PREPROCESSOR for t in toks)


def test_maximal_munch_operators():
    assert values("a >>= b; c <= d; e++") == [
        "a", ">>=", "b", ";", "c", "<=", "d", ";", "e", "++"]


def test_sysvar_and_signal_prefix():
    assert values("@sysvar::NS::V = $Sig") == [
        "@", "sysvar", "::", "NS", "::", "V", "=", "$", "Sig"]


def test_unterminated_string_reports_error():
    bag = DiagnosticBag()
    tokenize('write("chưa đóng', diagnostics=bag)
    assert any(d.code == "C0002" for d in bag)


def test_unterminated_block_comment_reports_error():
    bag = DiagnosticBag()
    tokenize("/* mở mà không đóng", diagnostics=bag)
    assert any(d.code == "C0001" for d in bag)


def test_line_and_column_are_one_based():
    toks = tokenize("byte a;\nint b;")
    second_line = [t for t in toks if t.line == 2]
    assert second_line[0].value == "int"
    assert second_line[0].column == 1
