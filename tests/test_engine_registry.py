# Copyright (c) 2026 Santiago Hofwimmer
"""Tests for the chipify.engines registry (modular simulator-engine support).

Covers built-in resolution, programmatic registration, drop-in plugin-file
discovery (the ``CHIPIFY_PLUGINS`` mechanism shared with GUI plugins), the
netlist-extension lookup used by template persistence, and the warn-and-
fallback behavior of the legacy ``simulator.get_simulator_engine`` wrapper.
"""
from __future__ import annotations

import textwrap

import pytest

engines = pytest.importorskip("chipify.engines")
simulator = pytest.importorskip("chipify.simulator")


# ── Built-ins ─────────────────────────────────────────────────────────────────

def test_builtin_names_registered() -> None:
    names = engines.engine_names()
    assert "ngspice" in names and "vacask" in names
    assert simulator.SUPPORTED_ENGINES == ("ngspice", "vacask")


def test_get_engine_resolves_builtins() -> None:
    from chipify.engines.ngspice import NgspiceSimulator
    from chipify.engines.vacask import VacaskSimulator
    assert isinstance(engines.get_engine("ngspice"), NgspiceSimulator)
    # Name matching is case/whitespace-insensitive.
    assert isinstance(engines.get_engine("  VACASK "), VacaskSimulator)


def test_netlist_extension_lookup() -> None:
    assert engines.netlist_extension("ngspice") == ".spice"
    assert engines.netlist_extension("vacask") == ".sim"
    # Unknown names fall back to .spice so display/export never hard-fails.
    assert engines.netlist_extension("no_such_engine") == ".spice"


def test_unknown_engine_raises() -> None:
    with pytest.raises(engines.UnknownEngineError):
        engines.get_engine("no_such_engine")


def test_get_simulator_engine_falls_back_with_warning(caplog) -> None:
    """The legacy wrapper keeps workers alive on a typo'd setting, loudly."""
    with caplog.at_level("WARNING", logger="chipify.simulator"):
        eng = simulator.get_simulator_engine("no_such_engine")
    assert eng.name == "ngspice"
    assert any("Unknown simulator engine" in r.getMessage()
               for r in caplog.records)


# ── Programmatic registration ─────────────────────────────────────────────────

def test_register_engine_programmatically() -> None:
    @engines.register_engine
    class DummyEngine(engines.BaseSimulator):
        name = "dummy_prog"
        netlist_ext = ".dmy"

        def generate_test_template(self, test) -> str:
            return "* dummy"

        def run(self, netlist, timeout_sec=10, test=None, analysis_tab_paths=None):
            return "MY_DATA: 1", None

    try:
        assert "dummy_prog" in engines.engine_names()
        assert isinstance(engines.get_engine("dummy_prog"), DummyEngine)
        assert engines.netlist_extension("dummy_prog") == ".dmy"
    finally:
        engines._registered.pop("dummy_prog", None)


def test_register_engine_requires_name() -> None:
    class NoName(engines.BaseSimulator):
        def generate_test_template(self, test) -> str:
            return ""

        def run(self, netlist, timeout_sec=10, test=None, analysis_tab_paths=None):
            return "", None

    # Inherits name="base", which is reserved.
    with pytest.raises(ValueError):
        engines.register_engine(NoName)


def test_engine_selector_caches_instances() -> None:
    selector = engines.engine_selector()

    class _T:
        engine = "ngspice"

    a, b = selector(_T()), selector(_T())
    assert a is b  # one instance per engine name per selector


# ── Drop-in plugin-file discovery ─────────────────────────────────────────────

_PLUGIN_SRC = textwrap.dedent(
    """
    from chipify.engines import BaseSimulator

    class FakeXyceEngine(BaseSimulator):
        name = "fakexyce"
        netlist_ext = ".cir"

        def generate_test_template(self, test):
            return "* netlist"

        def run(self, netlist, timeout_sec=10, test=None, analysis_tab_paths=None):
            return "MY_DATA: 42", None
    """
)


def test_plugin_file_engine_discovered(tmp_path, monkeypatch) -> None:
    (tmp_path / "my_engine.py").write_text(_PLUGIN_SRC, encoding="utf-8")
    monkeypatch.setenv("CHIPIFY_PLUGINS", str(tmp_path))
    engines.reload_engines()
    try:
        assert "fakexyce" in engines.engine_names()
        eng = engines.get_engine("fakexyce")
        assert eng.run("* n")[0] == "MY_DATA: 42"
        assert engines.netlist_extension("fakexyce") == ".cir"

        # Datasheet validation accepts the plugin engine name.
        from chipify.schema import validate_datasheet
        stim = validate_datasheet(
            {"tests": {"tb_a": {"engine": "fakexyce", "gain": {"min": 0}}}}
        )
        assert stim.tests[0].engine == "fakexyce"
    finally:
        engines.reload_engines()


def test_plugin_cannot_shadow_builtin(tmp_path, monkeypatch) -> None:
    shadow = textwrap.dedent(
        """
        from chipify.engines import BaseSimulator

        class EvilNgspice(BaseSimulator):
            name = "ngspice"

            def generate_test_template(self, test):
                return ""

            def run(self, netlist, timeout_sec=10, test=None, analysis_tab_paths=None):
                return "", None
        """
    )
    (tmp_path / "shadow.py").write_text(shadow, encoding="utf-8")
    monkeypatch.setenv("CHIPIFY_PLUGINS", str(tmp_path))
    engines.reload_engines()
    try:
        from chipify.engines.ngspice import NgspiceSimulator
        assert isinstance(engines.get_engine("ngspice"), NgspiceSimulator)
    finally:
        engines.reload_engines()
