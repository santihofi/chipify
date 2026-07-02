# Copyright (c) 2026 Santiago Hofwimmer
"""Tests for the hardened ng2vc converter resolution/invocation
(chipify.engines.vacask).

ng2vc (ngspice→VACASK netlist converter) is an external tool absent on CI, so we
exercise the resolution + invocation logic against tiny fake ng2vc scripts and a
synthetic VACASK install layout. No real vacask/pyopus needed.
"""
from __future__ import annotations

import os
import sys

import pytest

vacask = pytest.importorskip("chipify.engines.vacask")


# ── fake ng2vc scripts (two CLI conventions) ──────────────────────────────────

# Form A: `ng2vc <in> <out>` writes the .sim itself (errors without 2 args).
_FAKE_NG2VC_FILE = (
    "import sys\n"
    "if len(sys.argv) != 3: sys.stderr.write('need <in> <out>\\n'); sys.exit(2)\n"
    "data = open(sys.argv[1]).read()\n"
    "open(sys.argv[2], 'w').write('* converted\\n' + data)\n"
)

# Form B: `ng2vc <in>` writes the netlist to stdout (errors if given an out arg).
_FAKE_NG2VC_STDOUT = (
    "import sys\n"
    "if len(sys.argv) != 2: sys.stderr.write('usage: ng2vc <in>\\n'); sys.exit(2)\n"
    "data = open(sys.argv[1]).read()\n"
    "sys.stdout.write('* converted\\n' + data)\n"
)

# A converter that always fails — to check the error is surfaced.
_FAKE_NG2VC_BROKEN = "import sys\nsys.stderr.write('boom: bad netlist\\n')\nsys.exit(1)\n"


def _write(path, text) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return str(path)


@pytest.fixture
def spice_in(tmp_path) -> str:
    return _write(tmp_path / "tb.spice", "* netlist\nR1 a b 1k\n.end\n")


# ── _resolve_ng2vc / discovery ────────────────────────────────────────────────

def test_explicit_setting_wins(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(vacask.shutil, "which", lambda _n: None)
    cfg = {"ng2vc_binary": str(tmp_path / "custom_ng2vc.py")}
    assert vacask._resolve_ng2vc(cfg) == str(tmp_path / "custom_ng2vc.py")


def test_discovers_on_path(monkeypatch, tmp_path) -> None:
    found = _write(tmp_path / "ng2vc.py", "x")
    monkeypatch.setattr(vacask.shutil, "which",
                        lambda n: found if n == "ng2vc.py" else None)
    assert vacask._resolve_ng2vc({"ng2vc_binary": ""}) == found


def test_discovers_vacask_lib_layout(monkeypatch, tmp_path) -> None:
    """Binary at <prefix>/bin/vacask, converter at <prefix>/vacask/lib/vacask/python/."""
    monkeypatch.setattr(vacask.shutil, "which", lambda _n: None)  # nothing on PATH
    bindir = tmp_path / "bin"
    bindir.mkdir()
    vacask_bin = _write(bindir / "vacask", "#!/bin/sh\n")
    pydir = tmp_path / "vacask" / "lib" / "vacask" / "python"
    pydir.mkdir(parents=True)
    ng2vc = _write(pydir / "ng2vc.py", "x")

    cfg = {"ng2vc_binary": "", "vacask_binary": vacask_bin}
    assert vacask._resolve_ng2vc(cfg) == ng2vc


def test_resolve_none_when_nothing_found(monkeypatch) -> None:
    monkeypatch.setattr(vacask.shutil, "which", lambda _n: None)
    assert vacask._resolve_ng2vc({"ng2vc_binary": "", "vacask_binary": "vacask"}) is None


def test_argv0_python_vs_native() -> None:
    assert vacask._ng2vc_argv0("/x/ng2vc.py") == [sys.executable, "/x/ng2vc.py"]
    assert vacask._ng2vc_argv0("/x/ng2vc") == ["/x/ng2vc"]


# ── _run_ng2vc invocation (both conventions) ──────────────────────────────────

def _patch_cfg(monkeypatch, ng2vc_path: str) -> None:
    monkeypatch.setattr(vacask.app_config, "load_config",
                        lambda: {"ng2vc_binary": ng2vc_path})
    # No real PyOPUS converter should hijack the script path.
    monkeypatch.setitem(sys.modules, "pyopus", None)


def test_run_uses_output_file_form(monkeypatch, tmp_path, spice_in) -> None:
    ng2vc = _write(tmp_path / "ng2vc.py", _FAKE_NG2VC_FILE)
    _patch_cfg(monkeypatch, ng2vc)
    sim_file = str(tmp_path / "tb.sim")
    vacask._run_ng2vc(spice_in, sim_file)
    assert os.path.isfile(sim_file)
    assert "* converted" in open(sim_file, encoding="utf-8").read()


def test_run_falls_back_to_stdout_form(monkeypatch, tmp_path, spice_in) -> None:
    ng2vc = _write(tmp_path / "ng2vc.py", _FAKE_NG2VC_STDOUT)
    _patch_cfg(monkeypatch, ng2vc)
    sim_file = str(tmp_path / "tb.sim")
    vacask._run_ng2vc(spice_in, sim_file)
    assert os.path.isfile(sim_file)
    assert "* converted" in open(sim_file, encoding="utf-8").read()


def test_run_surfaces_real_error(monkeypatch, tmp_path, spice_in) -> None:
    ng2vc = _write(tmp_path / "ng2vc.py", _FAKE_NG2VC_BROKEN)
    _patch_cfg(monkeypatch, ng2vc)
    with pytest.raises(RuntimeError, match="boom: bad netlist"):
        vacask._run_ng2vc(spice_in, str(tmp_path / "tb.sim"))


def test_run_not_found_lists_searched_paths(monkeypatch, tmp_path, spice_in) -> None:
    monkeypatch.setattr(vacask.app_config, "load_config",
                        lambda: {"ng2vc_binary": "", "vacask_binary": "vacask"})
    monkeypatch.setattr(vacask.shutil, "which", lambda _n: None)
    monkeypatch.setitem(sys.modules, "pyopus", None)
    with pytest.raises(RuntimeError, match="ng2vc converter not found"):
        vacask._run_ng2vc(spice_in, str(tmp_path / "tb.sim"))
