"""CAPL Browser — the CAPL editing window of CANoe.

Layout: file tree + outline on the left, a multi-tab editor in the middle,
and a compiler problems list at the bottom — matching the real CAPL Browser.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHeaderView,
                               QInputDialog, QLabel, QMenu, QMessageBox,
                               QSplitter, QTabWidget, QToolBar, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ...capl import snippets as capl_snippets
from ...capl.diagnostics import Diagnostic, Severity
from ..icons import icon
from ..theme import PALETTE, mono_font, ui_font
from .editor import CaplEditor

_SYMBOL_ICON = {
    "function": "sym_function",
    "testcase": "sym_testcase",
    "handler": "sym_handler",
    "variable": "sym_variable",
    "struct": "sym_struct",
    "enum": "sym_enum",
    "constant": "sym_constant",
    "include": "sym_include",
    "block": "sym_block",
}


class _EditorTab(QWidget):
    """One tab: an editor plus its attached file path."""

    def __init__(self, path: Path | None, text: str, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self.editor = CaplEditor(self)
        self.editor.file_path = path
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.editor)

    @property
    def title(self) -> str:
        base = self.path.name if self.path else "Untitled.can"
        return base + (" *" if self.editor.document().isModified() else "")


class CaplBrowser(QWidget):
    """The complete CAPL Browser widget."""

    status_message = Signal(str)
    compile_finished = Signal(str, int, int)   # file name, error count, warning count

    def __init__(self, workspace: Path, parent=None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self.workspace.mkdir(parents=True, exist_ok=True)

        self._build_ui()
        self.refresh_file_tree()

    # ==================================================================
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())

        outer = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(self._build_left_panel())

        right = QSplitter(Qt.Orientation.Vertical)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        right.addWidget(self.tabs)
        right.addWidget(self._build_problems())
        right.setStretchFactor(0, 4)
        right.setStretchFactor(1, 1)
        right.setSizes([460, 150])

        outer.addWidget(right)
        outer.setStretchFactor(0, 1)
        outer.setStretchFactor(1, 4)
        outer.setSizes([260, 900])
        layout.addWidget(outer, 1)

    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar()
        bar.setIconSize(bar.iconSize() * 0.9)

        bar.addAction(icon("new"), "New CAPL File", self.new_file)
        bar.addAction(icon("open"), "Open .can/.cin File", self.open_file_dialog)
        bar.addAction(icon("save"), "Save (Ctrl+S)", self.save_current)
        bar.addSeparator()

        self.act_compile = QAction(icon("compile"), "Compile (F7)", self)
        self.act_compile.triggered.connect(self.compile_current)
        bar.addAction(self.act_compile)
        bar.addSeparator()

        insert_button = QToolButton()
        insert_button.setText("Insert Template ▾")
        insert_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        insert_button.setIcon(icon("capl"))
        insert_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        insert_button.setMenu(self._build_snippet_menu())
        bar.addWidget(insert_button)

        bar.addSeparator()
        bar.addAction(icon("search"), "Go to Line (Ctrl+G)", self.goto_line_dialog)
        return bar

    def _build_snippet_menu(self) -> QMenu:
        menu = QMenu(self)
        for category, items in capl_snippets.by_category().items():
            sub = menu.addMenu(category)
            for snippet in items:
                action = sub.addAction(snippet.title)
                action.setToolTip(snippet.description)
                action.triggered.connect(
                    lambda _checked=False, s=snippet: self._insert_snippet(s))
        return menu

    def _build_left_panel(self) -> QWidget:
        panel = QSplitter(Qt.Orientation.Vertical)

        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["Node / CAPL File"])
        self.file_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.file_tree.setFont(ui_font(9))
        self.file_tree.itemDoubleClicked.connect(self._on_file_activated)
        self.file_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_tree.customContextMenuRequested.connect(self._file_context_menu)
        panel.addWidget(self.file_tree)

        self.outline = QTreeWidget()
        self.outline.setHeaderLabels(["Structure", "Detail"])
        self.outline.setFont(ui_font(9))
        self.outline.setColumnWidth(0, 170)
        self.outline.itemClicked.connect(self._on_outline_clicked)
        panel.addWidget(self.outline)

        panel.setStretchFactor(0, 1)
        panel.setStretchFactor(1, 2)
        return panel

    def _build_problems(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.problems_header = QLabel("  Build Results — no errors yet")
        self.problems_header.setFont(ui_font(9, bold=True))
        self.problems_header.setStyleSheet(
            f"background: {PALETTE.panel_header}; color: {PALETTE.text_muted};"
            f" border-top: 1px solid {PALETTE.border};"
            f" border-bottom: 1px solid {PALETTE.border_light}; padding: 4px;"
        )
        layout.addWidget(self.problems_header)

        self.problems = QTreeWidget()
        self.problems.setHeaderLabels(["", "Code", "Description", "Line", "Column"])
        self.problems.setRootIsDecorated(False)
        self.problems.setAlternatingRowColors(True)
        self.problems.setFont(ui_font(9))
        self.problems.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.problems.setColumnWidth(0, 26)
        self.problems.setColumnWidth(1, 60)
        self.problems.setColumnWidth(3, 55)
        self.problems.setColumnWidth(4, 45)
        self.problems.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.problems.itemDoubleClicked.connect(self._on_problem_activated)
        layout.addWidget(self.problems)
        return container

    # ==================================================================
    # File tree
    # ==================================================================
    def refresh_file_tree(self) -> None:
        self.file_tree.clear()
        root = QTreeWidgetItem([self.workspace.name or "CAPL"])
        root.setIcon(0, icon("open", 14))
        root.setData(0, Qt.ItemDataRole.UserRole, None)
        self.file_tree.addTopLevelItem(root)

        files = sorted(list(self.workspace.glob("*.can")) + list(self.workspace.glob("*.cin")))
        for path in files:
            item = QTreeWidgetItem([path.name])
            item.setIcon(0, icon("capl", 14))
            item.setData(0, Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(0, str(path))
            root.addChild(item)
        root.setExpanded(True)
        if not files:
            hint = QTreeWidgetItem(["(no files yet — use the 'New CAPL File' button)"])
            hint.setForeground(0, QColor(PALETTE.text_disabled))
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            root.addChild(hint)

    def _file_context_menu(self, pos) -> None:
        item = self.file_tree.itemAt(pos)
        if item is None:
            return
        path_text = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        if path_text:
            menu.addAction("Open", lambda: self.open_path(Path(path_text)))
            menu.addAction("Rename...", lambda: self._rename(Path(path_text)))
            menu.addSeparator()
            menu.addAction("Delete File", lambda: self._delete(Path(path_text)))
        else:
            menu.addAction("New CAPL File", self.new_file)
            menu.addAction("Refresh", self.refresh_file_tree)
        menu.exec(self.file_tree.viewport().mapToGlobal(pos))

    def _rename(self, path: Path) -> None:
        new_name, ok = QInputDialog.getText(self, "Rename File", "New name:",
                                            text=path.name)
        if not ok or not new_name.strip():
            return
        target = path.with_name(new_name.strip())
        try:
            path.rename(target)
        except OSError as exc:
            QMessageBox.warning(self, "Rename Failed", str(exc))
            return
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if tab.path == path:
                tab.path = target
                tab.editor.file_path = target
                self.tabs.setTabText(i, tab.title)
        self.refresh_file_tree()

    def _delete(self, path: Path) -> None:
        answer = QMessageBox.question(
            self, "Delete File",
            f"Delete '{path.name}' from disk?\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, "Delete Failed", str(exc))
            return
        for i in reversed(range(self.tabs.count())):
            if self.tabs.widget(i).path == path:
                self.tabs.removeTab(i)
        self.refresh_file_tree()
        self.status_message.emit(f"Deleted {path.name}")

    def _on_file_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        path_text = item.data(0, Qt.ItemDataRole.UserRole)
        if path_text:
            self.open_path(Path(path_text))

    # ==================================================================
    # Tab / file
    # ==================================================================
    @property
    def current_tab(self) -> _EditorTab | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, _EditorTab) else None

    @property
    def current_editor(self) -> CaplEditor | None:
        tab = self.current_tab
        return tab.editor if tab else None

    def new_file(self) -> None:
        snippet = capl_snippets.find("caplfile")
        text, _ = capl_snippets.expand(snippet.body) if snippet else ("", 0)
        self._add_tab(None, text)
        self.status_message.emit("Created a new CAPL file from the standard boilerplate.")

    def open_file_dialog(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(
            self, "Open CAPL File", str(self.workspace),
            "CAPL (*.can *.cin);;All Files (*.*)")
        if path_text:
            self.open_path(Path(path_text))

    def open_path(self, path: Path) -> None:
        for i in range(self.tabs.count()):
            if self.tabs.widget(i).path == path:
                self.tabs.setCurrentIndex(i)
                return
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, "Failed to Open File", f"{path}\n\n{exc}")
            return
        self._add_tab(path, text)
        self.status_message.emit(f"Opened {path.name}")

    def _add_tab(self, path: Path | None, text: str) -> _EditorTab:
        tab = _EditorTab(path, text)
        if path is None:
            # unsaved file: still root it at the workspace so #include can find .cin
            tab.editor.file_path = self.workspace / "Untitled.can"
        index = self.tabs.addTab(tab, icon("capl", 14), tab.title)
        self.tabs.setCurrentIndex(index)
        tab.editor.document().modificationChanged.connect(
            lambda _m, t=tab: self._update_tab_title(t))
        tab.editor.diagnostics_changed.connect(self._on_diagnostics)
        tab.editor.symbols_changed.connect(self._on_symbols)
        tab.editor.analyze()
        return tab

    def _update_tab_title(self, tab: _EditorTab) -> None:
        index = self.tabs.indexOf(tab)
        if index >= 0:
            self.tabs.setTabText(index, tab.title)

    def close_tab(self, index: int) -> None:
        tab = self.tabs.widget(index)
        if isinstance(tab, _EditorTab) and tab.editor.document().isModified():
            answer = QMessageBox.question(
                self, "Unsaved Changes",
                f"'{tab.title.rstrip(' *')}' has unsaved changes. Save it?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save and not self._save_tab(tab):
                return
        self.tabs.removeTab(index)
        if self.tabs.count() == 0:
            self.outline.clear()
            self.problems.clear()
            self._set_problems_header(0, 0, 0)

    def save_current(self) -> bool:
        tab = self.current_tab
        return self._save_tab(tab) if tab else False

    def _save_tab(self, tab: _EditorTab) -> bool:
        if tab.path is None:
            path_text, _ = QFileDialog.getSaveFileName(
                self, "Save CAPL File", str(self.workspace / "NewNode.can"),
                "CAPL (*.can *.cin)")
            if not path_text:
                return False
            tab.path = Path(path_text)
            tab.editor.file_path = tab.path
        try:
            tab.path.write_text(tab.editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))
            return False
        tab.editor.document().setModified(False)
        self._update_tab_title(tab)
        self.refresh_file_tree()
        self.status_message.emit(f"Saved {tab.path.name}")
        return True

    def _on_tab_changed(self, _index: int) -> None:
        editor = self.current_editor
        if editor is None:
            self.outline.clear()
            self.problems.clear()
            return
        self._on_symbols(editor.symbols)
        self._on_diagnostics(editor.diagnostics)

    # ==================================================================
    # Compile / errors
    # ==================================================================
    def compile_current(self) -> None:
        tab = self.current_tab
        if tab is None:
            self.status_message.emit("No CAPL file is open to compile.")
            return
        tab.editor.analyze()
        diags = tab.editor.diagnostics
        errors = sum(1 for d in diags if d.severity is Severity.ERROR)
        warnings = sum(1 for d in diags if d.severity is Severity.WARNING)
        name = tab.title.rstrip(" *")
        if errors == 0:
            self.status_message.emit(f"{name}: build succeeded, {warnings} warning(s).")
        else:
            self.status_message.emit(f"{name}: {errors} error(s), {warnings} warning(s).")
        self.compile_finished.emit(name, errors, warnings)

    def _on_diagnostics(self, diagnostics: list[Diagnostic]) -> None:
        if self.sender() is not None and self.current_editor is not self.sender():
            return
        self.problems.clear()
        counts = {Severity.ERROR: 0, Severity.WARNING: 0, Severity.INFO: 0}
        icon_name = {Severity.ERROR: "error", Severity.WARNING: "warning",
                     Severity.INFO: "info", Severity.HINT: "info"}
        for diag in diagnostics:
            counts[diag.severity if diag.severity in counts else Severity.INFO] += 1
            item = QTreeWidgetItem(["", diag.code, diag.message,
                                    str(diag.line), str(diag.column)])
            item.setIcon(0, icon(icon_name[diag.severity], 14))
            item.setData(0, Qt.ItemDataRole.UserRole, (diag.line, diag.column))
            item.setFont(1, mono_font(9))
            if diag.severity is Severity.ERROR:
                item.setForeground(2, QColor(PALETTE.error))
            elif diag.severity is Severity.WARNING:
                item.setForeground(2, QColor(PALETTE.warning))
            else:
                item.setForeground(2, QColor(PALETTE.text_muted))
            self.problems.addTopLevelItem(item)
        self._set_problems_header(counts[Severity.ERROR], counts[Severity.WARNING],
                                  counts[Severity.INFO])

    def _set_problems_header(self, errors: int, warnings: int, infos: int) -> None:
        if errors == 0 and warnings == 0:
            text = "  Build Results — no errors"
            color = PALETTE.running
        else:
            text = f"  Build Results — {errors} error(s), {warnings} warning(s), {infos} hint(s)"
            color = PALETTE.error if errors else PALETTE.warning
        self.problems_header.setText(text)
        self.problems_header.setStyleSheet(
            f"background: {PALETTE.panel_header}; color: {color};"
            f" border-top: 1px solid {PALETTE.border};"
            f" border-bottom: 1px solid {PALETTE.border_light}; padding: 4px;"
        )

    def _on_problem_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        position = item.data(0, Qt.ItemDataRole.UserRole)
        editor = self.current_editor
        if position and editor:
            editor.goto_line(*position)

    # ==================================================================
    # Outline
    # ==================================================================
    def _on_symbols(self, symbols) -> None:
        if self.sender() is not None and self.current_editor is not self.sender():
            return
        self.outline.clear()

        def add(parent, symbol):
            item = QTreeWidgetItem([symbol.name, symbol.detail])
            item.setIcon(0, icon(_SYMBOL_ICON.get(symbol.kind, "sym_block"), 14))
            item.setData(0, Qt.ItemDataRole.UserRole, (symbol.line, symbol.column))
            if symbol.kind in ("handler", "testcase"):
                font = QFont(ui_font(9))
                font.setBold(True)
                item.setFont(0, font)
            item.setForeground(1, QColor(PALETTE.text_muted))
            if parent is None:
                self.outline.addTopLevelItem(item)
            else:
                parent.addChild(item)
            for child in symbol.children:
                add(item, child)
            return item

        for symbol in symbols:
            node = add(None, symbol)
            node.setExpanded(symbol.kind not in ("block",))

    def _on_outline_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        position = item.data(0, Qt.ItemDataRole.UserRole)
        editor = self.current_editor
        if position and editor and position[0] > 0:
            editor.goto_line(*position)

    # ==================================================================
    def _insert_snippet(self, snippet) -> None:
        editor = self.current_editor
        if editor is None:
            self.new_file()
            editor = self.current_editor
        if editor is not None:
            editor.insert_snippet(snippet)

    def goto_line_dialog(self) -> None:
        editor = self.current_editor
        if editor is None:
            return
        line, ok = QInputDialog.getInt(self, "Go to Line", "Line number:",
                                       editor.textCursor().blockNumber() + 1,
                                       1, max(1, editor.blockCount()))
        if ok:
            editor.goto_line(line)

    def has_unsaved(self) -> bool:
        return any(self.tabs.widget(i).editor.document().isModified()
                   for i in range(self.tabs.count()))
