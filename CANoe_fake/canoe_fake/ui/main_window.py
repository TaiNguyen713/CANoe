"""Main window of CANoe Fake.

Layout follows CANoe: menu + toolbar on top, "desktops" switched via a tab bar
at the bottom, the Write Window docked at the bottom edge, and a status bar
showing measurement state, elapsed time, and bus load.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import (QDockWidget, QLabel, QMainWindow, QMessageBox,
                               QStackedWidget, QTabBar, QToolBar, QVBoxLayout,
                               QWidget)

from .. import APP_EDITION, APP_TITLE, __version__
from ..backend.base import (BusEvent, BusStatistics, EventKind,
                            MeasurementBackend, MeasurementState)
from ..backend.simulated import SimulatedBackend
from ..model.database import Configuration, NodeDef, demo_configuration
from .capl import CaplBrowser
from .dialogs import CaplReferenceDialog
from .icons import icon
from .theme import PALETTE, stylesheet, ui_font
from .windows import (DiagnosticsWindow, MeasurementSetupView, SetupPanel,
                      SimulationSetupView, StatisticsWindow,
                      TestFeatureSetWindow, TraceWindow, WriteWindow)

#: (key, display label, icon)
DESKTOPS = (
    ("measurement", "Measurement Setup", "measurement"),
    ("simulation", "Simulation Setup", "bus"),
    ("trace", "Trace", "trace"),
    ("capl", "CAPL Browser", "capl"),
    ("diagnostics", "Diagnostics", "diagnostics"),
    ("test", "Test", "test"),
)


class MainWindow(QMainWindow):
    def __init__(self, config: Configuration | None = None,
                 backend: MeasurementBackend | None = None,
                 workspace: Path | None = None) -> None:
        super().__init__()
        self.config = config or demo_configuration()
        self.workspace = workspace or (Path(__file__).resolve().parents[2] / "capl")
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.backend = backend or SimulatedBackend(self.config, self)
        self._reference_dialog: CaplReferenceDialog | None = None
        #: assigned early because QTabBar.currentChanged fires as soon as the
        #: first tab is added, i.e. before _build_actions() runs
        self.desktop_actions: QActionGroup | None = None

        self.setWindowTitle(f"{APP_TITLE} — {self.config.title}")
        self.setStyleSheet(stylesheet())
        self.setFont(ui_font(9))
        self.resize(1500, 940)
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks
                            | QMainWindow.DockOption.AllowNestedDocks
                            | QMainWindow.DockOption.AllowTabbedDocks)

        self._build_desktops()
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_status_bar()
        self._connect_backend()

        self._clock = QTimer(self)
        self._clock.setInterval(200)
        self._clock.timeout.connect(self._update_clock)
        self._clock.start()

        self.measurement_view.rebuild(self.config)
        self.simulation_view.rebuild(self.config)
        self._switch_desktop(0)
        self._update_state_ui(MeasurementState.STOPPED)

    # ==================================================================
    # Build UI
    # ==================================================================
    def _build_desktops(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.desktop_bar = QTabBar()
        self.desktop_bar.setExpanding(False)
        self.desktop_bar.setDrawBase(False)
        self.desktop_bar.setFont(ui_font(9))
        self.desktop_bar.currentChanged.connect(self._switch_desktop)
        self.desktop_bar.setStyleSheet(f"""
            QTabBar {{ background: {PALETTE.ribbon}; }}
            QTabBar::tab {{
                background: {PALETTE.panel_header};
                border: 1px solid {PALETTE.border};
                border-top: none;
                padding: 5px 16px;
                margin-right: 1px;
                color: {PALETTE.text_muted};
            }}
            QTabBar::tab:selected {{
                background: {PALETTE.surface};
                color: {PALETTE.text};
                border-top: 2px solid {PALETTE.accent};
                font-weight: 600;
            }}
            QTabBar::tab:hover:!selected {{ background: {PALETTE.accent_hover}; }}
        """)
        layout.addWidget(self.desktop_bar)
        self.setCentralWidget(central)

        # -- desktops --------------------------------------------------
        self.measurement_view = MeasurementSetupView()
        self.measurement_view.open_window_requested.connect(self._open_analysis_window)
        self.stack.addWidget(SetupPanel(
            self.measurement_view,
            "Measurement Setup — data flow from the bus to the analysis windows"))

        self.simulation_view = SimulationSetupView()
        self.simulation_view.node_activated.connect(self._open_node_capl)
        self.stack.addWidget(SetupPanel(
            self.simulation_view,
            "Simulation Setup — network diagram and simulated nodes"))

        self.trace_window = TraceWindow()
        self.stack.addWidget(self.trace_window)

        self.capl_browser = CaplBrowser(self.workspace)
        self.capl_browser.status_message.connect(self._show_status)
        self.capl_browser.compile_finished.connect(self._on_compile_finished)
        self.stack.addWidget(self.capl_browser)

        self.diagnostics_window = DiagnosticsWindow(self.config)
        self.diagnostics_window.send_requested.connect(self.backend.send_diag_request)
        self.stack.addWidget(self.diagnostics_window)

        self.test_window = TestFeatureSetWindow(self.workspace)
        self.test_window.log_message.connect(
            lambda text, level: self.write_window.log(text, level, "Test"))
        self.stack.addWidget(self.test_window)

        for key, label, icon_name in DESKTOPS:
            index = self.desktop_bar.addTab(icon(icon_name, 14), label)
            self.desktop_bar.setTabData(index, key)

    def _build_docks(self) -> None:
        self.write_window = WriteWindow()
        self.write_dock = QDockWidget("Write Window", self)
        self.write_dock.setObjectName("dock_write")
        self.write_dock.setWidget(self.write_window)
        self.write_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea
                                        | Qt.DockWidgetArea.TopDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.write_dock)
        self.resizeDocks([self.write_dock], [180], Qt.Orientation.Vertical)

        self.statistics_window = StatisticsWindow()
        self.statistics_dock = QDockWidget("Statistics", self)
        self.statistics_dock.setObjectName("dock_statistics")
        self.statistics_dock.setWidget(self.statistics_window)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.statistics_dock)
        self.resizeDocks([self.statistics_dock], [380], Qt.Orientation.Horizontal)
        self.statistics_dock.hide()

    # ------------------------------------------------------------------
    def _build_actions(self) -> None:
        def act(name: str, text: str, icon_name: str = "", shortcut: str = "",
                tip: str = "", checkable: bool = False, slot=None) -> QAction:
            action = QAction(text, self)
            if icon_name:
                action.setIcon(icon(icon_name))
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.setStatusTip(tip or text)
            action.setToolTip(f"{text} ({shortcut})" if shortcut else text)
            action.setCheckable(checkable)
            if slot is not None:
                action.triggered.connect(slot)
            setattr(self, name, action)
            return action

        # File
        act("act_new_config", "New Configuration", "new", "Ctrl+N",
            "Create an empty configuration", slot=self.new_configuration)
        act("act_open_config", "Open Configuration...", "open", "Ctrl+O",
            "Open a saved configuration", slot=self.open_configuration)
        act("act_save_config", "Save Configuration", "save", "Ctrl+Shift+S",
            slot=self.save_configuration)
        act("act_exit", "Exit", shortcut="Alt+F4", slot=self.close)

        # Measurement
        act("act_start", "Start Measurement", "start", "F9",
            "Start the measurement (F9)", slot=self.start_measurement)
        act("act_pause", "Pause", "pause", "F8", slot=self.pause_measurement)
        act("act_stop", "Stop Measurement", "stop", "Ctrl+F9",
            slot=self.stop_measurement)
        act("act_reset_stats", "Reset Statistics", "clear",
            slot=self.reset_statistics)

        # Analysis
        act("act_clear_trace", "Clear Trace", "clear", "Ctrl+L",
            slot=lambda: self.trace_window.clear())
        act("act_clear_write", "Clear Write Window",
            slot=lambda: self.write_window.clear_all())
        act("act_toggle_write", "Write Window", "write", "Alt+1", checkable=True,
            slot=lambda checked: self.write_dock.setVisible(checked))
        act("act_toggle_stats", "Statistics", "statistics", "Alt+2", checkable=True,
            slot=lambda checked: self.statistics_dock.setVisible(checked))
        self.act_toggle_write.setChecked(True)
        self.act_toggle_stats.setChecked(False)

        # CAPL
        act("act_capl_new", "New CAPL File", "new",
            slot=lambda: (self._goto_desktop("capl"), self.capl_browser.new_file()))
        act("act_capl_save", "Save CAPL File", "save", "Ctrl+S",
            slot=self.capl_browser.save_current)
        act("act_capl_compile", "Compile CAPL File", "compile", "F7",
            slot=lambda: (self._goto_desktop("capl"),
                          self.capl_browser.compile_current()))
        act("act_capl_reference", "CAPL Syntax Reference...", "capl", "F1",
            slot=self.show_capl_reference)

        # Diagnostics / Test
        act("act_tester_present", "Send TesterPresent (0x3E)", "diagnostics",
            slot=self.send_tester_present)
        act("act_test_reload", "Reload Test Module", "open",
            slot=lambda: (self._goto_desktop("test"),
                          self.test_window.reload_modules()))
        act("act_test_run", "Run Test Module", "test", "F5",
            slot=lambda: (self._goto_desktop("test"), self.test_window.start_run()))

        # Help
        act("act_about", "About CANoe Fake", slot=self.show_about)

        # Desktop switching
        self.desktop_actions = QActionGroup(self)
        self.desktop_actions.setExclusive(True)
        for index, (key, label, icon_name) in enumerate(DESKTOPS):
            action = QAction(icon(icon_name), label, self)
            action.setCheckable(True)
            action.setShortcut(QKeySequence(f"Ctrl+{index + 1}"))
            action.triggered.connect(lambda _c=False, i=index: self._goto_index(i))
            self.desktop_actions.addAction(action)

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        file_menu.addAction(self.act_new_config)
        file_menu.addAction(self.act_open_config)
        file_menu.addAction(self.act_save_config)
        file_menu.addSeparator()
        file_menu.addAction(self.act_capl_new)
        file_menu.addAction(self.act_capl_save)
        file_menu.addSeparator()
        file_menu.addAction(self.act_exit)

        view_menu = bar.addMenu("&View")
        for action in self.desktop_actions.actions():
            view_menu.addAction(action)
        view_menu.addSeparator()
        view_menu.addAction(self.act_toggle_write)
        view_menu.addAction(self.act_toggle_stats)

        sim_menu = bar.addMenu("&Simulation")
        sim_menu.addAction(self.act_start)
        sim_menu.addAction(self.act_pause)
        sim_menu.addAction(self.act_stop)
        sim_menu.addSeparator()
        sim_menu.addAction(self.desktop_actions.actions()[1])   # Simulation Setup

        analysis_menu = bar.addMenu("&Analysis")
        analysis_menu.addAction(self.desktop_actions.actions()[2])   # Trace
        analysis_menu.addAction(self.act_toggle_stats)
        analysis_menu.addSeparator()
        analysis_menu.addAction(self.act_clear_trace)
        analysis_menu.addAction(self.act_clear_write)
        analysis_menu.addAction(self.act_reset_stats)

        test_menu = bar.addMenu("&Test")
        test_menu.addAction(self.act_test_run)
        test_menu.addAction(self.act_test_reload)
        test_menu.addSeparator()
        test_menu.addAction(self.desktop_actions.actions()[5])

        diag_menu = bar.addMenu("&Diagnostics")
        diag_menu.addAction(self.desktop_actions.actions()[4])
        diag_menu.addSeparator()
        diag_menu.addAction(self.act_tester_present)

        tools_menu = bar.addMenu("Too&ls")
        tools_menu.addAction(self.desktop_actions.actions()[3])   # CAPL Browser
        tools_menu.addAction(self.act_capl_compile)
        tools_menu.addSeparator()
        tools_menu.addAction(self.act_capl_reference)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self.act_capl_reference)
        help_menu.addSeparator()
        help_menu.addAction(self.act_about)

    def _build_toolbars(self) -> None:
        measure_bar = QToolBar("Measurement")
        measure_bar.setObjectName("toolbar_measurement")
        measure_bar.setMovable(False)
        measure_bar.addAction(self.act_start)
        measure_bar.addAction(self.act_pause)
        measure_bar.addAction(self.act_stop)
        measure_bar.addSeparator()
        measure_bar.addAction(self.act_clear_trace)
        measure_bar.addAction(self.act_reset_stats)
        measure_bar.addSeparator()
        measure_bar.addAction(self.act_toggle_write)
        measure_bar.addAction(self.act_toggle_stats)
        measure_bar.addSeparator()
        measure_bar.addAction(self.act_capl_compile)
        measure_bar.addAction(self.act_capl_reference)
        self.addToolBar(measure_bar)

        desktop_bar = QToolBar("Desktops")
        desktop_bar.setObjectName("toolbar_desktops")
        desktop_bar.setMovable(False)
        desktop_bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for action in self.desktop_actions.actions():
            desktop_bar.addAction(action)
        self.addToolBar(desktop_bar)

    def _build_status_bar(self) -> None:
        bar = self.statusBar()

        self.state_label = QLabel()
        self.state_label.setFont(ui_font(9, bold=True))
        self.state_label.setMinimumWidth(150)
        bar.addPermanentWidget(self.state_label)

        self.time_label = QLabel("t = 0.000 s")
        self.time_label.setFont(ui_font(9))
        self.time_label.setMinimumWidth(120)
        bar.addPermanentWidget(self.time_label)

        self.load_label = QLabel("Bus load —")
        self.load_label.setFont(ui_font(9))
        self.load_label.setMinimumWidth(130)
        bar.addPermanentWidget(self.load_label)

        self.config_label = QLabel(self.config.title)
        self.config_label.setFont(ui_font(9))
        bar.addPermanentWidget(self.config_label)

        bar.showMessage(f"{APP_TITLE} {__version__} — {APP_EDITION}. "
                        "Press F9 to start the measurement.")

    # ==================================================================
    # Backend wiring
    # ==================================================================
    def _connect_backend(self) -> None:
        self.backend.event_received.connect(self._on_event)
        self.backend.events_received.connect(self._on_events)
        self.backend.statistics_updated.connect(self._on_statistics)
        self.backend.state_changed.connect(self._update_state_ui)

    def _on_event(self, event: BusEvent) -> None:
        self.trace_window.add_event(event)
        self._dispatch_special(event)

    def _on_events(self, events: list[BusEvent]) -> None:
        self.trace_window.add_events(events)
        for event in events:
            self._dispatch_special(event)

    def _dispatch_special(self, event: BusEvent) -> None:
        if event.kind is EventKind.CAPL_WRITE:
            tab = "System" if event.node == "CANoe" else "CAPL"
            self.write_window.log_measurement(event.timestamp, event.detail,
                                              "system", tab)
        elif event.kind in (EventKind.DIAG_REQUEST, EventKind.DIAG_RESPONSE):
            self.diagnostics_window.handle_event(event)
            self.write_window.log_measurement(
                event.timestamp,
                f"{event.name}  {event.data_text}  — {event.detail}",
                "diag", "Diagnostics")
        elif event.kind is EventKind.ERROR_FRAME:
            self.write_window.log_measurement(
                event.timestamp, f"Error frame on CAN {event.channel}: {event.detail}",
                "error", "System")

    def _on_statistics(self, stat: BusStatistics) -> None:
        self.statistics_window.update_statistics(stat)
        if stat.channel == 1:
            color = (PALETTE.error if stat.bus_load_percent > 70
                     else PALETTE.warning if stat.bus_load_percent > 45
                     else PALETTE.running)
            self.load_label.setText(f"Bus load {stat.bus_load_percent:.1f} %")
            self.load_label.setStyleSheet(f"color: {color};")

    def _update_state_ui(self, state: MeasurementState) -> None:
        running = state is MeasurementState.RUNNING
        self.act_start.setEnabled(not running)
        self.act_pause.setEnabled(running)
        self.act_stop.setEnabled(state is not MeasurementState.STOPPED)

        color = {MeasurementState.RUNNING: PALETTE.running,
                 MeasurementState.PAUSED: PALETTE.paused,
                 MeasurementState.STOPPED: PALETTE.stopped}[state]
        symbol = {MeasurementState.RUNNING: "●",
                  MeasurementState.PAUSED: "❚❚",
                  MeasurementState.STOPPED: "■"}[state]
        self.state_label.setText(f"{symbol}  {state.label}")
        self.state_label.setStyleSheet(f"color: {color};")

        if state is MeasurementState.STOPPED:
            self.load_label.setText("Bus load —")
            self.load_label.setStyleSheet(f"color: {PALETTE.text_muted};")

    def _update_clock(self) -> None:
        self.time_label.setText(f"t = {self.backend.elapsed:.3f} s")

    # ==================================================================
    # Actions
    # ==================================================================
    def start_measurement(self) -> None:
        self.backend.start()
        self._show_status("Measurement running — simulated nodes are now sending frames.")

    def pause_measurement(self) -> None:
        self.backend.pause()
        self._show_status("Measurement paused.")

    def stop_measurement(self) -> None:
        self.backend.stop()
        self._show_status("Measurement stopped.")

    def reset_statistics(self) -> None:
        self.statistics_window.reset()
        self._show_status("Statistics have been reset.")

    def send_tester_present(self) -> None:
        if not self.config.diag_ecus:
            self._show_status("The configuration has no diagnostic ECU.")
            return
        ecu = self.config.diag_ecus[0]
        self.backend.send_diag_request(ecu.name, bytes((0x3E, 0x00)))
        self._goto_desktop("diagnostics")

    def new_configuration(self) -> None:
        answer = QMessageBox.question(
            self, "New Configuration",
            "Reload the default demo configuration?\n"
            "Trace and Write Window contents will be cleared.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.backend.stop()
        self.config = demo_configuration()
        self._apply_configuration()

    def open_configuration(self) -> None:
        QMessageBox.information(
            self, "Open Configuration",
            "Reading/writing real .cfg files will be wired up in Phase 2 together "
            "with your framework.\n\n"
            "In Phase 1, the demo configuration is built in "
            "canoe_fake/model/database.py — edit demo_configuration() to change "
            "the networks, nodes, messages, and diagnostic ECUs.")

    def save_configuration(self) -> None:
        QMessageBox.information(
            self, "Save Configuration",
            "Writing .cfg files will be wired up in Phase 2 together with your "
            "framework.")

    def _apply_configuration(self) -> None:
        if isinstance(self.backend, SimulatedBackend):
            self.backend.reload_configuration(self.config)
        self.measurement_view.rebuild(self.config)
        self.simulation_view.rebuild(self.config)
        self.diagnostics_window.reload(self.config)
        self.trace_window.clear()
        self.statistics_window.reset()
        self.setWindowTitle(f"{APP_TITLE} — {self.config.title}")
        self.config_label.setText(self.config.title)

    def show_capl_reference(self) -> None:
        if self._reference_dialog is None:
            self._reference_dialog = CaplReferenceDialog(self)
            self._reference_dialog.insert_requested.connect(self._insert_into_editor)
        self._reference_dialog.show()
        self._reference_dialog.raise_()
        self._reference_dialog.activateWindow()

    def _insert_into_editor(self, text: str) -> None:
        self._goto_desktop("capl")
        editor = self.capl_browser.current_editor
        if editor is None:
            self.capl_browser.new_file()
            editor = self.capl_browser.current_editor
        if editor is not None:
            editor.textCursor().insertText(text)
            editor.setFocus()

    def show_about(self) -> None:
        QMessageBox.about(
            self, f"About {APP_TITLE}",
            f"<h3>{APP_TITLE} {__version__}</h3>"
            f"<p>{APP_EDITION} — a simulated Vector CANoe user interface.</p>"
            "<p><b>Phase 1</b> (this build): the full UI plus a complete CAPL "
            "language layer (syntax highlighting, code completion, lexer, "
            "AST-producing parser, semantic checks).</p>"
            "<p><b>Phase 2</b>: attach a real execution engine through the "
            "<code>canoe_fake.backend.MeasurementBackend</code> layer.</p>"
            "<p style='color:#6a707a'>Not affiliated with Vector Informatik GmbH. "
            "This is a learning/prototyping tool, not for real bus measurement.</p>")

    # ==================================================================
    # Desktop navigation
    # ==================================================================
    def _switch_desktop(self, index: int) -> None:
        if index < 0 or index >= self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        if self.desktop_bar.currentIndex() != index:
            self.desktop_bar.blockSignals(True)
            self.desktop_bar.setCurrentIndex(index)
            self.desktop_bar.blockSignals(False)
        if self.desktop_actions is not None:
            actions = self.desktop_actions.actions()
            if index < len(actions):
                actions[index].setChecked(True)

        if not hasattr(self, "statistics_dock"):
            return      # still building the UI

        key = DESKTOPS[index][0]
        # Statistics only auto-shows while viewing Trace, but honors the user's choice
        if key == "trace" and not self.statistics_dock.isVisible():
            self.statistics_dock.show()
            self.act_toggle_stats.setChecked(True)

    def _goto_index(self, index: int) -> None:
        self.desktop_bar.setCurrentIndex(index)

    def _goto_desktop(self, key: str) -> None:
        for index, (desktop_key, _label, _icon) in enumerate(DESKTOPS):
            if desktop_key == key:
                self._goto_index(index)
                return

    def _open_analysis_window(self, name: str) -> None:
        if name == "Trace":
            self._goto_desktop("trace")
        elif name == "Statistics":
            self.statistics_dock.show()
            self.act_toggle_stats.setChecked(True)
        elif name == "Write":
            self.write_dock.show()
            self.act_toggle_write.setChecked(True)
            self.write_window.focus_tab("CAPL")
        elif name == "Logging":
            self._show_status(
                "The logging block will write to .blf/.asc once a real engine "
                "is attached in Phase 2.")

    def _open_node_capl(self, node: NodeDef) -> None:
        if not node.capl_file:
            self._show_status(f"Node '{node.name}' is a hardware ECU — it has no CAPL file.")
            return
        path = self.workspace / node.capl_file
        self._goto_desktop("capl")
        if path.exists():
            self.capl_browser.open_path(path)
        else:
            self._show_status(
                f"File {node.capl_file} does not exist yet in {self.workspace} — "
                "create it with the 'New CAPL File' button.")

    # ==================================================================
    def _show_status(self, text: str) -> None:
        self.statusBar().showMessage(text, 6000)

    def _on_compile_finished(self, name: str, errors: int, warnings: int) -> None:
        level = "error" if errors else ("warning" if warnings else "success")
        self.write_window.log(
            f"Build {name}: {errors} error(s), {warnings} warning(s).", level, "CAPL")
        self.write_window.focus_tab("CAPL")

    def closeEvent(self, event) -> None:
        if self.capl_browser.has_unsaved():
            answer = QMessageBox.question(
                self, "Exit CANoe Fake",
                "There are unsaved CAPL files. Exit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.backend.stop()
        super().closeEvent(event)
