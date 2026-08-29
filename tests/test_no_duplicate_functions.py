# Copyright (c) 2026 Santiago Hofwimmer
"""Guard against the same function being written twice in two modules.

Copies drift: `_param_plugin_modes` existed byte-identically in two tabs, and
run-selection existed three times with two different vocabularies, so a
datasheet and the GUI could disagree about which runs a plot covered. This
turns that audit into something the suite re-runs for free.
"""
from __future__ import annotations

import ast
import collections
import pathlib

import pytest

#: Names that are legitimately defined in more than one module, with why.
_ALLOWED: dict[str, str] = {
    # Console-script entry points: one for the CLI, one for the GUI.
    "main": "separate entry points (cli.py, gui_qt/app.py)",
    # Same name, deliberately different behaviour: the measurements table wants
    # "-" for a missing value, the hover tooltip wants the raw text back.
    "fmt_value": "measurements table vs scatter hover have different contracts",
}

_ROOT = pathlib.Path(__file__).resolve().parent.parent / "chipify"


def _module_level_functions() -> dict[str, list[str]]:
    found: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted(_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        except SyntaxError as exc:  # pragma: no cover - would fail elsewhere too
            pytest.fail(f"{path} does not parse: {exc}")
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                found[node.name].append(
                    f"{path.relative_to(_ROOT.parent).as_posix()}:{node.lineno}")
    return found


def test_no_function_name_is_defined_in_two_modules():
    duplicates = {
        name: locations
        for name, locations in _module_level_functions().items()
        if len(locations) > 1 and name not in _ALLOWED
    }
    assert not duplicates, (
        "Module-level functions defined in more than one file:\n"
        + "\n".join(f"  {n}: {', '.join(locs)}" for n, locs in sorted(duplicates.items()))
        + "\n\nMove the shared one into a service both callers import, or add it "
          "to _ALLOWED with the reason the copies are genuinely different."
    )


def test_allowlist_entries_are_still_real_duplicates():
    """A stale allowlist hides nothing but does mislead the next reader."""
    found = _module_level_functions()
    stale = [name for name in _ALLOWED if len(found.get(name, [])) < 2]
    assert not stale, f"_ALLOWED entries no longer duplicated: {stale}"
