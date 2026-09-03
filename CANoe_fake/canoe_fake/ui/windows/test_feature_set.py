"""Test Feature Set — the Test Module + Test Report window.

The test module tree is built **from real CAPL source**: `.can` files in the
workspace are parsed, and every `testcase` / `testfunction` declaration
becomes an entry in the tree.

Running tests in Phase 1 is a simulated progression (there is no CAPL
execution engine yet); every run notes that clearly in the report. Phase 2
only needs to swap `_SimulatedRunner` for a real engine.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel,
                               QProgressBar, QSplitter, QToolBar, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ...capl import compile_source
from ..icons import icon
from ..theme import PALETTE, mono_font, ui_font

_VERDICT_COLOR = {
    "pass": PALETTE.running,
    "fail": PALETTE.error,
    "warning": PALETTE.warning,
    "none": PALETTE.text_muted,
    "running": PALETTE.accent,
}


@dataclass
class TestCaseInfo:
    name: str
    signature: str
    line: int
    module: str
    steps: list[str] = field(default_factory=list)


@dataclass
class TestModuleInfo:
    name: str
    path: Path
    cases: list[TestCaseInfo] = field(default_factory=list)
    parse_errors: int = 0


class _SimulatedRunner(QObject):
    """Simulated runner: emits each test step on a real-time tick."""

    step_started = Signal(object, str)          # TestCaseInfo, step description
    step_finished = Signal(object, str, str)    # TestCaseInfo, description, verdict
    case_finished = Signal(object, str)         # TestCaseInfo, verdict
    run_finished = Signal(int, int, int)        # pass, fail, warning

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self._advance)
        self._queue: list[tuple[TestCaseInfo, str]] = []
        self._index = 0
        self._counts = {"pass": 0, "fail": 0, "warning": 0}
        self._case_verdicts: dict[str, str] = {}

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def start(self, cases: list[TestCaseInfo]) -> None:
        self._queue = []
        for case in cases:
            steps = case.steps or ["Set up initial conditions",
                                   "Execute the main action",
                                   "Check the expected result"]
            for step in steps:
                self._queue.append((case, step))
        self._index = 0
        self._counts = {"pass": 0, "fail": 0, "warning": 0}
        self._case_verdicts.clear()
        if self._queue:
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._queue.clear()

    def _advance(self) -> None:
        if self._index >= len(self._queue):
            self._timer.stop()
            self.run_finished.emit(self._counts["pass"], self._counts["fail"],
                                   self._counts["warning"])
            return

        case, step = self._queue[self._index]
        self._index += 1
        roll = random.random()
        verdict = "pass" if roll < 0.84 else ("warning" if roll < 0.93 else "fail")
        self.step_started.emit(case, step)
        self.step_finished.emit(case, step, verdict)

        previous = self._case_verdicts.get(case.name, "pass")
        rank = {"pass": 0, "warning": 1, "fail": 2}
        if rank[verdict] > rank[previous]:
            self._case_verdicts[case.name] = verdict
        else:
            self._case_verdicts.setdefault(case.name, previous)

        is_last_of_case = (self._index >= len(self._queue)
                           or self._queue[self._index][0] is not case)
        if is_last_of_case:
            final = self._case_verdicts.get(case.name, "pass")
            self._counts[final] += 1
            self.case_finished.emit(case, final)


class TestFeatureSetWindow(QWidget):
    """Test module tree on the left, test report on the right."""

    log_message = Signal(str, str)     # text, level

    def __init__(self, workspace: Path, parent=None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._modules: list[TestModuleInfo] = []
        self._report_items: dict[str, QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_module_tree())
        splitter.addWidget(self._build_report())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([330, 640])
        layout.addWidget(splitter, 1)

        self.runner = _SimulatedRunner(self)
        self.runner.step_finished.connect(self._on_step_finished)
        self.runner.case_finished.connect(self._on_case_finished)
        self.runner.run_finished.connect(self._on_run_finished)

        self.reload_modules()

    # ==================================================================
    def _build_toolbar(self) -> QToolBar:
        bar = QToolBar()
        bar.setIconSize(bar.iconSize() * 0.85)
        bar.addAction(icon("start"), "Run Test Module", self.start_run)
        bar.addAction(icon("stop"), "Stop", self.stop_run)
        bar.addSeparator()
        bar.addAction(icon("open"), "Reload Modules from Workspace", self.reload_modules)
        bar.addAction(icon("clear"), "Clear Report", self.clear_report)
        bar.addSeparator()

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setValue(0)
        bar.addWidget(self.progress)

        self.summary = QLabel("  not run yet")
        self.summary.setFont(ui_font(9, bold=True))
        bar.addWidget(self.summary)
        return bar

    def _build_module_tree(self) -> QWidget:
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        header = QLabel("  Test Modules (scanned from .can files in the workspace)")
        header.setFont(ui_font(9, bold=True))
        header.setStyleSheet(
            f"background: {PALETTE.panel_header}; color: {PALETTE.text_muted};"
            f" border-bottom: 1px solid {PALETTE.border}; padding: 5px;")
        box.addWidget(header)

        self.module_tree = QTreeWidget()
        self.module_tree.setHeaderLabels(["Test Case", "Signature"])
        self.module_tree.setFont(ui_font(9))
        self.module_tree.setColumnWidth(0, 190)
        self.module_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.module_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        box.addWidget(self.module_tree, 1)
        return container

    def _build_report(self) -> QWidget:
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        header = QLabel("  Test Report")
        header.setFont(ui_font(9, bold=True))
        header.setStyleSheet(
            f"background: {PALETTE.panel_header}; color: {PALETTE.text_muted};"
            f" border-bottom: 1px solid {PALETTE.border}; padding: 5px;")
        box.addWidget(header)

        self.report = QTreeWidget()
        self.report.setHeaderLabels(["Item", "Verdict", "Note"])
        self.report.setFont(ui_font(9))
        self.report.setColumnWidth(0, 300)
        self.report.setColumnWidth(1, 80)
        self.report.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.report.setAlternatingRowColors(True)
        box.addWidget(self.report, 1)
        return container

    # ==================================================================
    # Load modules from real CAPL source
    # ==================================================================
    def reload_modules(self) -> None:
        self.module_tree.clear()
        self._modules.clear()

        files = sorted(self.workspace.glob("*.can"))
        for path in files:
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            result = compile_source(source, str(path))
            if not result.unit.testcases:
                continue
            module = TestModuleInfo(name=path.stem, path=path,
                                    parse_errors=len(result.diagnostics.errors))
            for tc in result.unit.testcases:
                module.cases.append(TestCaseInfo(
                    name=tc.name, signature=tc.signature, line=tc.line,
                    module=module.name, steps=_extract_steps(source, tc),
                ))
            self._modules.append(module)

        for module in self._modules:
            root = QTreeWidgetItem([module.name, str(module.path.name)])
            root.setIcon(0, icon("test", 14))
            root.setFont(0, ui_font(9, bold=True))
            if module.parse_errors:
                root.setForeground(1, QColor(PALETTE.error))
                root.setText(1, f"{module.path.name} — {module.parse_errors} build error(s)")
            self.module_tree.addTopLevelItem(root)
            for case in module.cases:
                item = QTreeWidgetItem([case.name, case.signature])
                item.setIcon(0, icon("sym_testcase", 14))
                item.setFont(1, mono_font(8))
                item.setForeground(1, QColor(PALETTE.text_muted))
                item.setData(0, Qt.ItemDataRole.UserRole, case)
                item.setCheckState(0, Qt.CheckState.Checked)
                root.addChild(item)
            root.setExpanded(True)

        total = sum(len(m.cases) for m in self._modules)
        if total == 0:
            hint = QTreeWidgetItem([
                "(no testcases found)",
                "add 'testcase TC_Name() { ... }' to a .can file"])
            hint.setForeground(0, QColor(PALETTE.text_disabled))
            hint.setForeground(1, QColor(PALETTE.text_disabled))
            self.module_tree.addTopLevelItem(hint)
        self.log_message.emit(
            f"Loaded {len(self._modules)} test module(s), {total} test case(s) total.", "info")

    def _selected_cases(self) -> list[TestCaseInfo]:
        out: list[TestCaseInfo] = []
        for i in range(self.module_tree.topLevelItemCount()):
            root = self.module_tree.topLevelItem(i)
            for j in range(root.childCount()):
                child = root.child(j)
                case = child.data(0, Qt.ItemDataRole.UserRole)
                if case is not None and child.checkState(0) == Qt.CheckState.Checked:
                    out.append(case)
        return out

    # ==================================================================
    # Run tests
    # ==================================================================
    def start_run(self) -> None:
        if self.runner.running:
            return
        cases = self._selected_cases()
        if not cases:
            self.log_message.emit(
                "No test cases selected — check the boxes in the Test Modules tree.", "warning")
            return

        self.clear_report()
        self._total_steps = sum(len(c.steps) or 3 for c in cases)
        self._done_steps = 0
        self.progress.setMaximum(self._total_steps)
        self.progress.setValue(0)

        note = QTreeWidgetItem([
            "Note", "",
            "Phase 1 simulates the test progression — it does not execute real CAPL "
            "code yet. An execution engine will be attached in Phase 2."])
        note.setIcon(0, icon("info", 14))
        note.setForeground(2, QColor(PALETTE.text_muted))
        self.report.addTopLevelItem(note)

        by_module: dict[str, QTreeWidgetItem] = {}
        for case in cases:
            module_item = by_module.get(case.module)
            if module_item is None:
                module_item = QTreeWidgetItem([f"Test Module: {case.module}", "", ""])
                module_item.setIcon(0, icon("test", 14))
                module_item.setFont(0, ui_font(9, bold=True))
                self.report.addTopLevelItem(module_item)
                module_item.setExpanded(True)
                by_module[case.module] = module_item

            case_item = QTreeWidgetItem([case.name, "running", ""])
            case_item.setIcon(0, icon("sym_testcase", 14))
            self._set_verdict(case_item, "running")
            module_item.addChild(case_item)
            case_item.setExpanded(True)
            self._report_items[case.name] = case_item

        self.summary.setText("  running...")
        self.summary.setStyleSheet(f"color: {PALETTE.accent};")
        self.runner.start(cases)
        self.log_message.emit(f"Started running {len(cases)} test case(s).", "info")

    def stop_run(self) -> None:
        if not self.runner.running:
            return
        self.runner.stop()
        self.summary.setText("  stopped")
        self.summary.setStyleSheet(f"color: {PALETTE.warning};")
        self.log_message.emit("Test module stopped by request.", "warning")

    def clear_report(self) -> None:
        self.report.clear()
        self._report_items.clear()
        self.progress.setValue(0)
        self.summary.setText("  not run yet")
        self.summary.setStyleSheet(f"color: {PALETTE.text_muted};")

    # ------------------------------------------------------------------
    def _on_step_finished(self, case: TestCaseInfo, step: str, verdict: str) -> None:
        parent = self._report_items.get(case.name)
        if parent is None:
            return
        item = QTreeWidgetItem([f"  {step}", verdict, ""])
        self._set_verdict(item, verdict)
        parent.addChild(item)
        self._done_steps += 1
        self.progress.setValue(self._done_steps)

    def _on_case_finished(self, case: TestCaseInfo, verdict: str) -> None:
        item = self._report_items.get(case.name)
        if item is not None:
            self._set_verdict(item, verdict)
            item.setText(2, f"{item.childCount()} step(s)")

    def _on_run_finished(self, passed: int, failed: int, warnings: int) -> None:
        total = passed + failed + warnings
        self.summary.setText(f"  {passed} pass · {warnings} warning · {failed} fail")
        color = PALETTE.error if failed else (PALETTE.warning if warnings
                                              else PALETTE.running)
        self.summary.setStyleSheet(f"color: {color};")

        result = QTreeWidgetItem([
            "Overall Result", "fail" if failed else ("warning" if warnings else "pass"),
            f"{total} test case: {passed} pass, {warnings} warning, {failed} fail"])
        self._set_verdict(result, "fail" if failed else
                          ("warning" if warnings else "pass"))
        result.setFont(0, ui_font(9, bold=True))
        self.report.addTopLevelItem(result)
        self.log_message.emit(
            f"Test module finished: {passed} pass, {warnings} warning, {failed} fail.",
            "error" if failed else "success")

    @staticmethod
    def _set_verdict(item: QTreeWidgetItem, verdict: str) -> None:
        item.setText(1, verdict)
        color = QColor(_VERDICT_COLOR.get(verdict, PALETTE.text_muted))
        item.setForeground(1, color)
        font = QFont(ui_font(9))
        font.setBold(verdict in ("fail", "pass"))
        item.setFont(1, font)


#: only matches `TestStep("id", "description")` — NOT TestStepPass/Fail/Warning.
#: Pass/Fail is the *result* of a step, not a new step; folding them into the
#: list would make the report list both mutually-exclusive branches as steps.
_TEST_STEP_RE = re.compile(
    r"\bTestStep\s*\(\s*\"[^\"]*\"\s*,\s*\"([^\"]*)\"", re.IGNORECASE)


def _extract_steps(source: str, testcase) -> list[str]:
    """Extract step descriptions from `TestStep(...)` calls inside a testcase body."""
    lines = source.splitlines()
    start = max(0, testcase.line - 1)
    depth = 0
    started = False
    steps: list[str] = []

    for line in lines[start:]:
        depth += line.count("{")
        if depth > 0:
            started = True
        match = _TEST_STEP_RE.search(line)
        if match:
            steps.append(match.group(1))
        depth -= line.count("}")
        if started and depth <= 0:
            break
    return steps
