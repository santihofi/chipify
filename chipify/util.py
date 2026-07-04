# Copyright (c) 2026 Santiago Hofwimmer
"""
util.py – Core domain objects and utilities for Chipify.

Classes
-------
Stimuli  – Loads a datasheet.yaml and builds the test plan.
Test     – A single testbench with its boundary specifications.
Value    – One measurement boundary (name, min, typ, max).

Functions
---------
get_num_cores()  – Returns a safe core count for multiprocessing.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import yaml


class Stimuli:
    """Parses a ``datasheet.yaml`` file into a test plan."""

    def __init__(self, yaml_file: str | os.PathLike[str] | None = None) -> None:
        self.params: dict[str, Any] = {}
        self.tests: list[Test] = []
        # Custom equations from the datasheet's top-level ``equations:`` /
        # ``transient_equations:`` blocks, as [{"name", "expr"}] dicts.
        self.equations: list[dict[str, str]] = []
        self.transient_equations: list[dict[str, str]] = []
        if yaml_file:
            self._load_from_yaml(yaml_file)

    def _load_from_yaml(self, file_path: str | os.PathLike[str]) -> None:
        """
        Load and validate the datasheet YAML.

        Delegates to ``schema.validate_datasheet`` which:
        - expands range-DSL strings (range(N), linspace(…), logspace(…))
          via a strict AST whitelist — no eval() involved.
        - validates structural correctness and reports precise error paths.
        """
        data = yaml.safe_load(Path(file_path).read_text(encoding="utf-8"))

        from chipify.schema import validate_datasheet, SchemaError
        try:
            validated = validate_datasheet(data or {})
        except SchemaError as exc:
            raise ValueError(f"Datasheet {file_path!r} schema error: {exc}") from exc

        self.params = validated.params
        self.tests = validated.tests
        self.equations = getattr(validated, "equations", [])
        self.transient_equations = getattr(validated, "transient_equations", [])

    def addTest(self, test: "Test") -> None:
        self.tests.append(test)


class Test:
    """A testbench entry with its measurement specifications."""

    def __init__(self, tb_path: str, value_lst: list["Value"]) -> None:
        self.tb_path: str = tb_path
        self.value_lst: list[Value] = value_lst
        # Rendered-ready Jinja2 netlist template, filled in by
        # simulator.generate_templates() before the sweep starts.
        self.template_str: str = ""
        # One Analysis instance per kind captured from this testbench.
        # Populated by schema.validate_datasheet() from transient_signals /
        # dc_signals / ac_signals YAML keys.
        from chipify.analyses import Analysis  # local import: avoid cycle
        self.analyses: list[Analysis] = []
        self.measure: dict[str, str] = {}
        # Per-testbench simulator engine ("ngspice"/"vacask"). None means
        # "inherit the run default"; schema.validate_datasheet() sets it from the
        # optional ``engine:`` key, and simulator.run_sim() resolves None to a
        # concrete name before dispatch.
        self.engine: str | None = None
        # Set by simulator.generate_templates() if this testbench's netlist could
        # not be produced (e.g. its engine is unavailable). The worker then fails
        # only this testbench's runs with this message, leaving others to run.
        self.template_error: str | None = None

    @property
    def transient_signals(self) -> list[str]:
        """Back-compat shim: signals of the TransientAnalysis if present."""
        return next((a.signals for a in self.analyses
                     if a.kind == "transient"), [])


class Value:
    """One measurement boundary specification."""

    def __init__(
        self,
        name: str,
        vmin: float | None,
        vmax: float | None,
        vtyp: float | None,
        unit: str | None = None,
    ) -> None:
        self.name = name
        self.vmin = vmin
        self.vmax = vmax
        self.vtyp = vtyp
        # Optional engineering unit (e.g. "V", "mV", "Hz", "dB"). Display-only:
        # surfaced in the Measurements table; never used in pass/fail math.
        self.unit = unit

    def isPass(self, val: float) -> bool:
        import math
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return False
        if self.vmin is not None and val < self.vmin:
            return False
        if self.vmax is not None and val > self.vmax:
            return False
        return True


def get_num_cores() -> int:
    """Return the number of cores available for simulation workers."""
    # os.sched_getaffinity is Linux-only; fall back to cpu_count elsewhere.
    # getattr (rather than a platform-specific ``# type: ignore``) keeps mypy
    # happy on both Linux and Windows.
    sched_getaffinity = getattr(os, "sched_getaffinity", None)
    if sched_getaffinity is not None:
        available_cores = len(sched_getaffinity(0))
    else:
        available_cores = os.cpu_count() or 1

    return max(1, available_cores - 1)
