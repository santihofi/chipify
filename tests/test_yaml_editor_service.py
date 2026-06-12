# Copyright (c) 2026 Santiago Hofwimmer
"""
tests/test_yaml_editor_service.py

Unit tests for chipify.gui.services.yaml_editor_service.

Covers:
- get_params_dict: recognised key variants, falls back to ('params', {})
- get_tests_dict: recognised key variants, normalises 'values' sub-block
- gui_repr_param: string wrapping, pass-through for DSL/numeric strings
- sync_form_to_yaml: round-trip preservation of measure:/typ:/unknown keys
"""
from __future__ import annotations

import pytest
from chipify.gui.services.yaml_editor_service import (
    get_params_dict,
    get_tests_dict,
    gui_repr_param,
    sync_form_to_yaml,
)


class _Var:
    """Stand-in for a tk StringVar (only .get() is needed)."""

    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value


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


def test_gui_repr_param_dsl_strings_unquoted() -> None:
    assert gui_repr_param("linspace(0.6, 0.9, 4)") == "linspace(0.6, 0.9, 4)"
    assert gui_repr_param("logspace(0, 2, 3)") == "logspace(0, 2, 3)"


def test_gui_repr_param_compact_floats() -> None:
    assert gui_repr_param(1000000.0) == "1e+06"
    assert gui_repr_param(0.75) == "0.75"


def test_gui_repr_param_numeric_string() -> None:
    assert gui_repr_param("1.8") == "1.8"


def test_gui_repr_param_plain_string_gets_quoted() -> None:
    result = gui_repr_param("typical")
    assert result == "'typical'"


def test_gui_repr_param_non_string() -> None:
    assert gui_repr_param(1.8) == "1.8"
    assert gui_repr_param([1, 2]) == "[1, 2]"


# ── sync_form_to_yaml round-trip ──────────────────────────────────────────────

def _form_state(yaml_data: dict) -> tuple[list, list]:
    """Build (param_vars, test_vars) mirroring an untouched editor form."""
    _, params = get_params_dict(yaml_data)
    _, tests = get_tests_dict(yaml_data)
    skip = ("values", "measure",
            "transient_signals", "dc_signals", "ac_signals")

    param_vars = []
    for k, v in params.items():
        if isinstance(v, list):
            val_str = ", ".join(str(x) for x in v)
        else:
            val_str = str(v)
        param_vars.append({"key": _Var(str(k)), "val": _Var(val_str)})

    test_vars = []
    for tb_name, tb_data in tests.items():
        tb_data = tb_data if isinstance(tb_data, dict) else {}
        values = []
        for v_name, v_data in tb_data.items():
            if v_name in skip:
                continue
            v_data = v_data if isinstance(v_data, dict) else {}
            vmin = v_data.get("vmin", v_data.get("min", ""))
            vmax = v_data.get("vmax", v_data.get("max", ""))
            vtyp = v_data.get("vtyp", v_data.get("typ", ""))
            values.append({
                "name": _Var(str(v_name)),
                "vmin": _Var(str(vmin) if vmin is not None else ""),
                "vmax": _Var(str(vmax) if vmax is not None else ""),
                "vtyp": _Var(str(vtyp) if vtyp is not None else ""),
                "orig_name": str(v_name),
            })
        analysis_vars = {
            key: _Var(", ".join(str(s) for s in tb_data.get(key, []))
                      if isinstance(tb_data.get(key), list) else "")
            for key in ("transient_signals", "dc_signals", "ac_signals")
        }
        test_vars.append({
            "tb_name": _Var(str(tb_name)),
            "values": values,
            "tran_signals": analysis_vars["transient_signals"],
            "analysis_signals": analysis_vars,
        })
    return param_vars, test_vars


def _sample_yaml() -> dict:
    return {
        "parameters": {"temp": [27, 85], "corner": ["tt"]},
        "tests": {
            "tb_gain": {
                "ac_signals": ["out"],
                "gain": {"min": 40.0, "max": 80.0, "typ": 60.0},
                "measure": {"gbw": "gain * bandwidth"},
                "custom_key": {"anything": True},
            },
        },
    }


def test_sync_preserves_measure_typ_and_unknown_keys() -> None:
    data = _sample_yaml()
    pv, tv = _form_state(data)
    out = sync_form_to_yaml(data, "parameters", "tests", pv, tv, str)
    tb = out["tests"]["tb_gain"]
    assert tb["measure"] == {"gbw": "gain * bandwidth"}
    assert tb["gain"]["typ"] == 60.0
    assert tb["custom_key"] == {"anything": True}
    assert tb["ac_signals"] == ["out"]
    assert tb["gain"]["min"] == 40.0 and tb["gain"]["max"] == 80.0


def test_sync_updates_bounds_keeps_typ() -> None:
    data = _sample_yaml()
    pv, tv = _form_state(data)
    tv[0]["values"][0]["vmin"] = _Var("45")     # edit min in the form
    out = sync_form_to_yaml(data, "parameters", "tests", pv, tv, str)
    tb = out["tests"]["tb_gain"]
    assert tb["gain"]["min"] == 45.0
    assert tb["gain"]["typ"] == 60.0            # untouched key survives


def test_sync_rename_measurement_carries_spec() -> None:
    data = _sample_yaml()
    pv, tv = _form_state(data)
    tv[0]["values"][0]["name"] = _Var("gain_db")
    out = sync_form_to_yaml(data, "parameters", "tests", pv, tv, str)
    tb = out["tests"]["tb_gain"]
    assert "gain" not in tb
    assert tb["gain_db"]["typ"] == 60.0


def test_sync_clearing_bound_removes_it() -> None:
    data = _sample_yaml()
    pv, tv = _form_state(data)
    tv[0]["values"][0]["vmax"] = _Var("")
    out = sync_form_to_yaml(data, "parameters", "tests", pv, tv, str)
    tb = out["tests"]["tb_gain"]
    assert "max" not in tb["gain"]
    assert tb["gain"]["min"] == 40.0


def test_sync_keeps_dsl_params_intact() -> None:
    # linspace/logspace contain commas — the sync must not comma-split them
    # into a broken list (that silently corrupted datasheets on save).
    data = {"parameters": {"vincm": "linspace(0.6, 0.9, 4)"}, "tests": {}}
    pv = [{"key": _Var("vincm"), "val": _Var("linspace(0.6, 0.9, 4)")}]
    out = sync_form_to_yaml(data, "parameters", "tests", pv, [], str)
    assert out["parameters"]["vincm"] == "linspace(0.6, 0.9, 4)"


def test_sync_clearing_signals_removes_key() -> None:
    data = _sample_yaml()
    pv, tv = _form_state(data)
    tv[0]["analysis_signals"]["ac_signals"] = _Var("")
    out = sync_form_to_yaml(data, "parameters", "tests", pv, tv, str)
    assert "ac_signals" not in out["tests"]["tb_gain"]


def test_sync_updates_typ() -> None:
    data = _sample_yaml()
    pv, tv = _form_state(data)
    tv[0]["values"][0]["vtyp"] = _Var("65")
    out = sync_form_to_yaml(data, "parameters", "tests", pv, tv, str)
    assert out["tests"]["tb_gain"]["gain"]["typ"] == 65.0


def test_sync_clearing_typ_removes_it() -> None:
    data = _sample_yaml()
    pv, tv = _form_state(data)
    tv[0]["values"][0]["vtyp"] = _Var("")
    out = sync_form_to_yaml(data, "parameters", "tests", pv, tv, str)
    tb = out["tests"]["tb_gain"]
    assert "typ" not in tb["gain"]
    assert tb["gain"]["min"] == 40.0          # other bounds untouched


def test_sync_without_vtyp_field_is_backcompat() -> None:
    # Form states built before the Typ column carry no 'vtyp' key — the
    # original typ value must survive untouched via the merge.
    data = _sample_yaml()
    pv, tv = _form_state(data)
    del tv[0]["values"][0]["vtyp"]
    out = sync_form_to_yaml(data, "parameters", "tests", pv, tv, str)
    assert out["tests"]["tb_gain"]["gain"]["typ"] == 60.0


# ── create_datasheet / new_datasheet_template ─────────────────────────────────

def test_template_is_a_valid_datasheet() -> None:
    import yaml
    from chipify.gui.services.yaml_editor_service import new_datasheet_template
    from chipify.schema import validate_datasheet
    data = yaml.safe_load(new_datasheet_template())
    stim = validate_datasheet(data)
    assert stim.params and stim.tests
    assert stim.tests[0].value_lst[0].vmin == 0.0


def test_create_datasheet_writes_template(tmp_path) -> None:
    from chipify.gui.services.yaml_editor_service import create_datasheet
    path = create_datasheet(str(tmp_path), "my_design")
    assert path.endswith("my_design.yaml")
    text = open(path, encoding="utf-8").read()
    assert "parameters:" in text and "tests:" in text


def test_create_datasheet_sanitises_name(tmp_path) -> None:
    from chipify.gui.services.yaml_editor_service import create_datasheet
    path = create_datasheet(str(tmp_path), "  ../weird:name?  ")
    import os
    assert os.path.dirname(path) == str(tmp_path)       # no path escape
    assert os.path.basename(path) == "weird_name.yaml"


def test_create_datasheet_refuses_overwrite(tmp_path) -> None:
    from chipify.gui.services.yaml_editor_service import create_datasheet
    create_datasheet(str(tmp_path), "a")
    with pytest.raises(FileExistsError):
        create_datasheet(str(tmp_path), "a")


def test_create_datasheet_rejects_empty_name(tmp_path) -> None:
    from chipify.gui.services.yaml_editor_service import create_datasheet
    with pytest.raises(ValueError):
        create_datasheet(str(tmp_path), "   ")
