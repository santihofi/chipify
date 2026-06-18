# Copyright (c) 2026 Santiago Hofwimmer
"""
Offscreen smoke tests for the PySide6 GUI (chipify.gui_qt).

Run headlessly via the ``offscreen`` Qt platform (set below before any Qt
import). Skipped automatically if PySide6 is not installed.
"""
from __future__ import annotations

import os

import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeVal:
    def __init__(self, name, vmin=None, vmax=None, unit=None):
        self.name = name
        self.vmin = vmin
        self.vmax = vmax
        self.unit = unit


class _FakeTest:
    def __init__(self, values):
        self.value_lst = values


class _FakeStim:
    def __init__(self):
        self.tests = [_FakeTest([_FakeVal("gain", 9.0, 11.0, unit="dB")])]
        self.params = {}


def _sample_df():
    return pd.DataFrame({
        "gain": [10.0, 10.2, 8.5, 10.1],          # one out-of-spec (< vmin 9.0)
        "gain_pass": [True, True, False, True],   # one failure
        "sim_error": ["None", "None", "None", "None"],
    })


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def window(qt_app):
    from chipify.gui_qt.main_window import MainWindow
    win = MainWindow()
    yield win
    win.close()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_window_constructs(window):
    assert window.windowTitle() == "Chipify EDA Dashboard"
    assert window.tabs.count() >= 1
    assert window.tabs.tabText(0) == "Datasheet Editor"


def test_theme_qss_builds_for_all_themes():
    from chipify.gui_qt import theme
    for name in theme.available_themes():
        qss = theme.build_qss(name)
        assert "QPushButton" in qss and theme.ACCENT in qss


def test_show_results_populates_measurements(window):
    window.show_results(_sample_df(), _FakeStim(), switch_tab=True)
    tree = window.measurements_tab.tree
    assert tree.topLevelItemCount() == 1
    item = tree.topLevelItem(0)
    assert item.text(0) == "gain"
    assert item.text(1) == "dB"              # optional unit column
    assert item.text(9) == "FAIL"           # one failing run
    assert "gain" in window.measurements_tab.status_label.text()

    # The out-of-spec failing run shows up under Worst Cases.
    worst = window.measurements_tab.worst_tree
    assert worst.topLevelItemCount() == 1
    assert worst.topLevelItem(0).text(0) == "gain"
    assert worst.topLevelItem(0).text(2).startswith("<")   # violated lower bound


def test_measurement_rows_service():
    from chipify.uikit.services import measurements as meas
    rows = meas.measurement_rows(_sample_df(), _FakeStim())
    assert len(rows) == 1
    r = rows[0]
    assert r.name == "gain" and r.status == "FAIL" and r.fail_n == 1
    assert r.unit == "dB"                    # carried through from the Value
    assert r.cpk_str not in ("-", "")        # finite spread → numeric Cpk


def test_measurements_equation_results(window, monkeypatch):
    from chipify import app_config
    monkeypatch.setattr(
        app_config, "load_config",
        lambda: {"custom_equations": [{"name": "gain_x2", "expr": "gain * 2"}]},
    )
    window.show_results(_sample_df(), _FakeStim(), switch_tab=False)
    et = window.measurements_tab.eq_tree
    names = [et.topLevelItem(i).text(0) for i in range(et.topLevelItemCount())]
    assert "gain_x2" in names
    row = next(et.topLevelItem(i) for i in range(et.topLevelItemCount())
               if et.topLevelItem(i).text(0) == "gain_x2")
    assert row.text(1) == "gain * 2"         # expression column


def test_histogram_latex_export(window, tmp_path, monkeypatch):
    from chipify import settings
    from chipify.gui_qt.services import latex_export
    monkeypatch.setattr(settings, "OUT_DIR", str(tmp_path))
    monkeypatch.setattr(latex_export.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(latex_export.QMessageBox, "critical", lambda *a, **k: None)

    window.show_results(_sample_df(), _FakeStim(), switch_tab=False)
    h = window.histogram_tab
    h.param_combo.setCurrentText("gain")
    h._export_latex()

    out = tmp_path / "latex"
    assert (out / "gain_plot.tex").exists()
    assert (out / "gain_plot.csv").exists()


def test_transient_latex_export_no_data_is_graceful(window, monkeypatch):
    # With no loaded data the overlay export must warn, not raise.
    from chipify.gui_qt.services import latex_export
    seen = {}
    monkeypatch.setattr(latex_export.QMessageBox, "information",
                        lambda *a, **k: seen.setdefault("info", a))
    window.transient_tab._export_latex()
    assert "info" in seen


def test_plot_tabs_present(window):
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert titles == ["Datasheet Editor", "Measurements", "Histogram",
                      "Analytics", "Transient"]
    # Equations editor is embedded as the editor's third column, not a tab.
    assert window.editor_tab.equations_panel is window.equations_tab


def test_transient_tab_empty_state(window):
    """No waveform CSVs on disk → the tab must render its empty-state safely."""
    window.show_results(_sample_df(), _FakeStim(), switch_tab=False)
    tt = window.transient_tab
    tt._redraw()                              # transient kind, no data
    tt.kind_combo.setCurrentText("DC Sweep")  # exercises the dc plotter path
    tt._redraw()
    tt.kind_combo.setCurrentText("Bode")      # exercises the ac/bode path
    tt._redraw()
    assert tt.canvas.figure.axes               # an axes was drawn each time


def test_histogram_and_analytics_redraw(window):
    window.show_results(_sample_df(), _FakeStim(), switch_tab=False)

    # Option lists populated from the loaded data.
    assert window.histogram_tab.param_combo.findText("gain") >= 0

    # Histogram renders without error and produces axes.
    window.histogram_tab._redraw()
    assert window.histogram_tab.canvas.figure.axes
    assert "Cpk" in window.histogram_tab.kpi_label.text()

    # Analytics: default pie already drawn; force the interactive scatter mode.
    at = window.analytics_tab
    at.mode_combo.blockSignals(True)
    at.mode_combo.setCurrentText("Scatter Plot")
    at.mode_combo.blockSignals(False)
    at._apply_mode_visibility()
    at._repopulate_options(window.app_state.active_df, window.app_state.current_stim)
    at._redraw()
    assert at._sc_plot is not None          # scatter artist created for hover


def test_equations_tab_applies_derived_column(window, monkeypatch):
    from chipify import app_config
    store = {"custom_equations": []}
    monkeypatch.setattr(app_config, "load_config", lambda: dict(store))
    monkeypatch.setattr(app_config, "save_config", lambda cfg: store.update(cfg))

    window.show_results(_sample_df(), _FakeStim(), switch_tab=False)
    eq = window.equations_tab
    eq.mode_combo.setCurrentText("Scalar")
    eq._append_row("gain2", "gain * 2")
    eq._apply()

    df = window.app_state.current_df
    assert "gain2" in df.columns
    assert df["gain2"].iloc[0] == df["gain"].iloc[0] * 2
    assert "gain2" in window.app_state.derived_cols
    # Derived column shows up as a histogram parameter option.
    assert window.histogram_tab.param_combo.findText("gain2") >= 0


def test_deferred_runs_on_next_tick(qt_app):
    """`deferred` must not run inline (so a combo popup can close first)."""
    from chipify.gui_qt.widgets.helpers import deferred
    calls = []
    slot = deferred(lambda x: calls.append(x))
    slot(42)
    assert calls == []                      # not synchronous
    for _ in range(10):
        qt_app.processEvents()
        if calls:
            break
    assert calls == [42]                    # ran on a later event-loop tick


def test_qss_excludes_complex_widgets_and_palette_builds(qt_app):
    """QComboBox/QSpinBox must be themed via the palette, not QSS, so their
    sub-controls (popups, spin arrows) keep working under Fusion."""
    from PySide6.QtGui import QColor, QPalette
    from chipify.gui_qt import theme
    for mode in theme.available_themes():
        qss = theme.build_qss(mode)
        assert "QComboBox" not in qss
        assert "QSpinBox" not in qss
        pal = theme.build_palette(mode)
        assert pal.color(QPalette.Base) == QColor(theme.palette(mode)["input_bg"])


def test_compact_combo_bounds_width(qt_app):
    """A compact combo must not widen to its longest item (Wayland surface
    overflow regression)."""
    from PySide6.QtWidgets import QComboBox
    from chipify.gui_qt.widgets.helpers import compact_combo
    combo = QComboBox()
    compact_combo(combo, length=8)
    combo.addItem("x")
    combo.addItem("a really really really long history run label.csv")
    assert combo.sizeHint().width() < 220


def test_datasheet_editor_loads_and_saves(qt_app, tmp_path, monkeypatch):
    import yaml as _yaml

    from chipify import settings
    monkeypatch.setattr(settings, "IN_DIR", str(tmp_path))
    ds = tmp_path / "demo.yaml"
    ds.write_text(
        "parameters:\n  temp: [27, 85]\n"
        "tests:\n  tb_sf:\n    gain:\n      min: 0.8\n      max: 1.0\n",
        encoding="utf-8",
    )

    from chipify.gui_qt.main_window import MainWindow
    win = MainWindow()
    try:
        win.set_active_datasheet("demo.yaml")
        ed = win.editor_tab
        assert ed.current_yaml_path == str(ds)
        # Form populated from the file.
        assert any(v["key"].get() == "temp" for v in ed.param_vars)
        assert ed.test_vars and ed.test_vars[0]["tb_name"].get() == "tb_sf"

        # Edit a measurement bound and set an optional unit, then save.
        ed.test_vars[0]["values"][0]["vmax"]._w.setText("1.5")
        ed.test_vars[0]["values"][0]["unit"]._w.setText("V")
        ed._save()
        reloaded = _yaml.safe_load(ds.read_text())
        assert reloaded["tests"]["tb_sf"]["gain"]["max"] == 1.5
        assert reloaded["tests"]["tb_sf"]["gain"]["unit"] == "V"
    finally:
        win.close()


def test_run_summary_updates(window):
    window.show_results(_sample_df(), _FakeStim(), switch_tab=False)
    assert window.sum_samples.text() == "4"
    assert window.sum_valid.text() == "4"
    assert "%" in window.sum_yield.text()      # yield rendered


def test_font_size_setting_persists_and_applies(window, monkeypatch):
    from chipify import app_config
    from chipify.gui_qt.widgets.settings_dialog import SettingsDialog
    store = {"theme": "night", "font_size": 13}
    monkeypatch.setattr(app_config, "load_config", lambda: dict(store))
    monkeypatch.setattr(app_config, "save_config", lambda cfg: store.update(cfg))

    dlg = SettingsDialog(window)
    dlg.font_spin.setValue(16)
    dlg._save()
    assert store["font_size"] == 16


def test_dashboard_histogram_has_compare(qt_app, monkeypatch):
    from chipify import app_config
    monkeypatch.setattr(app_config, "load_config", lambda: {})
    monkeypatch.setattr(app_config, "save_config", lambda _cfg: None)
    from chipify.gui_qt.multiplot_window import PlotCell
    cell = PlotCell(AppState_for_cell(), lambda: _night_theme(), lambda _c: None)
    try:
        cell.mode_combo.setCurrentText("Histogram")
        cell._apply_mode_visibility()
        # group, fit (dist), compare and zoom are all available for histogram cells.
        assert cell.compare_combo.isVisibleTo(cell)
        assert cell.group_combo.isVisibleTo(cell)
        assert cell.dist_combo.isVisibleTo(cell)
        assert cell.zoom_check.isVisibleTo(cell)
        assert "compare" in cell.get_config()
        assert "zoom" in cell.get_config()
        # Zoom round-trips through config.
        cell.apply_config({"mode": "Histogram", "zoom": True})
        assert cell.zoom_check.isChecked()
    finally:
        cell.deleteLater()


def _night_theme():
    from chipify.gui_qt import theme
    return theme.plot_theme("night")


def AppState_for_cell():
    from chipify.uikit.state import AppState
    return AppState()


def test_apply_theme_switches_palette(window):
    window.apply_theme("light")
    assert window.theme_name == "light"
    assert window.plot_theme()["bg"] == "white"


def test_settings_dialog_saves_and_applies_theme(window, monkeypatch):
    from chipify import app_config
    from chipify.gui_qt.widgets.settings_dialog import SettingsDialog
    store = {"theme": "night", "simulator_engine": "ngspice"}
    monkeypatch.setattr(app_config, "load_config", lambda: dict(store))
    monkeypatch.setattr(app_config, "save_config", lambda cfg: store.update(cfg))

    dlg = SettingsDialog(window)
    dlg.theme_combo.setCurrentText("dark")
    dlg.engine_combo.setCurrentText("vacask")
    dlg._save()

    assert store["theme"] == "dark"
    assert store["simulator_engine"] == "vacask"
    assert window.theme_name == "dark"


def test_left_panel_actions_exist(window):
    for attr in ("btn_settings", "btn_pdf", "btn_open_folder", "btn_annotate",
                 "btn_multiplot"):
        assert hasattr(window, attr)


def test_multiplot_dashboard(window, monkeypatch):
    from chipify import app_config
    monkeypatch.setattr(app_config, "load_config", lambda: {})
    monkeypatch.setattr(app_config, "save_config", lambda _cfg: None)

    window.show_results(_sample_df(), _FakeStim(), switch_tab=False)
    from chipify.gui_qt.multiplot_window import MultiPlotWindow
    mp = MultiPlotWindow(window.app_state, window.plot_theme)
    try:
        assert len(mp._cells) == 1            # one default cell when none saved
        cell = mp._cells[0]
        cell.mode_combo.setCurrentText("Histogram")
        mp.refresh_all()
        assert cell.canvas.figure.axes

        mp._add_cell({"mode": "Scatter Plot"})
        assert len(mp._cells) == 2
        assert mp._cells[1].get_config()["mode"] == "Scatter Plot"
    finally:
        mp.close()


def test_figure_export_uses_exporter(window, monkeypatch, tmp_path):
    from chipify.gui_qt.services import figure_export
    out = tmp_path / "hist.png"
    monkeypatch.setattr(
        figure_export.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "PNG (*.png)")),
    )
    window.show_results(_sample_df(), _FakeStim(), switch_tab=False)
    window.histogram_tab._redraw()
    window.histogram_tab._export()
    assert out.exists() and out.stat().st_size > 0


def test_qt_tab_plugin_loads_and_receives_data(qt_app, tmp_path, monkeypatch):
    import textwrap

    from chipify import plugin_loader

    (tmp_path / "run_counter.py").write_text(textwrap.dedent('''
        from PySide6.QtWidgets import QLabel, QVBoxLayout
        from chipify.plugin_loader import QtTabPlugin

        class RunCounter(QtTabPlugin):
            name = "Run Counter"
            def build(self, parent, context):
                self._lbl = QLabel("no data", parent)
                QVBoxLayout(parent).addWidget(self._lbl)
            def on_data_changed(self, context):
                df = context.results()
                self._lbl.setText(f"{0 if df is None else len(df)} runs")
    '''), encoding="utf-8")
    monkeypatch.setenv("CHIPIFY_PLUGINS", str(tmp_path))
    plugin_loader.reload_plugins()

    from chipify.gui_qt.main_window import MainWindow
    win = MainWindow()
    try:
        titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        assert "Run Counter" in titles
        win.show_results(_sample_df(), _FakeStim(), switch_tab=False)
        plugin = next(p for p, _ in win._plugin_tabs.values())
        assert "4 runs" in plugin._lbl.text()
    finally:
        win.close()
        plugin_loader.reload_plugins()


def test_histogram_themed_frame_and_legend(window):
    """Regression: figure frame must be themed (not white) and the histogram
    must render a legend."""
    window.show_results(_sample_df(), _FakeStim(), switch_tab=False)
    window.histogram_tab._redraw()
    fig = window.histogram_tab.canvas.figure
    r, g, b, _a = fig.get_facecolor()
    assert (r, g, b) != (1.0, 1.0, 1.0)      # not the default white frame
    assert r < 0.5 and g < 0.5 and b < 0.5   # dark (night theme)
    assert fig.axes[0].get_legend() is not None


def test_simulation_worker_end_to_end(window, monkeypatch):
    """Mock run_sim and drive the QThread worker → AppState → table path."""
    from chipify import app_config, simulator, util
    from chipify.gui_qt.workers import sim_worker

    df = _sample_df()
    fake_stim = _FakeStim()

    def fake_run_sim(stim, progress_callback=None, chunk_callback=None, **_kw):
        for i in range(1, 4):
            progress_callback(i, 3)
        if chunk_callback is not None:
            chunk_callback(df.iloc[:2].copy())
        return df.copy()

    monkeypatch.setattr(simulator, "run_sim", fake_run_sim)
    monkeypatch.setattr(util, "Stimuli", lambda _p: fake_stim)
    monkeypatch.setattr(sim_worker.SimWorker, "_persist", lambda *a, **k: None)
    monkeypatch.setattr(app_config, "is_live_plotting_enabled", lambda: True)

    window.datasheet_combo.blockSignals(True)
    window.datasheet_combo.clear()
    window.datasheet_combo.addItem("fake.yaml")
    window.datasheet_combo.blockSignals(False)

    loop = QEventLoop()
    window.app_state.data_changed.connect(lambda **_k: loop.quit())
    timed_out = {"v": False}

    def _on_timeout():
        timed_out["v"] = True
        loop.quit()

    QTimer.singleShot(8000, _on_timeout)
    window.sim_controller.start()
    loop.exec()

    assert not timed_out["v"], "worker did not finish within timeout"
    assert window.app_state.current_df is not None
    assert window.app_state.last_sim_duration_sec is not None
    assert window.measurements_tab.tree.topLevelItemCount() == 1
    # Buttons returned to idle state.
    assert window.btn_start.isEnabled() and not window.btn_stop.isEnabled()
