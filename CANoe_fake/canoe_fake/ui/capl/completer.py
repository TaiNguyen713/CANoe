"""Code completion (autocomplete) for CAPL.

The suggestion list is drawn from 5 sources:
  1. keywords + data types
  2. event types (after `on `)
  3. built-in functions (with signature + doc)
  4. snippets
  5. symbols declared by the user in the open file

There is also context-aware completion: typing `this.` inside `on message`
only shows the valid properties of a CAN frame.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QCompleter, QListView, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem)

from ...capl import builtins as capl_builtins
from ...capl import keywords as kw
from ...capl import snippets as capl_snippets
from ..icons import icon
from ..theme import PALETTE, ui_font

ROLE_DETAIL = Qt.ItemDataRole.UserRole + 1
ROLE_DOC = Qt.ItemDataRole.UserRole + 2
ROLE_INSERT = Qt.ItemDataRole.UserRole + 3
ROLE_KIND = Qt.ItemDataRole.UserRole + 4


@dataclass(frozen=True)
class Completion:
    label: str
    kind: str                # keyword | type | event | function | snippet | symbol | member
    detail: str = ""
    doc: str = ""
    insert: str = ""         # actual text to insert (default = label)

    @property
    def text_to_insert(self) -> str:
        return self.insert or self.label


_KIND_ICON = {
    "keyword": "sym_block",
    "type": "sym_struct",
    "event": "sym_handler",
    "function": "sym_function",
    "builtin": "sym_function",
    "snippet": "capl",
    "symbol": "sym_variable",
    "member": "sym_constant",
    "constant": "sym_constant",
}


class CompletionDelegate(QStyledItemDelegate):
    """Paints each suggestion row as: [icon] name ............ detail."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(20, size.height() + 3))

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        painter.save()

        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        painter.fillRect(opt.rect,
                         QColor(PALETTE.selection) if selected else QColor(PALETTE.surface))

        rect = opt.rect.adjusted(4, 0, -6, 0)
        pixmap = opt.icon.pixmap(14, 14)
        if not pixmap.isNull():
            painter.drawPixmap(rect.left(), rect.center().y() - 7, pixmap)
        rect.setLeft(rect.left() + 20)

        label = index.data(Qt.ItemDataRole.DisplayRole) or ""
        detail = index.data(ROLE_DETAIL) or ""

        font = QFont(opt.font)
        painter.setFont(font)
        painter.setPen(QColor(PALETTE.text))
        metrics = painter.fontMetrics()
        label_width = metrics.horizontalAdvance(label)
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, label)

        if detail:
            detail_rect = rect.adjusted(label_width + 12, 0, 0, 0)
            if detail_rect.width() > 30:
                small = QFont(opt.font)
                small.setPointSizeF(max(7.0, opt.font.pointSizeF() - 0.5))
                painter.setFont(small)
                painter.setPen(QColor(PALETTE.text_muted))
                elided = painter.fontMetrics().elidedText(
                    detail, Qt.TextElideMode.ElideRight, detail_rect.width())
                painter.drawText(detail_rect,
                                 Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                                 elided)
        painter.restore()


class CaplCompleter(QCompleter):
    def __init__(self, parent=None) -> None:
        self._model = QStandardItemModel(parent)
        super().__init__(self._model, parent)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setFilterMode(Qt.MatchFlag.MatchContains)
        self.setWrapAround(False)
        self.setMaxVisibleItems(14)

        view = QListView()
        view.setItemDelegate(CompletionDelegate(view))
        view.setUniformItemSizes(True)
        view.setFont(ui_font(9))
        view.setStyleSheet(
            f"QListView {{ background: {PALETTE.surface};"
            f" border: 1px solid {PALETTE.border}; outline: none; }}"
        )
        self.setPopup(view)

        self._base_items: list[Completion] = []
        self._symbol_items: list[Completion] = []
        self._build_base()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_base(self) -> None:
        items: list[Completion] = []

        for word in sorted(kw.BLOCK_KEYWORDS | kw.CONTROL_KEYWORDS | kw.DECL_KEYWORDS):
            items.append(Completion(word, "keyword", "keyword"))
        for word in sorted(kw.DATA_TYPES):
            items.append(Completion(word, "type", "data type"))
        for word in sorted(kw.CONSTANTS):
            items.append(Completion(word, "constant", "built-in constant"))
        for name, doc in sorted(kw.EVENT_TYPES.items()):
            items.append(Completion(name, "event", "event", doc))
        for name in capl_builtins.all_names():
            fn = capl_builtins.FUNCTIONS[name]
            items.append(Completion(name, "builtin", fn.detail, fn.doc,
                                    insert=f"{name}("))
        for snippet in capl_snippets.SNIPPETS:
            items.append(Completion(snippet.trigger, "snippet",
                                    f"snippet · {snippet.title}",
                                    snippet.description or snippet.title))
        self._base_items = items

    def set_symbols(self, symbols, included=None) -> None:
        """Update symbols taken from the open file and any included .cin files."""
        items: list[Completion] = []
        seen: set[str] = set()

        if included is not None:
            for name, fn in sorted(included.functions.items()):
                seen.add(name)
                items.append(Completion(name, "function",
                                        f"{fn.signature}  ·  from included file",
                                        "", f"{name}("))
            for name, decl in sorted(included.globals.items()):
                if name in seen:
                    continue
                seen.add(name)
                items.append(Completion(name, "symbol",
                                        f"{decl.type_name}  ·  from included file"))

        def add(symbol) -> None:
            if symbol.kind in ("block", "include") or symbol.name in seen:
                for child in symbol.children:
                    add(child)
                return
            seen.add(symbol.name)
            kind = "function" if symbol.kind in ("function", "testcase") else "symbol"
            insert = f"{symbol.name}(" if kind == "function" else symbol.name
            items.append(Completion(symbol.name, kind,
                                    symbol.detail or symbol.kind, "", insert))
            for child in symbol.children:
                add(child)

        for s in symbols:
            add(s)
        self._symbol_items = items
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self, extra: list[Completion] | None = None) -> None:
        self._populate(self._symbol_items + self._base_items + list(extra or []))

    def show_members(self, members: dict[str, str]) -> None:
        """Switch to member-completion mode (after a dot)."""
        items = [
            Completion(name.replace("(x)", ""), "member", detail, "",
                       insert=name.replace("(x)", "(") if "(x)" in name else name)
            for name, detail in sorted(members.items())
        ]
        self._populate(items)

    def _populate(self, items: list[Completion]) -> None:
        self._model.clear()
        for comp in items:
            item = QStandardItem(comp.label)
            item.setEditable(False)
            item.setIcon(icon(_KIND_ICON.get(comp.kind, "sym_block"), 14))
            item.setData(comp.detail, ROLE_DETAIL)
            item.setData(comp.doc, ROLE_DOC)
            item.setData(comp.text_to_insert, ROLE_INSERT)
            item.setData(comp.kind, ROLE_KIND)
            if comp.doc:
                item.setToolTip(f"{comp.detail}\n\n{comp.doc}" if comp.detail else comp.doc)
            self._model.appendRow(item)

    # ------------------------------------------------------------------
    def current_insert_text(self) -> str:
        index = self.popup().currentIndex()
        if not index.isValid():
            return self.currentCompletion()
        return index.data(ROLE_INSERT) or index.data(Qt.ItemDataRole.DisplayRole) or ""

    def current_kind(self) -> str:
        index = self.popup().currentIndex()
        return index.data(ROLE_KIND) or "" if index.isValid() else ""
