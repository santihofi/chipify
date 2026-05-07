"""
tests/test_yaml_editor_service.py

Unit tests for chipify.gui.services.yaml_editor_service.

Covers:
- get_params_dict: recognised key variants, falls back to ('params', {})
- get_tests_dict: recognised key variants, normalises 'values' sub-block
- gui_repr_param: string wrapping, pass-through for DSL/numeric strings
"""
from __future__ import annotations

import pytest
from chipify.gui.services.yaml_editor_service import (
    get_params_dict,
    get_tests_dict,
    gui_repr_param,
)


# ── get_params_dict ───────────────────────────────────────────────────────────

def test_get_params_dict_canonical_key() -> None:
    data = {"params": {"vdd": 1.8, "temp": [27, 85]}}
    key, d = get_params_dict(data)
    assert key == "params"
    assert d["vdd"] == 1.8


def test_get_params_dict_alternative_key() -> None:
    data = {"parameters": {"a": 1}}
    key, d = get_params_dict(data)
    assert key == "parameters"
    assert d["a"] == 1


def test_get_params_dict_missing() -> None:
    key, d = get_params_dict({})
    assert d == {}


def test_get_params_dict_non_dict_value() -> None:
    data = {"params": "not a dict"}
    key, d = get_params_dict(data)
    assert d == {}


def test_get_params_dict_non_dict_input() -> None:
    key, d = get_params_dict(None)  # type: ignore[arg-type]
    assert d == {}


# ── get_tests_dict ────────────────────────────────────────────────────────────

def test_get_tests_dict_canonical_key() -> None:
    data = {"tests": {"tb.cir": {"gain": {"min": 10}}}}
    key, d = get_tests_dict(data)
    assert key == "tests"
    assert "gain" in d["tb.cir"]


def test_get_tests_dict_alternative_key() -> None:
    data = {"testbenches": {"tb.cir": {}}}
    key, d = get_tests_dict(data)
    assert key == "testbenches"


def test_get_tests_dict_normalises_values_subkey() -> None:
    """The legacy 'values' sub-key is flattened into the testbench dict."""
    data = {
        "tests": {
            "tb.cir": {
                "values": {"gain": {"min": 10, "max": 40}}
            }
        }
    }
    key, d = get_tests_dict(data)
    # 'values' should be removed and its contents merged
    assert "values" not in d["tb.cir"]
    assert "gain" in d["tb.cir"]


def test_get_tests_dict_missing() -> None:
    key, d = get_tests_dict({})
    assert d == {}


# ── gui_repr_param ────────────────────────────────────────────────────────────

def test_gui_repr_param_range_string() -> None:
    assert gui_repr_param("range(10)") == "range(10)"


def test_gui_repr_param_numpy_string() -> None:
    assert gui_repr_param("np.linspace(0, 1, 5)") == "np.linspace(0, 1, 5)"


def test_gui_repr_param_numeric_string() -> None:
    assert gui_repr_param("1.8") == "1.8"


def test_gui_repr_param_plain_string_gets_quoted() -> None:
    result = gui_repr_param("typical")
    assert result == "'typical'"


def test_gui_repr_param_non_string() -> None:
    assert gui_repr_param(1.8) == "1.8"
    assert gui_repr_param([1, 2]) == "[1, 2]"
