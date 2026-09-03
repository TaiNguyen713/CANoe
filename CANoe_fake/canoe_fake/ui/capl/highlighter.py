"""Tô màu cú pháp CAPL, dùng chính lexer của trình biên dịch.

Nhờ dùng lexer thay vì regex rời rạc, màu sắc luôn khớp với cách parser hiểu mã
nguồn: chuỗi có dấu `//` bên trong không bị coi là comment, số hex hiển thị
đúng, và `on <event>` được nhận diện theo ngữ cảnh.
"""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import (QColor, QFont, QSyntaxHighlighter, QTextCharFormat,
                           QTextDocument)

from ...capl import builtins as capl_builtins
from ...capl import keywords as kw
from ...capl.lexer import Lexer, TokenKind
from ..theme import PALETTE

#: trạng thái block: đang ở giữa một comment /* ... */
_STATE_NORMAL = 0
_STATE_BLOCK_COMMENT = 1


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.DemiBold)
    if italic:
        f.setFontItalic(True)
    return f


class CaplHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        p = PALETTE
        self.f_keyword = _fmt(p.syn_keyword, bold=True)
        self.f_type = _fmt(p.syn_type, bold=True)
        self.f_event = _fmt(p.syn_event, bold=True)
        self.f_builtin = _fmt(p.syn_builtin)
        self.f_constant = _fmt(p.syn_constant)
        self.f_string = _fmt(p.syn_string)
        self.f_char = _fmt(p.syn_char)
        self.f_number = _fmt(p.syn_number)
        self.f_comment = _fmt(p.syn_comment, italic=True)
        self.f_preproc = _fmt(p.syn_preproc, bold=True)
        self.f_operator = _fmt(p.syn_operator)
        self.f_sysvar = _fmt(p.syn_sysvar, bold=True)
        self.f_function = _fmt(p.text, bold=True)
        self.f_todo = _fmt(p.warning, bold=True)

        self._todo_re = QRegularExpression(r"\b(TODO|FIXME|HACK|XXX|NOTE)\b")

    # ------------------------------------------------------------------
    def highlightBlock(self, text: str) -> None:
        offset = 0
        state = self.previousBlockState()
        if state == -1:
            state = _STATE_NORMAL

        # phần đuôi của comment khối bắt đầu từ dòng trước
        if state == _STATE_BLOCK_COMMENT:
            end = text.find("*/")
            if end == -1:
                self.setFormat(0, len(text), self.f_comment)
                self._mark_todo(text, 0, len(text))
                self.setCurrentBlockState(_STATE_BLOCK_COMMENT)
                return
            length = end + 2
            self.setFormat(0, length, self.f_comment)
            self._mark_todo(text, 0, length)
            offset = length

        self.setCurrentBlockState(_STATE_NORMAL)
        segment = text[offset:]
        if not segment:
            return

        lexer = Lexer(segment)
        tokens = lexer.tokenize(include_trivia=True)
        prev_meaningful = None

        for i, tok in enumerate(tokens):
            if tok.kind is TokenKind.EOF:
                break
            start = offset + tok.offset
            length = len(tok.value)
            if length == 0:
                continue

            # comment khối chưa đóng ⇒ dòng sau vẫn ở trong comment
            if tok.kind is TokenKind.COMMENT:
                self.setFormat(start, length, self.f_comment)
                self._mark_todo(text, start, length)
                if tok.value.startswith("/*") and not tok.value.rstrip().endswith("*/"):
                    self.setCurrentBlockState(_STATE_BLOCK_COMMENT)
                continue

            if tok.kind is TokenKind.WHITESPACE:
                continue

            fmt = self._format_for(tok, prev_meaningful, tokens, i)
            if fmt is not None:
                self.setFormat(start, length, fmt)
            prev_meaningful = tok

    # ------------------------------------------------------------------
    def _format_for(self, tok, prev, tokens, index):
        kind = tok.kind

        if kind is TokenKind.PREPROCESSOR:
            return self.f_preproc
        if kind is TokenKind.STRING:
            return self.f_string
        if kind is TokenKind.CHAR:
            return self.f_char
        if kind is TokenKind.NUMBER:
            return self.f_number
        if kind is TokenKind.OPERATOR:
            if tok.value in ("@", "$"):
                return self.f_sysvar
            return self.f_operator
        if kind is TokenKind.TYPE:
            return self.f_type
        if kind is TokenKind.KEYWORD:
            return self.f_keyword

        if kind is TokenKind.IDENTIFIER:
            # tên loại sự kiện ngay sau `on`
            if prev is not None and prev.kind is TokenKind.KEYWORD and prev.value == "on":
                return self.f_event if kw.is_event_type(tok.value) else self.f_type
            if tok.value in kw.CONSTANTS:
                return self.f_constant
            if capl_builtins.is_builtin(tok.value):
                return self.f_builtin
            # định danh đứng ngay trước '(' ⇒ lời gọi hàm của người dùng
            nxt = _next_meaningful(tokens, index)
            if nxt is not None and nxt.is_op("("):
                return self.f_function
        return None

    def _mark_todo(self, text: str, start: int, length: int) -> None:
        it = self._todo_re.globalMatch(text, start)
        limit = start + length
        while it.hasNext():
            m = it.next()
            if m.capturedStart() >= limit:
                break
            self.setFormat(m.capturedStart(), m.capturedLength(), self.f_todo)


def _next_meaningful(tokens, index):
    for tok in tokens[index + 1:]:
        if tok.kind in (TokenKind.WHITESPACE, TokenKind.COMMENT):
            continue
        return tok
    return None
