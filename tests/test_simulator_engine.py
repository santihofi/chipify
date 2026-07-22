# Copyright (c) 2026 Santiago Hofwimmer
"""Tests for chipify.simulator case-evaluation and raw-file parsing.

Covers:
- _simulate_single_case_with_engine: measure: expressions on the MY_DATA
  path (works for ngspice now, not just VACASK), and the INVALID_OUTPUT
  count-mismatch guard.
- _parse_ascii_raw: indexed ASCII Values sections (the standard SPICE
  layout) and complex AC values.
- _staged_copy_is_stale: re-staging of edited model files.
"""
from __future__ import annotations

import math
import os

import pytest

simulator = pytest.importorskip("chipify.simulator")

# Alias: pytest must not try to collect chipify's Test domain class.
from chipify.util import Test as TbTest, Value  # noqa: E402


class _FakeEngine(simulator.BaseSimulator):
    """Engine stub returning a canned MY_DATA line (no subprocess)."""

    name = "fake"

    def __init__(self, output_line: str) -> None:
        self._output = output_line

    def generate_test_template(self, test) -> str:
        return ""

    def run(self, netlist, timeout_sec=10, test=None, analysis_tab_paths=None):
        return self._output, None


def _make_test(tb: str, value_names: list[str], measure: dict | None = None) -> TbTest:
    t = TbTest(tb, [Value(n, None, None, None) for n in value_names])
    t.template_str = "fake netlist"
    t.measure = measure or {}
    return t


# ── measure: expressions on the MY_DATA path ─────────────────────────────────

def test_measure_expressions_evaluated_from_scalars() -> None:
    test = _make_test("tb_gain", ["gain", "bandwidth"],
                      measure={"gbw": "gain * bandwidth"})
    engine = _FakeEngine("MY_DATA: 60.0 1e7")
    sample = simulator._simulate_single_case_with_engine(
        {"temp": 27}, [test], engine,
    )
    assert sample["gain"] == pytest.approx(60.0)
    assert sample["gbw"] == pytest.approx(6e8)
    assert sample["sim_error"] == "None"


def test_measure_can_reference_numeric_params() -> None:
    test = _make_test("tb_x", ["vout"], measure={"vratio": "vout / vdd"})
    engine = _FakeEngine("MY_DATA: 0.9")
    sample = simulator._simulate_single_case_with_engine(
        {"vdd": 1.8}, [test], engine,
    )
    assert sample["vratio"] == pytest.approx(0.5)


def test_measure_failure_records_nan_and_note() -> None:
    test = _make_test("tb_x", ["gain"], measure={"bad": "nonexistent + 1"})
    engine = _FakeEngine("MY_DATA: 42")
    sample = simulator._simulate_single_case_with_engine({}, [test], engine)
    assert math.isnan(sample["bad"])
    assert "bad" in sample["tb_x__measure_error"]
    # A broken derived measure must not fail the run itself.
    assert sample["sim_error"] == "None"


# ── INVALID_OUTPUT on value-count mismatch ────────────────────────────────────

def test_fewer_my_data_values_than_declared_is_an_error() -> None:
    test = _make_test("tb_x", ["gain", "bandwidth", "pm"])
    engine = _FakeEngine("MY_DATA: 60.0")
    sample = simulator._simulate_single_case_with_engine({}, [test], engine)
    assert "INVALID_OUTPUT" in sample["sim_error"]
    assert sample["tb_x_overall_pass"] is False
    assert math.isnan(sample["bandwidth"])
    assert sample["bandwidth_pass"] is False
    assert math.isnan(sample["pm"])


def test_exact_my_data_count_is_clean() -> None:
    test = _make_test("tb_x", ["a", "b"])
    engine = _FakeEngine("MY_DATA: 1 2")
    sample = simulator._simulate_single_case_with_engine({}, [test], engine)
    assert sample["sim_error"] == "None"
    assert sample["tb_x_overall_pass"] is True


# ── Per-testbench engine selection ────────────────────────────────────────────

def test_resolve_engine_name_precedence() -> None:
    t = _make_test("tb", ["x"])
    cfg_ng = {"simulator_engine": "ngspice"}
    # 1) per-testbench engine wins over everything
    t.engine = "vacask"
    assert simulator.resolve_engine_name(t, override="ngspice", cfg=cfg_ng) == "vacask"
    # 2) else the CLI override
    t.engine = None
    assert simulator.resolve_engine_name(t, override="vacask", cfg=cfg_ng) == "vacask"
    # 3) else the global setting
    assert simulator.resolve_engine_name(t, override=None, cfg={"simulator_engine": "vacask"}) == "vacask"
    # 4) else ngspice
    assert simulator.resolve_engine_name(t, override=None, cfg={}) == "ngspice"


def test_mixed_engines_select_per_testbench() -> None:
    ta = _make_test("tb_a", ["a"]); ta.engine = "ngspice"
    tb = _make_test("tb_b", ["b"]); tb.engine = "vacask"
    engines = {"ngspice": _FakeEngine("MY_DATA: 1"),
               "vacask": _FakeEngine("MY_DATA: 2")}
    used: dict[str, str] = {}

    def engine_for(test):
        used[test.tb_path] = test.engine
        return engines[test.engine]

    sample = simulator._simulate_single_case({}, [ta, tb], engine_for)
    assert used == {"tb_a": "ngspice", "tb_b": "vacask"}
    assert sample["a"] == pytest.approx(1.0)
    assert sample["b"] == pytest.approx(2.0)
    assert sample["sim_error"] == "None"


def test_unavailable_engine_fails_only_that_testbench() -> None:
    ok = _make_test("tb_ok", ["g"]); ok.engine = "ngspice"
    bad = _make_test("tb_bad", ["h"]); bad.engine = "vacask"

    def engine_for(test):
        if test.engine == "vacask":
            raise RuntimeError("PyOPUS not installed")
        return _FakeEngine("MY_DATA: 5")

    sample = simulator._simulate_single_case({}, [ok, bad], engine_for)
    assert sample["g"] == pytest.approx(5.0)
    assert sample["tb_ok_overall_pass"] is True
    assert math.isnan(sample["h"])
    assert sample["tb_bad_overall_pass"] is False
    assert "engine unavailable" in sample["sim_error"]


def test_template_error_fails_only_that_testbench() -> None:
    ok = _make_test("tb_ok", ["g"])
    bad = _make_test("tb_bad", ["h"])
    bad.template_error = "tb_bad: [vacask] netlist generation failed: boom"

    sample = simulator._simulate_single_case(
        {}, [ok, bad], lambda _t: _FakeEngine("MY_DATA: 7"),
    )
    assert sample["g"] == pytest.approx(7.0)
    assert math.isnan(sample["h"])
    assert "netlist generation failed" in sample["sim_error"]


def test_generate_templates_uses_per_test_extension(tmp_path) -> None:
    from chipify.util import Stimuli
    ng = _make_test("tb_ng", ["a"]); ng.engine = "ngspice"
    vc = _make_test("tb_vc", ["b"]); vc.engine = "vacask"
    stim = Stimuli()
    stim.tests = [ng, vc]
    # Pre-rendered templates: ngspice reads .spice, vacask reads .sim.
    (tmp_path / "tb_ng.spice").write_text("NG", encoding="utf-8")
    (tmp_path / "tb_vc.sim").write_text("VC", encoding="utf-8")
    simulator.generate_templates(stim, templates_dir=str(tmp_path))
    assert ng.template_str == "NG" and ng.template_error is None
    assert vc.template_str == "VC" and vc.template_error is None


def test_generate_templates_missing_file_isolates_failure(tmp_path) -> None:
    from chipify.util import Stimuli
    ok = _make_test("tb_ok", ["a"]); ok.engine = "ngspice"
    miss = _make_test("tb_miss", ["b"]); miss.engine = "ngspice"
    (tmp_path / "tb_ok.spice").write_text("OK", encoding="utf-8")
    stim = Stimuli()
    stim.tests = [ok, miss]
    simulator.generate_templates(stim, templates_dir=str(tmp_path))
    assert ok.template_str == "OK" and ok.template_error is None
    assert miss.template_str == ""
    assert "netlist generation failed" in (miss.template_error or "")


# ── Direct netlist import (per-testbench `source: netlist`) ──────────────────

def _use_tb_dir(monkeypatch, tmp_path) -> None:
    from chipify import settings
    monkeypatch.setattr(settings, "TB_DIR", str(tmp_path))


def _no_xschem(monkeypatch, module) -> None:
    def _boom(*_a, **_k):
        raise AssertionError("run_xschem must not run for an imported netlist")
    monkeypatch.setattr(module, "run_xschem", _boom)


def test_ngspice_import_netlist_skips_xschem_and_injects_capture(
    monkeypatch, tmp_path,
) -> None:
    from chipify.engines import ngspice as ng_mod
    _use_tb_dir(monkeypatch, tmp_path)
    _no_xschem(monkeypatch, ng_mod)

    # source="netlist" loads tb/<tb_path>.spice by convention.
    (tmp_path / "amp.spice").write_text(
        "V1 vdd 0 {{ vdd }}\n.control\ntran 1n 100n\n.endc\n", encoding="utf-8",
    )
    test = _make_test("amp", ["gain", "bw"])
    test.netlist_source = "netlist"

    out = ng_mod.NgspiceSimulator().generate_test_template(test)
    # Managed capture is injected exactly as for xschem output …
    assert "echo MY_DATA:$&gain $&bw" in out
    assert "set num_threads=1" in out
    # … while the imported deck's Jinja placeholder survives for the sweep.
    assert "{{ vdd }}" in out


def test_vacask_import_netlist_read_verbatim(monkeypatch, tmp_path) -> None:
    vc_mod = pytest.importorskip("chipify.engines.vacask")
    _use_tb_dir(monkeypatch, tmp_path)
    _no_xschem(monkeypatch, vc_mod)

    content = "* vacask deck\nsave all\ntran 1n 100n\n"
    (tmp_path / "amp.sim").write_text(content, encoding="utf-8")
    test = _make_test("amp", ["gain"])
    test.netlist_source = "netlist"

    out = vc_mod.VacaskSimulator().generate_test_template(test)
    assert out == content


def test_generate_templates_missing_import_isolates_failure(
    monkeypatch, tmp_path,
) -> None:
    from chipify.util import Stimuli
    from chipify.engines import ngspice as ng_mod
    _use_tb_dir(monkeypatch, tmp_path)
    _no_xschem(monkeypatch, ng_mod)

    (tmp_path / "tb_ok.spice").write_text(
        "* ok\n.control\ntran 1n 1u\n.endc\n", encoding="utf-8",
    )
    ok = _make_test("tb_ok", ["a"]); ok.engine = "ngspice"
    ok.netlist_source = "netlist"
    miss = _make_test("tb_miss", ["b"]); miss.engine = "ngspice"
    miss.netlist_source = "netlist"   # tb_miss.spice is absent
    stim = Stimuli()
    stim.tests = [ok, miss]

    simulator.generate_templates(stim)
    assert "echo MY_DATA:$&a" in ok.template_str and ok.template_error is None
    assert miss.template_str == ""
    assert "netlist generation failed" in (miss.template_error or "")


def test_template_render_error_fails_only_that_testbench() -> None:
    """A StrictUndefined render error (e.g. param-name typo in the testbench)
    must fail that testbench's row — not blow up the whole worker batch."""
    ok = _make_test("tb_ok", ["g"])
    bad = _make_test("tb_bad", ["h"])
    bad.template_str = "{{ undefined_variable }}"

    sample = simulator._simulate_single_case(
        {}, [ok, bad], lambda _t: _FakeEngine("MY_DATA: 7"),
    )
    assert sample["g"] == pytest.approx(7.0)
    assert math.isnan(sample["h"])
    assert "TEMPLATE_RENDER_ERROR" in sample["sim_error"]


def test_engine_exception_fails_only_that_testbench() -> None:
    """A plugin engine that raises from run() is contained per-testbench."""

    class _Boom(simulator.BaseSimulator):
        name = "boom"

        def generate_test_template(self, test) -> str:
            return ""

        def run(self, netlist, timeout_sec=10, test=None, analysis_tab_paths=None):
            raise RuntimeError("kaput")

    ok = _make_test("tb_ok", ["g"])
    bad = _make_test("tb_bad", ["h"])
    by_tb = {"tb_ok": _FakeEngine("MY_DATA: 7"), "tb_bad": _Boom()}

    sample = simulator._simulate_single_case(
        {}, [ok, bad], lambda t: by_tb[t.tb_path],
    )
    assert sample["g"] == pytest.approx(7.0)
    assert math.isnan(sample["h"])
    assert "ENGINE_ERROR" in sample["sim_error"]
    assert "kaput" in sample["sim_error"]


def test_unparsable_my_data_token_records_nan() -> None:
    """A non-numeric MY_DATA token is failed data, not a silently absent column."""
    test = _make_test("tb_x", ["gain", "bw"])
    engine = _FakeEngine("MY_DATA: abc 2.0")
    sample = simulator._simulate_single_case_with_engine({}, [test], engine)
    assert math.isnan(sample["gain"])
    assert sample["gain_pass"] is False
    assert sample["bw"] == pytest.approx(2.0)
    assert "INVALID_OUTPUT" in sample["sim_error"]
    assert sample["tb_x_overall_pass"] is False


# ── sim_timeout_sec resolution ────────────────────────────────────────────────

def test_resolve_sim_timeout() -> None:
    assert simulator._resolve_sim_timeout({}) == 10.0
    assert simulator._resolve_sim_timeout({"sim_timeout_sec": 120}) == 120.0
    assert simulator._resolve_sim_timeout({"sim_timeout_sec": "abc"}) == 10.0
    assert simulator._resolve_sim_timeout({"sim_timeout_sec": -5}) == 10.0


# ── ASCII .raw parsing ────────────────────────────────────────────────────────

def _write_ascii_raw(path, *, flags: str, varlines: list[str], values: str,
                     n_points: int) -> None:
    n_vars = len(varlines)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("Title: t\nDate: now\nPlotname: Transient Analysis\n")
        fh.write(f"Flags: {flags}\n")
        fh.write(f"No. Variables: {n_vars}\nNo. Points: {n_points}\n")
        fh.write("Variables:\n")
        for line in varlines:
            fh.write(line + "\n")
        fh.write("Values:\n")
        fh.write(values)


def test_parse_ascii_raw_with_point_indices(tmp_path) -> None:
    """Standard SPICE ASCII layout: each point starts with its index token."""
    raw = tmp_path / "t.raw"
    _write_ascii_raw(
        raw, flags="real", n_points=3,
        varlines=["\t0\ttime\ttime", "\t1\tv(out)\tvoltage"],
        values=(
            " 0\t0.0\n\t1.0\n"
            " 1\t0.5\n\t2.0\n"
            " 2\t1.0\n\t3.0\n"
        ),
    )
    parsed = simulator._parse_ascii_raw(str(raw))
    assert list(parsed["time"]) == pytest.approx([0.0, 0.5, 1.0])
    assert list(parsed["v(out)"]) == pytest.approx([1.0, 2.0, 3.0])


def test_parse_ascii_raw_without_indices(tmp_path) -> None:
    """Writers that omit the per-point index still parse correctly."""
    raw = tmp_path / "t.raw"
    _write_ascii_raw(
        raw, flags="real", n_points=2,
        varlines=["\t0\ttime\ttime", "\t1\tv(out)\tvoltage"],
        values="0.0 1.0\n0.5 2.0\n",
    )
    parsed = simulator._parse_ascii_raw(str(raw))
    assert list(parsed["time"]) == pytest.approx([0.0, 0.5])
    assert list(parsed["v(out)"]) == pytest.approx([1.0, 2.0])


def test_parse_ascii_raw_complex_values(tmp_path) -> None:
    """AC analyses write complex values as 're,im' pairs."""
    raw = tmp_path / "t.raw"
    _write_ascii_raw(
        raw, flags="complex", n_points=2,
        varlines=["\t0\tfrequency\tfrequency", "\t1\tv(out)\tvoltage"],
        values=(
            " 0\t1.0,0.0\n\t0.5,0.5\n"
            " 1\t10.0,0.0\n\t0.1,0.2\n"
        ),
    )
    parsed = simulator._parse_ascii_raw(str(raw))
    assert parsed["v(out)"][0] == pytest.approx(0.5 + 0.5j)
    assert parsed["v(out)"][1] == pytest.approx(0.1 + 0.2j)
    assert parsed["frequency"][1] == pytest.approx(10.0 + 0.0j)


# ── stage_files_to_ram freshness check ───────────────────────────────────────

def test_staged_copy_is_stale(tmp_path) -> None:
    src = tmp_path / "models.lib"
    dest = tmp_path / "staged.lib"
    src.write_text("v1", encoding="utf-8")

    assert simulator._staged_copy_is_stale(str(src), str(dest))  # missing dest

    import shutil
    shutil.copy2(str(src), str(dest))
    assert not simulator._staged_copy_is_stale(str(src), str(dest))

    # Edit the source: newer mtime + different size → stale again.
    src.write_text("v2 edited", encoding="utf-8")
    os.utime(str(src), (os.path.getmtime(str(dest)) + 5,) * 2)
    assert simulator._staged_copy_is_stale(str(src), str(dest))
