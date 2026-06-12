# Copyright (c) 2026 Santiago Hofwimmer
"""Built-in plot plugins: registration, user override, and draw smoke test."""
import textwrap

import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure

from chipify import plugin_loader
from chipify.plot_plugins import BUILTIN_PLOT_PLUGINS
from chipify.util import Value

_BUILTIN_NAMES = {"QQ Plot (Normality)", "ECDF + Spec Limits", "Yield vs Spec Curve"}


@pytest.fixture
def isolated_plugin_dir(tmp_path, monkeypatch):
    """Point plugin discovery at an empty tmp dir; restore cache afterwards."""
    monkeypatch.setenv("CHIPIFY_PLUGINS", str(tmp_path))
    plugin_loader.reload_plugins()
    yield tmp_path
    plugin_loader.reload_plugins()


def _stim():
    class _Test:
        pass

    class _Stim:
        pass

    t = _Test()
    t.value_lst = [Value("gain_db", 38.0, None, 41.0),
                   Value("offset_mv", -5.0, 5.0, 0.0)]
    t.measure = {}
    s = _Stim()
    s.tests = [t]
    return s


def _df(n=100):
    rng = np.random.default_rng(7)
    return pd.DataFrame({
        "gain_db": rng.normal(41.0, 1.2, n),
        "offset_mv": rng.normal(0.0, 2.0, n),
        "sim_error": "None",
    })


def test_builtins_registered(isolated_plugin_dir):
    plugins = plugin_loader.get_plot_plugins()
    assert {p.name for p in plugins} >= _BUILTIN_NAMES
    assert plugins[: len(BUILTIN_PLOT_PLUGINS)] == BUILTIN_PLOT_PLUGINS


def test_user_plugin_overrides_builtin(isolated_plugin_dir):
    (isolated_plugin_dir / "my_qq.py").write_text(textwrap.dedent("""
        from chipify.plugin_loader import PlotPlugin

        class MyQQ(PlotPlugin):
            name = "QQ Plot (Normality)"

            def draw(self, fig, ax, valid_df, stim, *, theme=None):
                pass
    """), encoding="utf-8")
    plugin_loader.reload_plugins()
    plugins = plugin_loader.get_plot_plugins()
    matches = [p for p in plugins if p.name == "QQ Plot (Normality)"]
    assert len(matches) == 1
    assert matches[0] not in BUILTIN_PLOT_PLUGINS  # user plugin won


@pytest.mark.parametrize("cls", BUILTIN_PLOT_PLUGINS, ids=lambda c: c.name)
def test_builtin_draw_smoke(cls):
    fig = Figure()
    ax = fig.add_subplot(111)
    cls().draw(fig, ax, _df(), _stim(), theme=None)
    assert len(fig.axes) == 2  # one grid panel per measurement


@pytest.mark.parametrize("cls", BUILTIN_PLOT_PLUGINS, ids=lambda c: c.name)
def test_builtin_draw_handles_empty(cls):
    fig = Figure()
    ax = fig.add_subplot(111)
    cls().draw(fig, ax, _df(0).iloc[0:0], _stim(), theme=None)  # must not raise
