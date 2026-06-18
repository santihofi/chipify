# Copyright (c) 2026 Santiago Hofwimmer
"""
tests/test_util_range_dsl.py

Unit tests for chipify.schema._parse_range_dsl.

Covers:
- range(N), range(a, b), range(a, b, step)
- linspace(start, stop, N)
- logspace(start, stop, N)
- Negative arguments
- Rejection of dangerous expressions (os.system, imports, attribute chains)
- Rejection of unknown function names
- Rejection of non-constant arguments
"""
from __future__ import annotations

import pytest
from chipify.schema import _parse_range_dsl, SchemaError, validate_parameters


# ── range() ───────────────────────────────────────────────────────────────────

def test_range_single_arg() -> None:
    result = _parse_range_dsl("range(5)")
    assert result == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_range_two_args() -> None:
    result = _parse_range_dsl("range(2, 7)")
    assert result == [2.0, 3.0, 4.0, 5.0, 6.0]


def test_range_three_args_step() -> None:
    result = _parse_range_dsl("range(0, 10, 2)")
    assert result == [0.0, 2.0, 4.0, 6.0, 8.0]


def test_range_negative_start() -> None:
    result = _parse_range_dsl("range(-3, 3)")
    assert result == [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0]


# ── linspace() ────────────────────────────────────────────────────────────────

def test_linspace_basic() -> None:
    result = _parse_range_dsl("linspace(0, 1, 5)")
    assert len(result) == 5
    assert result[0] == pytest.approx(0.0)
    assert result[-1] == pytest.approx(1.0)


def test_linspace_float_bounds() -> None:
    result = _parse_range_dsl("linspace(0.5, 1.5, 3)")
    assert result[0] == pytest.approx(0.5)
    assert result[2] == pytest.approx(1.5)


# ── logspace() ────────────────────────────────────────────────────────────────

def test_logspace_basic() -> None:
    result = _parse_range_dsl("logspace(0, 2, 3)")
    assert len(result) == 3
    assert result[0] == pytest.approx(1.0)     # 10^0 = 1
    assert result[2] == pytest.approx(100.0)    # 10^2 = 100


# ── Security: rejection of dangerous expressions ──────────────────────────────

def test_rejects_os_system() -> None:
    with pytest.raises(ValueError):
        _parse_range_dsl("os.system('rm -rf /')")


def test_rejects_import() -> None:
    with pytest.raises(ValueError):
        _parse_range_dsl("__import__('os')")


def test_rejects_attribute_access() -> None:
    with pytest.raises(ValueError):
        _parse_range_dsl("os.path.join('a', 'b')")


def test_rejects_unknown_function() -> None:
    with pytest.raises(ValueError):
        _parse_range_dsl("arange(10)")


def test_rejects_non_constant_arg() -> None:
    with pytest.raises(ValueError):
        _parse_range_dsl("range(n)")  # variable, not a literal


def test_rejects_binary_expression() -> None:
    with pytest.raises(ValueError):
        _parse_range_dsl("1 + 2")


def test_rejects_string_arg() -> None:
    with pytest.raises(ValueError):
        _parse_range_dsl("range('hello')")


# ── validate_parameters integration ──────────────────────────────────────────

def test_validate_parameters_expands_range() -> None:
    result = validate_parameters({"n_steps": "range(4)"})
    assert result["n_steps"] == [0.0, 1.0, 2.0, 3.0]


def test_validate_parameters_passes_list_unchanged() -> None:
    result = validate_parameters({"temp": [27, 85, 125]})
    assert result["temp"] == [27, 85, 125]


def test_validate_parameters_wraps_numeric_scalar() -> None:
    # Scalars must come back as one-element lists: generate_cases builds the
    # sweep grid with itertools.product, which crashes on a bare float.
    result = validate_parameters({"vdd": 1.8})
    assert result["vdd"] == [pytest.approx(1.8)]


def test_validate_parameters_wraps_string_scalar() -> None:
    # A bare string would otherwise be swept character by character.
    result = validate_parameters({"corner": "tt"})
    assert result["corner"] == ["tt"]


def test_validate_parameters_raises_on_unsafe_string() -> None:
    with pytest.raises(SchemaError):
        validate_parameters({"key": "os.system('bad')"})


# ── measurement bound validation ──────────────────────────────────────────────

def test_validate_datasheet_rejects_non_numeric_bound() -> None:
    from chipify.schema import validate_datasheet
    data = {
        "parameters": {"temp": [27]},
        "tests": {"tb_x": {"gain": {"min": "abc", "max": 80}}},
    }
    with pytest.raises(SchemaError, match="tb_x.gain"):
        validate_datasheet(data)


def test_validate_datasheet_allows_missing_bounds() -> None:
    from chipify.schema import validate_datasheet
    data = {
        "parameters": {"temp": [27]},
        "tests": {"tb_x": {"gain": {"min": 40}}},
    }
    stim = validate_datasheet(data)
    val = stim.tests[0].value_lst[0]
    assert val.vmin == 40.0 and val.vmax is None


def test_validate_datasheet_parses_optional_unit() -> None:
    from chipify.schema import validate_datasheet
    data = {
        "parameters": {"temp": [27]},
        "tests": {"tb_x": {
            "gain": {"min": 40, "unit": "dB"},
            "offset": {"max": 5},          # no unit → None
        }},
    }
    stim = validate_datasheet(data)
    gain, offset = stim.tests[0].value_lst
    assert gain.unit == "dB"
    assert offset.unit is None
