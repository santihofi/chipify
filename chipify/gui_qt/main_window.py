# Copyright (c) 2026 Santiago Hofwimmer
"""
main_window.py – Top-level QMainWindow shell for the Qt GUI.

Owns the shared :class:`AppState`, the left control panel (datasheet / run /
history controls), and the central tab area. Lifecycle logic lives in the
controllers (:mod:`chipify.gui_qt.controllers`); per-tab views live in
:mod:`chipify.gui_qt.tabs`. The window exposes a small, stable surface
(``show_results``, ``set_running_ui``, ``refresh_history`` …) that the
controllers call back into.
"""
from __future__ import annotations

import glob
import logging
import os

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chipify import __version__, app_config, settings
from chipify.gui.services import data_loader as _dl
from chipify.gui.services import equation_service as _eq_svc
from chipify.gui.state import AppState
from chipify.gui_qt import theme
from chipify.gui_qt.controllers.history_controller import HistoryController
from chipify.gui_qt.controllers.simulation_controller import SimulationController
from chipify.gui_qt.tabs.analytics_tab import AnalyticsTab
from chipify.gui_qt.tabs.equations_tab import EquationsTab
from chipify.gui_qt.tabs.histogram_tab import HistogramTab
from chipify.gui_qt.tabs.measurements_tab import MeasurementsTab
from chipify.gui_qt.tabs.transient_tab import TransientTab

log = logging.getLogger("chipify.gui_qt.main_window")

_LEFT_PANEL_WIDTH = 320


class MainWindow(QMainWindow):
    """Application shell: left control panel + central tab widget + status bar."""

    NO_DATASHEETS = "No files found"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Chipify EDA Dashboard")
        self.resize(1300, 950)

        #: Single source of truth, shared with controllers and tab views.
        self.app_state = AppState()
        self.theme_name = theme.load_theme_name()

        self.sim_controller = SimulationController(self)
        self.history_controller = HistoryController(self)

        self._build_ui()
        self.app_state.status_changed.connect(self._on_status_changed)

        # Populate selectors, then auto-load the last run once the loop is idle.
        self.refresh_datasheets()
        self.refresh_history()
        self.set_status(f"Chipify {__version__} — ready.")
        QTimer.singleShot(0, self.history_controller.auto_load_latest)
        log.debug("MainWindow constructed (theme=%s).", self.theme_name)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_left_panel())

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.measurements_tab = MeasurementsTab(self.app_state)
        self.histogram_tab = HistogramTab(self.app_state, self.plot_theme)
        self.analytics_tab = AnalyticsTab(self.app_state, self.plot_theme)
        self.transient_tab = TransientTab(self.app_state, self.plot_theme)
        self.equations_tab = EquationsTab(self.reapply_equations)
        self.tabs.addTab(self.measurements_tab, "Measurements")
        self.tabs.addTab(self.histogram_tab, "Histogram")
        self.tabs.addTab(self.analytics_tab, "Analytics")
        self.tabs.addTab(self.transient_tab, "Transient")
        self.tabs.addTab(self.equations_tab, "Equations")
        self._setup_plugin_tabs()
        root.addWidget(self.tabs, stretch=1)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))
        self._status_label = QLabel("")
        self.statusBar().addWidget(self._status_label)

    def _build_left_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("LeftPanel")
        panel.setFixedWidth(_LEFT_PANEL_WIDTH)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Chipify")
        title.setObjectName("Heading")
        layout.addWidget(title)
        subtitle = QLabel("Mismatch · sweeps · yield")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        # ── Datasheet selector ────────────────────────────────────────────────
        layout.addSpacing(6)
        layout.addWidget(QLabel("Datasheet"))
        ds_row = QHBoxLayout()
        ds_row.setSpacing(6)
        self.datasheet_combo = QComboBox()
        self.datasheet_combo.textActivated.connect(self._on_datasheet_changed)
        ds_row.addWidget(self.datasheet_combo, stretch=1)
        self.btn_refresh = QPushButton("↺")
        self.btn_refresh.setFixedWidth(36)
        self.btn_refresh.setToolTip("Rescan the datasheets folder")
        self.btn_refresh.clicked.connect(self.refresh_datasheets)
        ds_row.addWidget(self.btn_refresh)
        layout.addLayout(ds_row)

        # ── Run controls ──────────────────────────────────────────────────────
        layout.addSpacing(6)
        self.btn_start = QPushButton("Start Simulation")
        self.btn_start.setObjectName("Accent")
        self.btn_start.clicked.connect(self.sim_controller.start)
        layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("Stop Simulation")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.sim_controller.stop)
        layout.addWidget(self.btn_stop)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # ── History ───────────────────────────────────────────────────────────
        layout.addSpacing(12)
        layout.addWidget(QLabel("History"))
        hist_row = QHBoxLayout()
        hist_row.setSpacing(6)
        self.history_combo = QComboBox()
        self.history_combo.textActivated.connect(self.history_controller.on_select)
        hist_row.addWidget(self.history_combo, stretch=1)
        self.btn_annotate = QPushButton("✎")
        self.btn_annotate.setFixedWidth(36)
        self.btn_annotate.setToolTip("Edit notes / tags for the selected run")
        self.btn_annotate.clicked.connect(self.annotate_run)
        hist_row.addWidget(self.btn_annotate)
        layout.addLayout(hist_row)

        # ── Actions ───────────────────────────────────────────────────────────
        layout.addSpacing(12)
        self.btn_pdf = QPushButton("Export PDF Report")
        self.btn_pdf.clicked.connect(self.export_pdf)
        layout.addWidget(self.btn_pdf)
        self.btn_open_folder = QPushButton("Open Output Folder")
        self.btn_open_folder.clicked.connect(self.open_output_folder)
        layout.addWidget(self.btn_open_folder)
        self.btn_multiplot = QPushButton("Multi-Plot Dashboard")
        self.btn_multiplot.clicked.connect(self.open_multiplot)
        layout.addWidget(self.btn_multiplot)
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(self.open_settings)
        layout.addWidget(self.btn_settings)

        layout.addStretch(1)
        return panel

    # ── Plugin tabs ───────────────────────────────────────────────────────────

    def _setup_plugin_tabs(self) -> None:
        """Discover and host QtTabPlugins; warn about unsupported Tk ones."""
        from chipify.gui.services.plugin_context import PluginContext
        from chipify.gui_qt.services.main_thread import MainThreadInvoker
        from chipify.plugin_loader import (
            get_qt_tab_plugins,
            warn_unsupported_tab_plugins,
        )

        #: container QWidget → (plugin instance, PluginContext)
        self._plugin_tabs: dict = {}
        self._invoker = MainThreadInvoker(self)
        warn_unsupported_tab_plugins()

        for cls in get_qt_tab_plugins():
            name = str(getattr(cls, "name", "") or "").strip()
            if not name:
                continue
            container = QWidget()
            ctx = PluginContext(
                self.app_state,
                get_yaml_path=lambda: self.current_yaml_path,
                tk_after=self._invoker.after,
                set_status=self.set_status,
                plugin_name=name,
            )
            try:
                plugin = cls()
                plugin.build(container, ctx)
            except Exception as exc:  # noqa: BLE001
                log.exception("Qt tab plugin %r failed to build.", name)
                layout = container.layout() or QVBoxLayout(container)
                layout.addWidget(QLabel(f"Plugin '{name}' failed to load:\n{exc}"))
                self.tabs.addTab(container, name)
                continue
            self.tabs.addTab(container, name)
            self._plugin_tabs[container] = (plugin, ctx)

        self.app_state.data_changed.connect(self._notify_plugins_data_changed)
        self.tabs.currentChanged.connect(self._notify_plugin_on_show)

    def _notify_plugins_data_changed(self, **_kwargs) -> None:
        for plugin, ctx in self._plugin_tabs.values():
            try:
                plugin.on_data_changed(ctx)
            except Exception:  # noqa: BLE001
                log.exception("Qt tab plugin on_data_changed failed.")

    def _notify_plugin_on_show(self, index: int) -> None:
        entry = self._plugin_tabs.get(self.tabs.widget(index))
        if entry is not None:
            plugin, ctx = entry
            try:
                plugin.on_show(ctx)
            except Exception:  # noqa: BLE001
                log.exception("Qt tab plugin on_show failed.")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        for plugin, _ctx in getattr(self, "_plugin_tabs", {}).values():
            try:
                plugin.on_close()
            except Exception:  # noqa: BLE001
                log.exception("Qt tab plugin on_close failed.")
        super().closeEvent(event)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def plot_theme(self) -> dict:
        """Active matplotlib palette for the plot tabs."""
        return theme.plot_theme(self.theme_name)

    def apply_theme(self, name: str) -> None:
        """Switch the live theme: restyle the app and repaint the plots."""
        from PySide6.QtWidgets import QApplication
        self.theme_name = name
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.build_qss(name))
        # Re-emit so the plot tabs redraw with the new matplotlib palette.
        if self.app_state.current_df is not None:
            self.app_state.data_changed.emit(
                df=self.app_state.current_df,
                stim=self.app_state.current_stim,
                switch_tab=False,
            )

    # ── Actions ───────────────────────────────────────────────────────────────

    def open_settings(self) -> None:
        from chipify.gui_qt.widgets.settings_dialog import SettingsDialog
        SettingsDialog(self).exec()

    def open_multiplot(self) -> None:
        existing = getattr(self, "_multiplot", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        from chipify.gui_qt.multiplot_window import MultiPlotWindow
        self._multiplot = MultiPlotWindow(self.app_state, self.plot_theme)
        self._multiplot.show()

    def annotate_run(self) -> None:
        label = self.history_combo.currentText()
        if not label or label == "No runs found":
            return
        csv_path = _dl.resolve_csv_path(label, settings.OUT_DIR)
        if not csv_path:
            return
        from chipify.gui_qt.widgets.run_annotation_dialog import RunAnnotationDialog
        RunAnnotationDialog(self, label, csv_path).exec()
        self.refresh_history()

    def open_output_folder(self) -> None:
        os.makedirs(settings.OUT_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(settings.OUT_DIR))

    def export_pdf(self) -> None:
        df = self.app_state.current_df
        stim = self.app_state.current_stim
        if df is None or stim is None:
            QMessageBox.warning(self, "Export PDF", "No simulation data to export.")
            return
        self.set_status("Generating PDF report…", "yellow")
        try:
            from chipify import pdf_export
            path = pdf_export.generate_pdf_report(
                df, stim, self.current_yaml_path,
                os.path.join(settings.OUT_DIR, "reports"),
                sim_duration_sec=self.app_state.last_sim_duration_sec,
            )
        except Exception as exc:  # noqa: BLE001
            self.set_status("PDF export failed", "#e74c3c")
            QMessageBox.critical(self, "Export PDF", f"Failed to generate PDF:\n{exc}")
            return
        self.set_status("PDF saved to out/reports/", "#2ecc71")
        QMessageBox.information(self, "Export PDF", f"Report saved as:\n{os.path.basename(path)}")

    # ── Selectors ─────────────────────────────────────────────────────────────

    @property
    def current_yaml_path(self) -> str | None:
        """Absolute path of the selected datasheet, or None."""
        name = self.datasheet_combo.currentText()
        if not name or name == self.NO_DATASHEETS:
            return None
        return os.path.join(settings.IN_DIR, name)

    def refresh_datasheets(self) -> None:
        """Rescan the input folder for ``*.yaml`` / ``*.yml`` datasheets."""
        files = sorted(
            os.path.basename(p)
            for ext in ("*.yaml", "*.yml")
            for p in glob.glob(os.path.join(settings.IN_DIR, ext))
        )
        self.datasheet_combo.blockSignals(True)
        self.datasheet_combo.clear()
        self.datasheet_combo.addItems(files if files else [self.NO_DATASHEETS])
        self.datasheet_combo.blockSignals(False)

    def refresh_history(self, select_latest: bool = False) -> None:
        """Repopulate the history combo for the current datasheet."""
        self.history_controller.refresh(select_latest=select_latest)

    def _on_datasheet_changed(self, _text: str) -> None:
        self.refresh_history()

    # ── Results surface (called by controllers) ───────────────────────────────

    def show_results(self, df, stim, switch_tab: bool = False) -> None:
        """Install a result DataFrame into AppState and notify the views.

        Mirrors the legacy ``update_ui_results``: normalise ``sim_error``,
        (re)compute ``global_pass``, apply saved custom (scalar) equations so
        derived columns are available to every tab, publish to AppState, and
        emit ``data_changed``.
        """
        df = _dl.compute_global_pass(_dl.normalise_sim_error(df))
        equations = app_config.load_config().get("custom_equations", []) or []
        df, derived, _logs = _eq_svc.apply_scalar_equations(df, equations)
        self.app_state.derived_cols = derived

        self.app_state.partial_df = None
        self.app_state.simulation_active = False
        self.app_state.current_df = df
        self.app_state.current_stim = stim
        self.app_state.data_changed.emit(df=df, stim=stim, switch_tab=switch_tab)
        self.equations_tab.report_derived(derived)
        if switch_tab:
            self.tabs.setCurrentWidget(self.measurements_tab)

    def reapply_equations(self) -> None:
        """Re-run the current results through ``show_results`` to refresh
        derived columns after the equation list changes."""
        df = self.app_state.current_df
        if df is not None:
            self.show_results(df, self.app_state.current_stim, switch_tab=False)

    def show_error(self, message: str) -> None:
        """Surface a simulation error on the measurements tab."""
        self.measurements_tab.show_error(message)
        self.tabs.setCurrentWidget(self.measurements_tab)

    # ── Run-state UI ──────────────────────────────────────────────────────────

    def set_running_ui(self, running: bool) -> None:
        """Toggle controls between idle and running states."""
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_refresh.setEnabled(not running)
        self.datasheet_combo.setEnabled(not running)
        self.history_combo.setEnabled(not running)
        if not running:
            self.progress_bar.setValue(0)

    # ── Status bar ────────────────────────────────────────────────────────────

    def set_status(self, text: str, color: str | None = None) -> None:
        """Update the status-bar message (optionally with a colour override)."""
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"color: {color};" if color else "")

    def _on_status_changed(self, text: str = "", color: str = "") -> None:
        """Slot for ``AppState.status_changed`` (kwargs: text, color)."""
        self.set_status(text, color or None)
