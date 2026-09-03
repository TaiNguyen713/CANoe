"""Bộ tách token (lexer) cho CAPL.

Lexer giữ lại cả trivia (khoảng trắng + comment) để bộ tô màu dùng chung một
đường phân tích với parser; parser tự lọc trivia qua `Lexer.tokenize(...)`
với `include_trivia=False`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from . import keywords as kw
from .diagnostics import DiagnosticBag


class TokenKind(enum.Enum):
    IDENTIFIER = "identifier"
    KEYWORD = "keyword"
    TYPE = "type"
    NUMBER = "number"
    STRING = "string"
    CHAR = "char"
    OPERATOR = "operator"
    PREPROCESSOR = "preprocessor"
    COMMENT = "comment"
    WHITESPACE = "whitespace"
    UNKNOWN = "unknown"
    EOF = "eof"


TRIVIA_KINDS: frozenset[TokenKind] = frozenset(
    {TokenKind.WHITESPACE, TokenKind.COMMENT}
)


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    value: str
    offset: int
    line: int
    column: int

    @property
    def length(self) -> int:
        return len(self.value)

    @property
    def end(self) -> int:
        return self.offset + len(self.value)

    def is_op(self, *ops: str) -> bool:
        return self.kind is TokenKind.OPERATOR and self.value in ops

    def is_kw(self, *words: str) -> bool:
        return self.kind in (TokenKind.KEYWORD, TokenKind.TYPE) and self.value in words

    def __repr__(self) -> str:  # pragma: no cover - chỉ dùng khi debug
        return f"Token({self.kind.value}, {self.value!r}, {self.line}:{self.column})"


_IDENT_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_BODY = _IDENT_START | set("0123456789")
_DIGITS = set("0123456789")
_HEX_DIGITS = set("0123456789abcdefABCDEF")


class Lexer:
    """Tách mã nguồn CAPL thành danh sách token.

    Lexer không bao giờ ném exception: ký tự lạ trở thành token UNKNOWN kèm một
    diagnostic, để editor vẫn tô màu được file đang gõ dở.
    """

    def __init__(self, source: str, diagnostics: DiagnosticBag | None = None) -> None:
        self.src = source
        self.n = len(source)
        self.pos = 0
        self.line = 1
        self.col = 1
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticBag()

    # -- helper ------------------------------------------------------------
    def _peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.src[i] if i < self.n else ""

    def _advance(self, count: int = 1) -> str:
        start = self.pos
        for _ in range(count):
            if self.pos >= self.n:
                break
            if self.src[self.pos] == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.pos += 1
        return self.src[start:self.pos]

    def _make(self, kind: TokenKind, start_pos: int, start_line: int,
              start_col: int) -> Token:
        return Token(kind, self.src[start_pos:self.pos], start_pos, start_line, start_col)

    # -- API ---------------------------------------------------------------
    def tokenize(self, include_trivia: bool = False) -> list[Token]:
        tokens: list[Token] = []
        while True:
            tok = self._next_token()
            if tok.kind is TokenKind.EOF:
                tokens.append(tok)
                break
            if include_trivia or tok.kind not in TRIVIA_KINDS:
                tokens.append(tok)
        return tokens

    # -- lõi ----------------------------------------------------------------
    def _next_token(self) -> Token:
        if self.pos >= self.n:
            return Token(TokenKind.EOF, "", self.pos, self.line, self.col)

        start_pos, start_line, start_col = self.pos, self.line, self.col
        ch = self.src[self.pos]

        # khoảng trắng ------------------------------------------------------
        if ch in " \t\r\n\f\v":
            while self._peek() in " \t\r\n\f\v" and self._peek() != "":
                self._advance()
            return self._make(TokenKind.WHITESPACE, start_pos, start_line, start_col)

        # comment ------------------------------------------------------------
        if ch == "/" and self._peek(1) == "/":
            while self._peek() not in ("", "\n"):
                self._advance()
            return self._make(TokenKind.COMMENT, start_pos, start_line, start_col)

        if ch == "/" and self._peek(1) == "*":
            self._advance(2)
            closed = False
            while self.pos < self.n:
                if self._peek() == "*" and self._peek(1) == "/":
                    self._advance(2)
                    closed = True
                    break
                self._advance()
            if not closed:
                self.diagnostics.error(
                    "C0001", "Block comment /* ... */ was never closed.",
                    start_line, start_col, self.pos - start_pos, start_pos,
                )
            return self._make(TokenKind.COMMENT, start_pos, start_line, start_col)

        # tiền xử lý (#include, #pragma, #if, ...) ----------------------------
        if ch == "#":
            self._advance()
            while self._peek() in _IDENT_BODY and self._peek() != "":
                self._advance()
            # Phần còn lại của dòng thuộc về directive. Dừng sớm khi gặp comment
            # hoặc dấu '}' ngoài chuỗi — nhờ vậy dạng viết gọn một dòng
            # `includes { #include "lib.cin" }` vẫn phân tích đúng.
            in_string = False
            quote = ""
            while self._peek() not in ("", "\n"):
                c = self._peek()
                if in_string:
                    if c == "\\":
                        self._advance(2)
                        continue
                    if c == quote:
                        in_string = False
                elif c in ('"', "'", "<"):
                    in_string = True
                    quote = ">" if c == "<" else c
                elif c == "}":
                    break
                elif c == "/" and self._peek(1) in ("/", "*"):
                    break
                self._advance()
            return self._make(TokenKind.PREPROCESSOR, start_pos, start_line, start_col)

        # chuỗi ----------------------------------------------------------------
        if ch == '"':
            self._advance()
            closed = False
            while self.pos < self.n:
                c = self._peek()
                if c == "\\":
                    self._advance(2)
                    continue
                if c == "\n":
                    break
                self._advance()
                if c == '"':
                    closed = True
                    break
            if not closed:
                self.diagnostics.error(
                    "C0002", "String literal was never closed with a \".",
                    start_line, start_col, self.pos - start_pos, start_pos,
                )
            return self._make(TokenKind.STRING, start_pos, start_line, start_col)

        # ký tự -----------------------------------------------------------------
        if ch == "'":
            self._advance()
            closed = False
            while self.pos < self.n:
                c = self._peek()
                if c == "\\":
                    self._advance(2)
                    continue
                if c == "\n":
                    break
                self._advance()
                if c == "'":
                    closed = True
                    break
            if not closed:
                self.diagnostics.error(
                    "C0003", "Character literal was never closed with a '.",
                    start_line, start_col, self.pos - start_pos, start_pos,
                )
            return self._make(TokenKind.CHAR, start_pos, start_line, start_col)

        # số ---------------------------------------------------------------------
        if ch in _DIGITS or (ch == "." and self._peek(1) in _DIGITS):
            return self._lex_number(start_pos, start_line, start_col)

        # định danh / từ khoá -------------------------------------------------------
        if ch in _IDENT_START:
            while self._peek() in _IDENT_BODY and self._peek() != "":
                self._advance()
            word = self.src[start_pos:self.pos]
            if word in kw.DATA_TYPES:
                kind = TokenKind.TYPE
            elif kw.is_keyword(word):
                kind = TokenKind.KEYWORD
            else:
                kind = TokenKind.IDENTIFIER
            return Token(kind, word, start_pos, start_line, start_col)

        # toán tử --------------------------------------------------------------------
        for op in kw.OPERATORS:
            if self.src.startswith(op, self.pos):
                self._advance(len(op))
                return Token(TokenKind.OPERATOR, op, start_pos, start_line, start_col)

        # ký tự không hợp lệ ----------------------------------------------------------
        self._advance()
        self.diagnostics.error(
            "C0004", f"Invalid character in CAPL source: {ch!r}.",
            start_line, start_col, 1, start_pos,
        )
        return self._make(TokenKind.UNKNOWN, start_pos, start_line, start_col)

    def _lex_number(self, start_pos: int, start_line: int, start_col: int) -> Token:
        # hex: 0x1A / 0X1A
        if self._peek() == "0" and self._peek(1) in ("x", "X"):
            self._advance(2)
            if self._peek() not in _HEX_DIGITS:
                self.diagnostics.error(
                    "C0005", "Hex number is missing digits after 0x.",
                    start_line, start_col, self.pos - start_pos, start_pos,
                )
            while self._peek() in _HEX_DIGITS and self._peek() != "":
                self._advance()
        # binary: 0b1010 (CAPL hỗ trợ trong các phiên bản mới)
        elif self._peek() == "0" and self._peek(1) in ("b", "B") and self._peek(2) in ("0", "1"):
            self._advance(2)
            while self._peek() in ("0", "1"):
                self._advance()
        else:
            seen_dot = False
            seen_exp = False
            while True:
                c = self._peek()
                if c in _DIGITS:
                    self._advance()
                elif c == "." and not seen_dot and not seen_exp:
                    seen_dot = True
                    self._advance()
                elif c in ("e", "E") and not seen_exp and self._peek(1) != "":
                    nxt = self._peek(1)
                    if nxt in _DIGITS or (nxt in "+-" and self._peek(2) in _DIGITS):
                        seen_exp = True
                        self._advance(2 if nxt in "+-" else 1)
                    else:
                        break
                else:
                    break
        # hậu tố kiểu: U, L, UL, LL, F
        while self._peek() in ("u", "U", "l", "L", "f", "F"):
            self._advance()
        return self._make(TokenKind.NUMBER, start_pos, start_line, start_col)


def tokenize(source: str, include_trivia: bool = False,
             diagnostics: DiagnosticBag | None = None) -> list[Token]:
    """Hàm tiện dụng: tách token từ chuỗi mã nguồn."""
    return Lexer(source, diagnostics).tokenize(include_trivia=include_trivia)
