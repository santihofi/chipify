# Copyright (c) 2026 Santiago Hofwimmer
"""
schema.py – TypedDicts and validation helpers for the Chipify datasheet YAML.

TypedDicts define the expected structure of a parsed datasheet.yaml so that
editors and mypy can provide type-checked access to the data.

``validate_datasheet(data)`` is the single entry-point: it converts a raw
``yaml.safe_load()`` dict into validated Python objects, raising ``SchemaError``
with a precise error path on any structural or semantic problem.

Note: The heavy model classes (Stimuli, Test, Value) still live in util.py.
schema.py imports from util to build those objects; util.py must NOT import
from schema.py to avoid circular imports.
"""
from __future__ import annotations

import ast
from typing import Any

import numpy as np


# ── Exceptions ────────────────────────────────────────────────────────────────

class SchemaError(ValueError):
    """Raised when a datasheet.yaml violates the expected schema."""


def _supported_engines() -> tuple[str, ...]:
    """Valid per-testbench ``engine:`` values, from the engine registry.

    ``chipify.engines`` is import-light (no simulator modules are loaded just
    to list names), so datasheet validation stays cheap while still accepting
    drop-in engine plugins. Falls back to the built-in pair if the registry
    can't load for any reason.
    """
    try:
        from chipify.engines import engine_names
        return engine_names()
    except Exception:
        return ("ngspice", "vacask")


# ── Allowed range DSL functions ───────────────────────────────────────────────

_ALLOWED_CALLS: dict[str, Any] = {
    "range": range,
    "linspace": np.linspace,
    "logspace": np.logspace,
}


def _parse_range_dsl(value: str) -> list[float]:
    """
    Parse a YAML parameter value that encodes a sequence via a safe DSL.

    Allowed forms
    -------------
    - ``range(N)``                 → list(range(N))
    - ``range(start, stop)``       → list(range(start, stop))
    - ``range(start, stop, step)`` → list(range(start, stop, step))
    - ``linspace(start, stop, N)`` → list of N evenly spaced floats
    - ``logspace(start, stop, N)`` → list of N log-spaced floats

    Any other expression is rejected with ValueError (no eval() is used).

    Parameters
    ----------
    value:
        The raw string from the YAML file, e.g. ``"range(10)"`` or
        ``"linspace(0, 1, 5)"``.

    Returns
    -------
    list[float]
        Evaluated sequence as a Python list.

    Raises
    ------
    ValueError
        If the expression is not one of the allowed forms, uses unsupported
        node types, or contains non-numeric arguments.
    """
    try:
        tree = ast.parse(value.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Syntax error in range DSL {value!r}: {exc}") from exc

    body = tree.body
    if not isinstance(body, ast.Call):
        raise ValueError(
            f"Range DSL {value!r}: top-level must be a function call "
            f"(range, linspace, logspace)."
        )

    # Resolve function name
    func_node = body.func
    if not isinstance(func_node, ast.Name):
        raise ValueError(
            f"Range DSL {value!r}: function must be a plain name, not an attribute."
        )
    func_name = func_node.id
    if func_name not in _ALLOWED_CALLS:
        raise ValueError(
            f"Range DSL {value!r}: function {func_name!r} is not allowed. "
            f"Use one of: {sorted(_ALLOWED_CALLS)!r}"
        )

    # No keyword args (starred args are rejected by the constant-only
    # argument check below).
    if body.keywords:
        raise ValueError(f"Range DSL {value!r}: keyword arguments are not supported.")

    # Extract numeric arguments — only constants allowed
    args: list[float | int] = []
    for i, arg in enumerate(body.args):
        if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)):
            args.append(arg.value)
        elif isinstance(arg, ast.UnaryOp) and isinstance(arg.op, ast.USub):
            # Allow negation of constants: range(-5, 5)
            inner = arg.operand
            if isinstance(inner, ast.Constant) and isinstance(inner.value, (int, float)):
                args.append(-inner.value)
            else:
                raise ValueError(
                    f"Range DSL {value!r}: argument {i} is not a numeric constant."
                )
        else:
            raise ValueError(
                f"Range DSL {value!r}: argument {i} is not a numeric constant."
            )

    # Call the allowed function
    fn = _ALLOWED_CALLS[func_name]
    try:
        if func_name == "range":
            int_args = [int(a) for a in args]
            result = list(fn(*int_args))
        else:  # linspace / logspace return numpy arrays
            result = fn(*args).tolist()
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Range DSL {value!r}: failed to evaluate {func_name}({args!r}): {exc}"
        ) from exc

    if not isinstance(result, list):
        result = list(result)
    return [float(x) if not isinstance(x, float) else x for x in result]


def _parse_scalar_value(raw: Any) -> float | None:
    """Convert a YAML scalar (str/int/float/None) to float or None.

    Raises SchemaError for values that are present but not numeric, so a typo
    like ``min: abc`` fails loudly instead of silently dropping the bound.
    """
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"expected a number, got {raw!r}") from exc


def validate_parameters(params_raw: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and normalise the ``parameters:`` block.

    Sequences expressed as range-DSL strings are expanded here. Scalars
    (numbers and non-DSL strings) are wrapped in one-element lists so that
    every parameter value is a sweepable sequence — ``generate_cases`` builds
    the case grid with ``itertools.product``, which would otherwise crash on
    a bare number or silently sweep a bare string character by character.

    Returns a dict mapping parameter names to lists of values.
    Raises SchemaError on malformed entries.
    """
    result: dict[str, Any] = {}
    for key, value in params_raw.items():
        if not isinstance(key, str):
            raise SchemaError(f"Parameter key must be a string, got {key!r}")
        if isinstance(value, str):
            # Only attempt DSL parsing for strings that look like function calls
            stripped = value.strip()
            if stripped and stripped[0].isalpha() and "(" in stripped:
                try:
                    result[key] = _parse_range_dsl(stripped)
                except ValueError as exc:
                    raise SchemaError(f"Parameter {key!r}: {exc}") from exc
            else:
                result[key] = [value]
        elif isinstance(value, list):
            result[key] = value
        else:
            result[key] = [value]
    return result


def validate_datasheet(data: dict[str, Any]) -> "Any":  # returns util.Stimuli
    """
    Build and return a validated ``util.Stimuli`` object from a raw YAML dict.

    This is the authoritative entry-point for loading a datasheet.yaml.
    It replaces the ad-hoc parsing in ``Stimuli._load_from_yaml``.

    Raises
    ------
    SchemaError
        On structural violations (wrong types, missing required keys, bad
        range-DSL expressions).
    """
    from chipify.util import Stimuli, Test, Value  # local import to avoid circular dep

    if not isinstance(data, dict):
        raise SchemaError(f"Datasheet root must be a mapping, got {type(data).__name__}.")

    stim = Stimuli()

    # ── Parameters ────────────────────────────────────────────────────────────
    params_raw: dict[str, Any] = {}
    for key in ("parameters", "params", "sweep"):
        if key in data and isinstance(data[key], dict):
            params_raw = data[key]
            break

    stim.params = validate_parameters(params_raw)

    # ── Tests / Testbenches ───────────────────────────────────────────────────
    tests_raw: dict[str, Any] = {}
    for key in ("tests", "testbenches", "measurements"):
        if key in data and isinstance(data[key], dict):
            tests_raw = data[key]
            break

    from chipify.analyses import SCHEMA_KEY_TO_CLASS, Analysis

    for tb_path, measurements in tests_raw.items():
        if not isinstance(measurements, dict):
            continue

        analyses: list[Analysis] = []
        measure: dict[str, str] = {}
        engine: str | None = None
        value_lst: list[Value] = []

        for val_name, bounds in measurements.items():
            if val_name in SCHEMA_KEY_TO_CLASS:
                if isinstance(bounds, list) and bounds:
                    cls = SCHEMA_KEY_TO_CLASS[val_name]
                    analyses.append(cls(signals=[str(s) for s in bounds]))
                continue

            if val_name == "measure":
                if isinstance(bounds, dict):
                    measure = {k: str(v) for k, v in bounds.items()}
                continue

            if val_name == "engine":
                if bounds is not None:
                    eng = str(bounds).strip().lower()
                    supported = _supported_engines()
                    if eng and eng not in supported:
                        raise SchemaError(
                            f"tests.{tb_path}.engine: unknown engine {eng!r}; "
                            f"use one of {sorted(supported)}"
                        )
                    engine = eng or None
                continue

            # Measurement boundary spec
            if not isinstance(bounds, dict):
                bounds = {}
            try:
                vmin = _parse_scalar_value(bounds.get("min", bounds.get("vmin")))
                vmax = _parse_scalar_value(bounds.get("max", bounds.get("vmax")))
                vtyp = _parse_scalar_value(bounds.get("typ", bounds.get("vtyp")))
            except SchemaError as exc:
                raise SchemaError(
                    f"tests.{tb_path}.{val_name}: {exc}"
                ) from exc
            unit_raw = bounds.get("unit", bounds.get("units"))
            unit = str(unit_raw).strip() or None if unit_raw is not None else None
            value_lst.append(
                Value(name=str(val_name), vmin=vmin, vmax=vmax, vtyp=vtyp, unit=unit)
            )

        t = Test(tb_path, value_lst)
        t.analyses = analyses
        t.measure = measure
        t.engine = engine
        stim.addTest(t)

    return stim
