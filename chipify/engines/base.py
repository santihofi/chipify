# Copyright (c) 2026 Santiago Hofwimmer
"""
base.py – Abstract simulator-engine contract for Chipify.

An *engine* wraps one external circuit simulator (ngspice, VACASK, …). The
sweep orchestrator (:mod:`chipify.simulator`) never talks to a simulator
binary directly — it only calls the methods below, so adding support for a
new simulator means implementing this one class (see PLUGINS.md, section
"Simulator engine plugin", and :mod:`chipify.engines` for registration).

Contract
--------
``name``
    Registry key. This is the value users write in a datasheet's per-test
    ``engine:`` field and in the ``simulator_engine`` setting.
``netlist_ext``
    Extension of the netlist templates this engine produces/consumes
    (``.spice`` for ngspice, ``.sim`` for VACASK). Drives template
    persistence and ``--templates-dir`` re-run file naming.
``generate_test_template(test)``
    Produce the Jinja2-ready netlist template for one testbench (typically
    by driving xschem, see :func:`chipify.engines.xschem.run_xschem`). Runs
    once per testbench in the main process, before the sweep starts.
``run(netlist, timeout_sec, test, analysis_tab_paths)``
    Execute one rendered netlist. Runs inside a worker process; must be
    self-contained (no GUI, no shared state) and return
    ``(output_line, error_message)`` — exactly one of the two is set.
``stage_extra_files()``
    Optional hook: mirror engine-specific support files (e.g. OSDI compact
    models) into FAST_TMP before the sweep.
``run_log_tail(n_lines)``
    Optional: tail of the most recent ``run()``'s simulator log, used to
    attach a diagnostic to analysis-capture failures.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


def extract_error_line(log_text: str) -> str:
    """Pull the most relevant single line from a simulator log (best-effort).

    Prefers the first line mentioning an error / missing vector; otherwise the
    last non-empty line. Whitespace-collapsed and length-capped so it fits in a
    one-line result-row note / CSV cell.
    """
    lines = [ln.strip() for ln in log_text.splitlines() if ln.strip()]
    if not lines:
        return ""
    markers = ("error", "not available", "fatal", "can't", "cannot", "no such")
    pick = next((ln for ln in lines if any(m in ln.lower() for m in markers)), "")
    if not pick:
        pick = lines[-1]
    return " ".join(pick.split())[:200]


class BaseSimulator(ABC):
    """Abstract simulator engine interface for extensible backend support."""

    #: Registry key — the ``engine:`` value in datasheets and the
    #: ``simulator_engine`` setting. Must be unique, lowercase, non-empty.
    name: str = "base"

    #: Extension of the netlist templates this engine works with.
    netlist_ext: str = ".spice"

    #: Chipify engine-plugin API version (see plugin_loader versioning).
    api_version: str = "1"

    @abstractmethod
    def generate_test_template(self, test) -> str:
        """Return a rendered-ready Jinja2 netlist template string for *test*."""
        raise NotImplementedError

    @abstractmethod
    def run(self, netlist: str, timeout_sec: float = 10, test=None,
            analysis_tab_paths: dict | None = None):
        """Execute one netlist and return (output_line, error_message).

        netlist             – the fully rendered netlist text.
        timeout_sec         – wall-clock limit for the simulator process.
        test                – the Test object for the current testbench (optional;
                              used by VacaskSimulator to evaluate measure
                              expressions and to know which analyses to extract).
        analysis_tab_paths  – ``{Analysis.kind: tab_path}`` mapping where the
                              engine should write per-analysis waveform data.
                              ngspice ignores this (paths are baked into the
                              rendered netlist via Jinja2); VacaskSimulator
                              uses it to dump signals from the .raw file.
        """
        raise NotImplementedError

    def stage_extra_files(self) -> None:
        """Optional hook: stage engine-specific files into FAST_TMP before a
        sweep (called once per engine by ``stage_files_to_ram``)."""

    def run_log_tail(self, n_lines: int = 25) -> str:
        """Tail of the most recent ``run()``'s simulator log ('' if unknown).

        Used by the orchestrator to attach the engine's own error output to
        analysis-capture failure notes on the result row.
        """
        return ""

    @staticmethod
    def extract_error(log_text: str) -> str:
        """Most relevant single line of *log_text* (override for engines with
        distinctive log formats)."""
        return extract_error_line(log_text)
