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
from typing import Any
import yaml


class Stimuli:
    """Parses a ``datasheet.yaml`` file into a test plan."""

    def __init__(self, yaml_file: str | None = None) -> None:
        self.params: dict[str, Any] = {}
        self.tests: list[Test] = []
        if yaml_file:
            self._load_from_yaml(yaml_file)

    def _load_from_yaml(self, file_path: str) -> None:
        """
        Load and validate the datasheet YAML.

        Delegates to ``schema.validate_datasheet`` which:
        - expands range-DSL strings (range(N), linspace(…), logspace(…))
          via a strict AST whitelist — no eval() involved.
        - validates structural correctness and reports precise error paths.
        """
        with open(file_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        from chipify.schema import validate_datasheet, SchemaError
        try:
            validated = validate_datasheet(data or {})
        except SchemaError as exc:
            raise ValueError(f"Datasheet {file_path!r} schema error: {exc}") from exc

        self.params = validated.params
        self.tests = validated.tests

    def addTest(self, test: "Test") -> None:
        self.tests.append(test)


class Test:
    """A testbench entry with its measurement specifications."""

    def __init__(self, tb_path: str, value_lst: list["Value"]) -> None:
        self.tb_path: str = tb_path
        self.value_lst: list[Value] = value_lst
        self.template: str = ""
        self.transient_signals: list[str] = []
        self.measure: dict[str, str] = {}


class Value:
    """One measurement boundary specification."""

    def __init__(
        self,
        name: str,
        vmin: float | None,
        vmax: float | None,
        vtyp: float | None,
    ) -> None:
        self.name = name
        self.vmin = vmin
        self.vmax = vmax
        self.vtyp = vtyp

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
    try:
        available_cores = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except AttributeError:
        available_cores = os.cpu_count() or 1

    return max(1, available_cores - 1)
