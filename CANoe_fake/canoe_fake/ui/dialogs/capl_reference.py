"""Dialog for looking up the entire CAPL syntax.

Combines everything the language layer knows: keywords, data types, event
types, `this` properties, built-in constants, built-in functions (grouped),
and snippets.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QSplitter, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ...capl import builtins as capl_builtins
from ...capl import keywords as kw
from ...capl import snippets as capl_snippets
from ..icons import icon
from ..theme import PALETTE, mono_font, ui_font


class CaplReferenceDialog(QDialog):
    """A reference window — can stay open side-by-side while coding."""

    insert_requested = Signal(str)      # text to insert into the editor

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CAPL — Full Syntax Reference")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(1000, 660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "type a function name, keyword, or a word from its description "
            "(e.g. timer, diag, string)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self.search, 1)
        self.count_label = QLabel()
        self.count_label.setStyleSheet(f"color: {PALETTE.text_muted};")
        search_row.addWidget(self.count_label)
        layout.addLayout(search_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Return Type / Group"])
        self.tree.setFont(ui_font(9))
        self.tree.setColumnWidth(0, 260)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.currentItemChanged.connect(self._on_selection)
        splitter.addWidget(self.tree)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        self.detail.setFont(ui_font(9))
        self.detail.setStyleSheet(
            f"QTextBrowser {{ background: {PALETTE.surface};"
            f" border: 1px solid {PALETTE.border}; padding: 8px; }}")
        right_layout.addWidget(self.detail, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.insert_button = QPushButton("Insert into Editor")
        self.insert_button.setIcon(icon("capl", 14))
        self.insert_button.clicked.connect(self._emit_insert)
        self.insert_button.setEnabled(False)
        button_row.addWidget(self.insert_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)
        right_layout.addLayout(button_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([420, 560])
        layout.addWidget(splitter, 1)

        self._build_tree()

    # ==================================================================
    def _build_tree(self) -> None:
        self.tree.clear()

        # -- Top-level blocks -------------------------------------------
        blocks = self._group("Top-Level Blocks", "sym_block")
        for word in sorted(kw.BLOCK_KEYWORDS):
            self._leaf(blocks, word, "block", "keyword",
                       f"Keyword that opens a top-level block: `{word} {{ ... }}`.",
                       insert=f"{word}\n{{\n  \n}}\n")

        # -- Control flow ---------------------------------------------
        control = self._group("Control Flow", "sym_block")
        for word in sorted(kw.CONTROL_KEYWORDS):
            self._leaf(control, word, "keyword", "keyword",
                       "Control-flow keyword, C-like syntax.")

        # -- Declaration keywords ----------------------------------------
        decl = self._group("Declaration Keywords", "sym_block")
        for word in sorted(kw.DECL_KEYWORDS):
            self._leaf(decl, word, "keyword", "keyword", "")

        # -- Data types ---------------------------------------------------
        scalars = self._group("Scalar Types", "sym_struct")
        for word in sorted(kw.SCALAR_TYPES):
            self._leaf(scalars, word, "type", "type", _SCALAR_DOC.get(word, ""))

        objects = self._group("Bus Object Types", "sym_struct")
        for word in sorted(kw.OBJECT_TYPES):
            self._leaf(objects, word, "type", "type", _OBJECT_DOC.get(word, ""))

        # -- Events ----------------------------------------------------------
        events = self._group("Event Handlers (on ...)", "sym_handler")
        for name, doc in sorted(kw.EVENT_TYPES.items()):
            self._leaf(events, f"on {name}", "event", "event", doc,
                       insert=f"on {name}\n{{\n  \n}}\n")

        # -- this properties ----------------------------------------------------
        this_group = self._group("Properties of `this`", "sym_constant")
        for context, members in kw.THIS_MEMBERS.items():
            if not members:
                continue
            sub = QTreeWidgetItem([f"inside on {context}", f"{len(members)} propert{'y' if len(members) == 1 else 'ies'}"])
            sub.setForeground(1, QColor(PALETTE.text_muted))
            this_group.addChild(sub)
            for member, doc in sorted(members.items()):
                self._leaf(sub, f"this.{member}", "property", "member", doc)

        # -- Constants ----------------------------------------------------------------
        constants = self._group("Built-in Constants", "sym_constant")
        for word in sorted(kw.CONSTANTS):
            self._leaf(constants, word, "constant", "constant", "")

        # -- Built-in functions by category ---------------------------------------------------
        for category in capl_builtins.CATEGORIES:
            group = self._group(f"Functions — {category}", "sym_function")
            for name in capl_builtins.names_by_category(category):
                fn = capl_builtins.FUNCTIONS[name]
                self._leaf(group, fn.name, fn.returns, "function", fn.doc,
                           signature=fn.signature, insert=f"{fn.name}()")

        # -- Snippets -------------------------------------------------------------------
        snippet_group = self._group("Snippets", "capl")
        for snippet in capl_snippets.SNIPPETS:
            body, _ = capl_snippets.expand(snippet.body)
            self._leaf(snippet_group, snippet.title, snippet.category, "snippet",
                       snippet.description, code=body, insert=body)

        self._update_count()

    def _group(self, title: str, icon_name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([title, ""])
        item.setIcon(0, icon(icon_name, 14))
        item.setFont(0, ui_font(9, bold=True))
        item.setData(0, Qt.ItemDataRole.UserRole, None)
        self.tree.addTopLevelItem(item)
        return item

    def _leaf(self, parent: QTreeWidgetItem, name: str, detail: str, kind: str,
              doc: str, signature: str = "", code: str = "",
              insert: str = "") -> QTreeWidgetItem:
        item = QTreeWidgetItem([name, detail])
        item.setFont(0, mono_font(9))
        item.setForeground(1, QColor(PALETTE.text_muted))
        item.setData(0, Qt.ItemDataRole.UserRole,
                     {"name": name, "kind": kind, "doc": doc,
                      "signature": signature, "code": code,
                      "insert": insert or name, "detail": detail})
        parent.addChild(item)
        return item

    # ==================================================================
    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        visible = 0
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            visible += self._filter_item(group, needle)
        self._update_count(visible if needle else None)

    def _filter_item(self, item: QTreeWidgetItem, needle: str) -> int:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        matched_children = 0
        for i in range(item.childCount()):
            matched_children += self._filter_item(item.child(i), needle)

        if not needle:
            item.setHidden(False)
            item.setExpanded(False)
            return 1 if payload else 0

        haystack = " ".join([
            item.text(0), item.text(1),
            (payload or {}).get("doc", ""), (payload or {}).get("signature", ""),
        ]).lower()
        self_match = needle in haystack and payload is not None
        show = self_match or matched_children > 0
        item.setHidden(not show)
        item.setExpanded(matched_children > 0)
        return matched_children + (1 if self_match else 0)

    def _update_count(self, filtered: int | None = None) -> None:
        total = sum(self._count_leaves(self.tree.topLevelItem(i))
                    for i in range(self.tree.topLevelItemCount()))
        if filtered is None:
            self.count_label.setText(f"{total} entries")
        else:
            self.count_label.setText(f"{filtered} / {total} entries")

    def _count_leaves(self, item: QTreeWidgetItem) -> int:
        if item.childCount() == 0:
            return 1 if item.data(0, Qt.ItemDataRole.UserRole) else 0
        return sum(self._count_leaves(item.child(i)) for i in range(item.childCount()))

    # ==================================================================
    def _on_selection(self, current: QTreeWidgetItem, _previous) -> None:
        payload = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if not payload:
            self.detail.setHtml(
                f"<p style='color:{PALETTE.text_muted}'>"
                "Select an entry on the left to see its details.</p>")
            self.insert_button.setEnabled(False)
            return

        self.insert_button.setEnabled(True)
        name = payload["name"]
        signature = payload.get("signature") or name
        doc = payload.get("doc") or "<i>No description available.</i>"
        code = payload.get("code")

        html = [
            f"<h2 style='margin:0;color:{PALETTE.accent}'>{name}</h2>",
            f"<p style='color:{PALETTE.text_muted};margin:2px 0 12px 0'>"
            f"{payload.get('detail', '')}</p>",
        ]
        if payload["kind"] == "function":
            html.append(
                f"<pre style='background:{PALETTE.surface_alt};border:1px solid "
                f"{PALETTE.border_light};padding:8px'>{signature}</pre>")
        html.append(f"<p>{doc}</p>")
        if code:
            escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html.append(
                f"<pre style='background:{PALETTE.surface_alt};border:1px solid "
                f"{PALETTE.border_light};padding:8px'>{escaped}</pre>")
        self.detail.setHtml("".join(html))

    def _emit_insert(self) -> None:
        current = self.tree.currentItem()
        payload = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if payload:
            self.insert_requested.emit(payload["insert"])


_SCALAR_DOC = {
    "byte": "Unsigned 8-bit integer (0..255).",
    "word": "Unsigned 16-bit integer (0..65535).",
    "dword": "Unsigned 32-bit integer.",
    "int": "Signed 16-bit integer (-32768..32767).",
    "long": "Signed 32-bit integer.",
    "int64": "Signed 64-bit integer.",
    "qword": "Unsigned 64-bit integer.",
    "char": "Character / element of a string array.",
    "float": "32-bit floating-point number.",
    "double": "64-bit floating-point number — CAPL's default real type.",
    "void": "No return value.",
}

_OBJECT_DOC = {
    "message": "A CAN frame object: `message 0x100 msg;` or `message EngineData msg;`.",
    "multiplexed_message": "A CAN frame with a multiplexor (mode signal).",
    "msTimer": "A timer with millisecond resolution, used with setTimer/cancelTimer.",
    "timer": "A timer with second resolution.",
    "diagRequest": "A diagnostic request: `diagRequest ECU.Service req;`.",
    "diagResponse": "The diagnostic response matching a diagRequest.",
    "linFrame": "A LIN frame.",
    "frFrame": "A FlexRay frame.",
    "frPDU": "A FlexRay PDU.",
    "ethernetPacket": "An Ethernet packet.",
    "pdu": "A bus-independent PDU.",
    "signal": "A reference to a signal in the database.",
    "sysvar": "A reference to a system variable; access its value with `@sysvar::NS::Var`.",
    "envVar": "An environment variable (legacy mechanism, predecessor of system variables).",
}
