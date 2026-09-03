"""Editor CAPL: số dòng, tô màu, gợi ý mã, gạch chân lỗi, auto-indent.

Đây là phần tương đương cửa sổ soạn thảo trong CAPL Browser của CANoe.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFontMetrics, QPainter, QTextCharFormat,
                           QTextCursor, QTextFormat, QKeyEvent)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QToolTip, QWidget

from ...capl import builtins as capl_builtins
from ...capl import compile_source, snippets as capl_snippets
from ...capl.diagnostics import Diagnostic, Severity
from ...capl.keywords import this_members_for
from ..theme import PALETTE, mono_font
from .completer import CaplCompleter
from .highlighter import CaplHighlighter

INDENT = "  "          # CAPL quy ước thụt 2 khoảng trắng
_AUTO_PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CaplEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)


class CaplEditor(QPlainTextEdit):
    """Soạn thảo CAPL với phân tích cú pháp trực tiếp khi gõ."""

    diagnostics_changed = Signal(list)     # list[Diagnostic]
    symbols_changed = Signal(list)         # list[Symbol]
    cursor_position_changed = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFont(mono_font(10))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(QFontMetrics(self.font()).horizontalAdvance(" ") * 2)
        self.setCursorWidth(2)
        self.setMouseTracking(True)
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {PALETTE.surface}; color: {PALETTE.text};"
            f" border: 1px solid {PALETTE.border}; selection-background-color:"
            f" {PALETTE.selection}; selection-color: {PALETTE.text}; }}"
        )

        self._line_area = _LineNumberArea(self)
        self._highlighter = CaplHighlighter(self.document())
        self._diagnostics: list[Diagnostic] = []
        self._symbols: list = []
        #: đường dẫn file đang mở — quyết định nơi tìm các file .cin được include
        self.file_path: Path | None = None

        self._completer = CaplCompleter(self)
        self._completer.setWidget(self)
        self._completer.activated.connect(self._insert_completion)
        self._member_mode = False

        self._analyze_timer = QTimer(self)
        self._analyze_timer.setSingleShot(True)
        self._analyze_timer.setInterval(320)
        self._analyze_timer.timeout.connect(self.analyze)

        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self.textChanged.connect(self._analyze_timer.start)

        self._update_line_area_width(0)
        self._refresh_extra_selections()

    # ==================================================================
    # Vùng số dòng
    # ==================================================================
    def line_number_area_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_area_width(self, _count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width(0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(PALETTE.line_number_bg))
        painter.setPen(QColor(PALETTE.border_light))
        painter.drawLine(event.rect().right(), event.rect().top(),
                         event.rect().right(), event.rect().bottom())

        error_lines = {d.line for d in self._diagnostics if d.severity is Severity.ERROR}
        warn_lines = {d.line for d in self._diagnostics if d.severity is Severity.WARNING}
        current_line = self.textCursor().blockNumber() + 1

        block = self.firstVisibleBlock()
        number = block.blockNumber() + 1
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        height = self.fontMetrics().height()
        width = self._line_area.width() - 8

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if number in error_lines:
                    painter.setPen(QColor(PALETTE.error))
                    painter.drawText(2, int(top), 8, height,
                                     Qt.AlignmentFlag.AlignCenter, "●")
                elif number in warn_lines:
                    painter.setPen(QColor(PALETTE.warning))
                    painter.drawText(2, int(top), 8, height,
                                     Qt.AlignmentFlag.AlignCenter, "●")
                painter.setPen(QColor(PALETTE.line_number_active if number == current_line
                                      else PALETTE.line_number_fg))
                painter.drawText(0, int(top), width, height,
                                 Qt.AlignmentFlag.AlignRight, str(number))
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            number += 1

    # ==================================================================
    # Phân tích + đánh dấu
    # ==================================================================
    def analyze(self) -> None:
        path = str(self.file_path) if self.file_path else ""
        result = compile_source(self.toPlainText(), path)
        self._diagnostics = result.diagnostics.sorted()
        self._symbols = result.symbols
        self._completer.set_symbols(result.symbols, result.included)
        self._refresh_extra_selections()
        self._line_area.update()
        self.diagnostics_changed.emit(self._diagnostics)
        self.symbols_changed.emit(self._symbols)

    @property
    def diagnostics(self) -> list[Diagnostic]:
        return self._diagnostics

    @property
    def symbols(self) -> list:
        return self._symbols

    def _refresh_extra_selections(self) -> None:
        selections: list[QTextEdit.ExtraSelection] = []

        # dòng hiện tại
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor(PALETTE.current_line))
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            selections.append(sel)

        selections.extend(self._bracket_selections())
        selections.extend(self._diagnostic_selections())
        self.setExtraSelections(selections)

    def _diagnostic_selections(self) -> list[QTextEdit.ExtraSelection]:
        colors = {
            Severity.ERROR: PALETTE.error_underline,
            Severity.WARNING: PALETTE.warning_underline,
            Severity.INFO: PALETTE.info_underline,
            Severity.HINT: PALETTE.info_underline,
        }
        out: list[QTextEdit.ExtraSelection] = []
        doc = self.document()
        for diag in self._diagnostics:
            block = doc.findBlockByNumber(diag.line - 1)
            if not block.isValid():
                continue
            start = block.position() + max(0, diag.column - 1)
            length = max(1, min(diag.length, max(1, block.length() - diag.column)))
            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)

            fmt = QTextCharFormat()
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            fmt.setUnderlineColor(QColor(colors[diag.severity]))
            fmt.setToolTip(f"{diag.code}: {diag.message}")

            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = fmt
            out.append(sel)
        return out

    def _bracket_selections(self) -> list[QTextEdit.ExtraSelection]:
        cursor = self.textCursor()
        text = self.toPlainText()
        pos = cursor.position()
        pairs = {"(": ")", "[": "]", "{": "}"}
        closers = {v: k for k, v in pairs.items()}

        target = None
        if pos < len(text) and text[pos] in pairs:
            target = (pos, self._match_forward(text, pos, text[pos], pairs[text[pos]]))
        elif pos > 0 and text[pos - 1] in closers:
            target = (pos - 1,
                      self._match_backward(text, pos - 1, closers[text[pos - 1]],
                                           text[pos - 1]))
        if target is None or target[1] < 0:
            return []

        out = []
        for index in target:
            c = QTextCursor(self.document())
            c.setPosition(index)
            c.setPosition(index + 1, QTextCursor.MoveMode.KeepAnchor)
            sel = QTextEdit.ExtraSelection()
            sel.cursor = c
            sel.format.setBackground(QColor(PALETTE.bracket_match))
            out.append(sel)
        return out

    @staticmethod
    def _match_forward(text: str, start: int, opener: str, closer: str) -> int:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    return i
        return -1

    @staticmethod
    def _match_backward(text: str, start: int, opener: str, closer: str) -> int:
        depth = 0
        for i in range(start, -1, -1):
            if text[i] == closer:
                depth += 1
            elif text[i] == opener:
                depth -= 1
                if depth == 0:
                    return i
        return -1

    def _on_cursor_moved(self) -> None:
        self._refresh_extra_selections()
        cursor = self.textCursor()
        self.cursor_position_changed.emit(cursor.blockNumber() + 1,
                                          cursor.positionInBlock() + 1)
        self._line_area.update()

    # ==================================================================
    # Điều hướng
    # ==================================================================
    def goto_line(self, line: int, column: int = 1) -> None:
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.Right,
                            QTextCursor.MoveMode.MoveAnchor, max(0, column - 1))
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()

    def insert_snippet(self, snippet: capl_snippets.Snippet) -> None:
        text, offset = capl_snippets.expand(snippet.body)
        cursor = self.textCursor()
        indent = self._current_indent()
        if indent:
            text = text.replace("\n", "\n" + indent)
        cursor.insertText(text)
        cursor.setPosition(cursor.position() - (len(text) - offset))
        self.setTextCursor(cursor)
        self.analyze()

    def toggle_comment(self) -> None:
        cursor = self.textCursor()
        doc = self.document()
        start_block = doc.findBlock(cursor.selectionStart()).blockNumber()
        end_block = doc.findBlock(cursor.selectionEnd()).blockNumber()

        lines = [doc.findBlockByNumber(i) for i in range(start_block, end_block + 1)]
        all_commented = all(b.text().lstrip().startswith("//")
                            for b in lines if b.text().strip())

        cursor.beginEditBlock()
        for block in lines:
            text = block.text()
            if not text.strip():
                continue
            c = QTextCursor(block)
            if all_commented:
                index = text.index("//")
                c.setPosition(block.position() + index)
                c.setPosition(block.position() + index + (3 if text[index:index + 3] == "// "
                                                          else 2),
                              QTextCursor.MoveMode.KeepAnchor)
                c.removeSelectedText()
            else:
                indent_len = len(text) - len(text.lstrip())
                c.setPosition(block.position() + indent_len)
                c.insertText("// ")
        cursor.endEditBlock()

    def _current_indent(self) -> str:
        text = self.textCursor().block().text()
        return text[:len(text) - len(text.lstrip())]

    # ==================================================================
    # Gõ phím
    # ==================================================================
    def keyPressEvent(self, event: QKeyEvent) -> None:
        popup = self._completer.popup()
        if popup.isVisible():
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab,
                               Qt.Key.Key_Escape, Qt.Key.Key_Backtab):
                event.ignore()
                return

        ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if ctrl and event.key() == Qt.Key.Key_Space:
            self._show_completion(force=True)
            return
        if ctrl and event.key() == Qt.Key.Key_Slash:
            self.toggle_comment()
            return

        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self._handle_newline()
            return
        if event.key() == Qt.Key.Key_Tab and not self.textCursor().hasSelection():
            self.textCursor().insertText(INDENT)
            return
        if event.key() == Qt.Key.Key_Backtab or (
                event.key() == Qt.Key.Key_Tab and self.textCursor().hasSelection()):
            self._change_indent(event.key() == Qt.Key.Key_Tab)
            return
        if event.key() == Qt.Key.Key_Backspace and self._unindent_backspace():
            return

        text = event.text()
        if text in _AUTO_PAIRS and not self.textCursor().hasSelection():
            self._insert_pair(text)
            return
        if text in (")", "]", "}") and self._skip_closing(text):
            return

        super().keyPressEvent(event)

        if text and (text.isalnum() or text in "_.:"):
            self._show_completion(force=False)
        elif popup.isVisible():
            popup.hide()

    def _handle_newline(self) -> None:
        cursor = self.textCursor()
        block_text = cursor.block().text()
        indent = block_text[:len(block_text) - len(block_text.lstrip())]
        before = block_text[:cursor.positionInBlock()].rstrip()
        after = block_text[cursor.positionInBlock():].lstrip()

        cursor.beginEditBlock()
        if before.endswith("{"):
            if after.startswith("}"):
                cursor.insertText("\n" + indent + INDENT + "\n" + indent)
                cursor.movePosition(QTextCursor.MoveOperation.Up)
                cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
            else:
                cursor.insertText("\n" + indent + INDENT)
        else:
            cursor.insertText("\n" + indent)
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def _change_indent(self, add: bool) -> None:
        cursor = self.textCursor()
        doc = self.document()
        start = doc.findBlock(cursor.selectionStart()).blockNumber()
        end = doc.findBlock(cursor.selectionEnd()).blockNumber()
        cursor.beginEditBlock()
        for i in range(start, end + 1):
            block = doc.findBlockByNumber(i)
            c = QTextCursor(block)
            if add:
                c.insertText(INDENT)
            else:
                text = block.text()
                strip = min(len(INDENT), len(text) - len(text.lstrip(" ")))
                if strip:
                    c.setPosition(block.position())
                    c.setPosition(block.position() + strip,
                                  QTextCursor.MoveMode.KeepAnchor)
                    c.removeSelectedText()
        cursor.endEditBlock()

    def _unindent_backspace(self) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False
        col = cursor.positionInBlock()
        if col < len(INDENT):
            return False
        text = cursor.block().text()[:col]
        if text.strip() or col % len(INDENT) != 0:
            return False
        cursor.setPosition(cursor.position() - len(INDENT),
                           QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        return True

    def _insert_pair(self, opener: str) -> None:
        closer = _AUTO_PAIRS[opener]
        cursor = self.textCursor()
        next_char = self._char_at(cursor.position())
        # không tự đóng nháy khi đang ở giữa một từ
        if opener in ("'", '"') and next_char.isalnum():
            cursor.insertText(opener)
            return
        cursor.insertText(opener + closer)
        cursor.setPosition(cursor.position() - 1)
        self.setTextCursor(cursor)

    def _skip_closing(self, closer: str) -> bool:
        cursor = self.textCursor()
        if self._char_at(cursor.position()) != closer:
            return False
        cursor.setPosition(cursor.position() + 1)
        self.setTextCursor(cursor)
        return True

    def _char_at(self, position: int) -> str:
        text = self.toPlainText()
        return text[position] if 0 <= position < len(text) else ""

    # ==================================================================
    # Gợi ý mã
    # ==================================================================
    def _text_before_cursor(self) -> str:
        cursor = self.textCursor()
        return cursor.block().text()[:cursor.positionInBlock()]

    def _current_prefix(self) -> str:
        match = _WORD_RE.search(self._text_before_cursor())
        return match.group(0) if match else ""

    def _enclosing_event(self) -> str:
        """Tìm `on <event>` gần nhất phía trên con trỏ để gợi ý `this.` đúng."""
        cursor = self.textCursor()
        block = cursor.block()
        while block.isValid():
            match = re.match(r"\s*on\s+(\w+)", block.text())
            if match:
                return match.group(1)
            block = block.previous()
        return ""

    def _show_completion(self, force: bool) -> None:
        before = self._text_before_cursor()
        popup = self._completer.popup()

        # gợi ý thành viên sau `this.`
        member_match = re.search(r"(\bthis|\w+)\.(\w*)$", before)
        if member_match and member_match.group(1) == "this":
            members = this_members_for(self._enclosing_event())
            if members:
                self._member_mode = True
                self._completer.show_members(members)
                self._popup(member_match.group(2))
                return

        if self._member_mode:
            self._member_mode = False
            self._completer.refresh()

        prefix = self._current_prefix()
        if not force and len(prefix) < 2:
            popup.hide()
            return
        if not prefix and not force:
            popup.hide()
            return
        self._popup(prefix)

    def _popup(self, prefix: str) -> None:
        completer = self._completer
        completer.setCompletionPrefix(prefix)
        if completer.completionCount() == 0:
            completer.popup().hide()
            return
        completer.popup().setCurrentIndex(completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(completer.popup().sizeHintForColumn(0)
                      + completer.popup().verticalScrollBar().sizeHint().width() + 90)
        rect.translate(self.line_number_area_width(), 4)
        completer.complete(rect)

    def _insert_completion(self, _text: str) -> None:
        insert = self._completer.current_insert_text()
        kind = self._completer.current_kind()

        if kind == "snippet":
            snippet = capl_snippets.find(insert)
            if snippet is not None:
                self._replace_prefix("")
                self.insert_snippet(snippet)
                return

        self._replace_prefix(insert)
        if insert.endswith("("):
            cursor = self.textCursor()
            cursor.insertText(")")
            cursor.setPosition(cursor.position() - 1)
            self.setTextCursor(cursor)

    def _replace_prefix(self, text: str) -> None:
        cursor = self.textCursor()
        prefix = self._current_prefix()
        if prefix:
            cursor.setPosition(cursor.position() - len(prefix),
                               QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.setTextCursor(cursor)

    # ==================================================================
    # Tooltip
    # ==================================================================
    def event(self, event) -> bool:
        if event.type() == event.Type.ToolTip:
            self._show_tooltip(event)
            return True
        return super().event(event)

    def _show_tooltip(self, event) -> None:
        cursor = self.cursorForPosition(event.pos())
        line = cursor.blockNumber() + 1
        column = cursor.positionInBlock() + 1

        for diag in self._diagnostics:
            if diag.line == line and diag.column <= column < diag.column + max(1, diag.length):
                QToolTip.showText(event.globalPos(),
                                  f"<b>{diag.severity.label} {diag.code}</b><br>{diag.message}",
                                  self)
                return

        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText()
        fn = capl_builtins.lookup(word) if word else None
        if fn is not None:
            QToolTip.showText(
                event.globalPos(),
                f"<b>{fn.returns} {fn.signature}</b><br>"
                f"<i>{fn.category}</i><br>{fn.doc}", self)
            return
        QToolTip.hideText()
