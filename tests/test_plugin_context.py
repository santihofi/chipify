# Copyright (c) 2026 Santiago Hofwimmer
"""Tests for the TabPlugin interface: PluginContext facade + discovery.

PluginContext is tkinter-free by design (the Tk dependency is an injected
``after`` callable), so everything here runs headlessly.
"""
from __future__ import annotations

import json
import os
import textwrap
import threading

import pandas as pd
import pytest

from chipify import settings
from chipify.uikit.services.plugin_context import PluginContext, _jsonable
from chipify.uikit.state import AppState
from chipify.schema import validate_datasheet


def _make_stim():
    return validate_datasheet({
        "parameters": {"temp": [-40, 27, 100], "vincm": "linspace(0.6, 0.9, 4)"},
        "tests": {
            "tb_gain": {
                "ac_signals": ["out"],
                "gain": {"min": 40.0, "typ": 60.0, "max": 80.0},
                "measure": {"gbw": "gain * bandwidth"},
            },
        },
    })


def _make_ctx(state: AppState, yaml_path: str | None = None,
              after=None) -> PluginContext:
    return PluginContext(
        app_state=state,
        get_yaml_path=lambda: yaml_path,
        tk_after=after or (lambda _ms, fn: fn()),
        plugin_name="test-plugin",
    )


# ── specs() ───────────────────────────────────────────────────────────────────

def test_specs_structure_and_json_serializable() -> None:
    state = AppState()
    state.current_stim = _make_stim()
    ctx = _make_ctx(state, yaml_path="/proj/datasheets/corner.yaml")

    specs = ctx.specs()
    json.dumps(specs)  # must be serializable as-is (LLM payload use case)

    assert specs["datasheet"] == "corner.yaml"
    assert specs["parameters"]["temp"] == [-40, 27, 100]
    assert len(specs["parameters"]["vincm"]) == 4
    tb = specs["tests"]["tb_gain"]
    assert tb["measurements"]["gain"] == {"min": 40.0, "typ": 60.0, "max": 80.0}
    assert tb["signals"] == {"ac": ["out"]}
    assert tb["measure"] == {"gbw": "gain * bandwidth"}


def test_specs_without_data_is_empty_but_valid() -> None:
    ctx = _make_ctx(AppState())
    specs = ctx.specs()
    json.dumps(specs)
    assert specs == {"datasheet": None, "parameters": {}, "tests": {}}


def test_jsonable_handles_numpy_scalars() -> None:
    import numpy as np
    assert _jsonable(np.float64(1.5)) == 1.5
    assert _jsonable([np.int32(3), "x"]) == [3, "x"]


# ── results() / summary() ─────────────────────────────────────────────────────

def _result_df() -> pd.DataFrame:
    return pd.DataFrame({
        "run_id": ["000000", "000001", "000002"],
        "sim_error": ["None", "None", "tb_x: TIMEOUT"],
        "gain": [50.0, 90.0, float("nan")],
        "tb_gain_overall_pass": [True, False, False],
    })


def test_results_returns_isolated_copy() -> None:
    state = AppState()
    state.current_df = _result_df()
    ctx = _make_ctx(state)

    df = ctx.results()
    assert df is not None and len(df) == 3
    df.loc[0, "gain"] = -999.0          # mutate the copy
    df["evil"] = 1
    assert state.current_df.loc[0, "gain"] == 50.0
    assert "evil" not in state.current_df.columns


def test_results_valid_only_filters_errors() -> None:
    state = AppState()
    state.current_df = _result_df()
    ctx = _make_ctx(state)
    df = ctx.results(valid_only=True)
    assert df is not None and len(df) == 2


def test_results_none_without_data() -> None:
    assert _make_ctx(AppState()).results() is None


def test_summary() -> None:
    state = AppState()
    state.current_df = _result_df()
    ctx = _make_ctx(state)
    s = ctx.summary()
    assert s["total"] == 3 and s["crashes"] == 1 and s["valid"] == 2
    assert s["passed"] == 1
    assert s["yield_pct"] == pytest.approx(33.33, abs=0.01)


def test_summary_empty() -> None:
    assert _make_ctx(AppState()).summary()["total"] == 0


# ── datasheet text / netlists / testbench paths ───────────────────────────────

def test_datasheet_text_reads_file(tmp_path) -> None:
    p = tmp_path / "ds.yaml"
    p.write_text("# a comment\nparameters: {}\n", encoding="utf-8")
    ctx = _make_ctx(AppState(), yaml_path=str(p))
    assert "# a comment" in ctx.datasheet_text()
    assert ctx.datasheet_path == str(p)


def test_datasheet_text_empty_when_unset() -> None:
    assert _make_ctx(AppState()).datasheet_text() == ""


def test_netlists_from_template_str() -> None:
    state = AppState()
    stim = _make_stim()
    stim.tests[0].template_str = "* rendered netlist\n.end\n"
    state.current_stim = stim
    nls = _make_ctx(state).netlists()
    assert nls == {"tb_gain": "* rendered netlist\n.end\n"}


def test_netlists_fast_tmp_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "FAST_TMP", str(tmp_path))
    (tmp_path / "tb_gain.spice").write_text("* from disk\n", encoding="utf-8")
    state = AppState()
    state.current_stim = _make_stim()      # template_str is ""
    nls = _make_ctx(state).netlists()
    assert nls["tb_gain"] == "* from disk\n"


def test_testbench_paths_only_existing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "TB_DIR", str(tmp_path))
    (tmp_path / "tb_gain.sch").write_text("v {xschem}", encoding="utf-8")
    state = AppState()
    state.current_stim = _make_stim()
    paths = _make_ctx(state).testbench_paths()
    assert list(paths) == ["tb_gain"]
    assert os.path.isfile(paths["tb_gain"])


# ── history runs ──────────────────────────────────────────────────────────────

def test_history_runs_and_load_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OUT_DIR", str(tmp_path))
    _result_df().to_csv(tmp_path / "simulation_results.csv", index=False)
    hist = tmp_path / "history"
    hist.mkdir()
    _result_df().to_csv(hist / "run_20260611_120000.csv", index=False)
    (hist / "run_20260611_120000.meta.json").write_text(
        json.dumps({"schema_version": 1, "yaml": "corner.yaml"}),
        encoding="utf-8")

    ctx = _make_ctx(AppState())
    runs = ctx.history_runs()
    assert runs[0] == "Latest (simulation_results)"
    assert "run_20260611_120000.csv" in runs

    df = ctx.load_run("run_20260611_120000.csv")
    assert df is not None and "global_pass" in df.columns

    meta = ctx.run_meta("run_20260611_120000.csv")
    assert meta["yaml"] == "corner.yaml"
    assert ctx.load_run("does_not_exist.csv") is None
    assert ctx.run_meta("does_not_exist.csv") == {}


# ── waveforms ─────────────────────────────────────────────────────────────────

def test_waveforms_loads_per_run_csvs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "OUT_DIR", str(tmp_path))
    adir = tmp_path / "analysis_data" / "transient" / "20260611_120000"
    adir.mkdir(parents=True)
    pd.DataFrame({"time": [0.0, 1e-6], "v(out)": [0.0, 1.0]}).to_csv(
        adir / "run_000000__tb_gain.csv", index=False)

    state = AppState()
    state.current_df = _result_df()
    ctx = _make_ctx(state)

    assert ctx.analysis_kinds() == ["transient"]
    wf = ctx.waveforms("transient")           # defaults to all valid runs
    assert set(wf["run_id"]) == {"000000"}
    assert "v(out)" in wf.columns
    assert ctx.waveforms("ac").empty


# ── events / threading bridge ─────────────────────────────────────────────────

def test_subscribe_data_changed_swallows_plugin_errors() -> None:
    state = AppState()
    ctx = _make_ctx(state)
    calls: list[int] = []

    def bad_callback() -> None:
        calls.append(1)
        raise RuntimeError("plugin bug")

    ctx.subscribe_data_changed(bad_callback)
    state.data_changed.emit(df=None, stim=None, switch_tab=False)  # must not raise
    assert calls == [1]

    ctx.unsubscribe_all()
    state.data_changed.emit(df=None, stim=None, switch_tab=False)
    assert calls == [1]                       # no longer subscribed


def test_run_async_happy_and_error_paths() -> None:
    done = threading.Event()
    results: dict = {}

    ctx = _make_ctx(AppState(), after=lambda _ms, fn: fn())

    ctx.run_async(lambda: 21 * 2,
                  on_done=lambda r: (results.__setitem__("ok", r), done.set()))
    assert done.wait(5)
    assert results["ok"] == 42

    failed = threading.Event()
    ctx.run_async(lambda: 1 / 0,
                  on_done=lambda r: results.__setitem__("never", r),
                  on_error=lambda e: (results.__setitem__("err", type(e).__name__),
                                      failed.set()))
    assert failed.wait(5)
    assert results["err"] == "ZeroDivisionError"
    assert "never" not in results


def test_run_async_callback_errors_are_contained() -> None:
    done = threading.Event()
    ctx = _make_ctx(AppState(), after=lambda _ms, fn: fn())

    def exploding_on_done(_r) -> None:
        done.set()
        raise RuntimeError("UI bug in plugin")

    ctx.run_async(lambda: 1, on_done=exploding_on_done)  # must not propagate
    assert done.wait(5)


def test_set_status_noop_headless() -> None:
    _make_ctx(AppState()).set_status("hello")  # must not raise


# ── discovery ─────────────────────────────────────────────────────────────────

def test_tab_plugin_discovery(tmp_path, monkeypatch) -> None:
    from chipify import plugin_loader

    (tmp_path / "my_tab.py").write_text(textwrap.dedent("""
        from chipify.plugin_loader import TabPlugin

        class HelloTab(TabPlugin):
            name = "Hello Tab"
            def build(self, parent, context):
                pass

        class DuplicateTab(TabPlugin):
            name = "Hello Tab"          # same name -> must be skipped
            def build(self, parent, context):
                pass
    """), encoding="utf-8")

    monkeypatch.setenv("CHIPIFY_PLUGINS", str(tmp_path))
    plugin_loader.reload_plugins()
    try:
        tabs = plugin_loader.get_tab_plugins()
        names = [t.name for t in tabs]
        assert names.count("Hello Tab") == 1
        assert plugin_loader.list_plugins()["tab"] == [
            {"name": "Hello Tab", "api_version": "1"}]
    finally:
        plugin_loader.reload_plugins()      # don't leak tmp plugins to other tests
