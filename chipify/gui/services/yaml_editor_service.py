"""
yaml_editor_service.py – Pure-logic helpers for the YAML datasheet editor tab.

No tkinter imports.  The editor tab calls these functions to translate between
the raw YAML dict and the form-variable state.
"""
from __future__ import annotations

from typing import Any


# ── Parameter display helpers ─────────────────────────────────────────────────

def gui_repr_param(x: Any) -> str:
    """
    Return a user-facing string representation of a parameter value.

    - Strings that look like DSL calls or plain numbers are left as-is.
    - Other strings are wrapped in single quotes.
    - Everything else uses ``str()``.
    """
    if isinstance(x, str):
        stripped = x.strip()
        # DSL call (range/linspace/…) or numpy expression
        if stripped.startswith("range(") or stripped.startswith("np."):
            return stripped
        # Plain numeric string
        if stripped.replace(".", "", 1).replace("-", "", 1).isdigit():
            return stripped
        return f"'{stripped}'"
    return str(x)


# ── YAML structural helpers ───────────────────────────────────────────────────

def get_params_dict(yaml_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Extract the parameters sub-dict from a raw YAML data dict.

    Returns ``(key_used, params_dict)`` — both may be empty if no recognised
    parameter key is found.
    """
    if not isinstance(yaml_data, dict):
        return "params", {}
    for key in ("params", "parameters", "sweep"):
        if key in yaml_data:
            val = yaml_data[key]
            if isinstance(val, dict):
                return key, val
    return "params", {}


def get_tests_dict(yaml_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Extract the tests sub-dict from a raw YAML data dict.

    Normalises the legacy ``values:`` sub-block into flat measurement dicts.
    Returns ``(key_used, tests_dict)``.
    """
    if not isinstance(yaml_data, dict):
        return "tests", {}
    for key in ("tests", "testbenches", "measurements"):
        if key in yaml_data:
            val = yaml_data[key]
            if isinstance(val, dict):
                # Normalise legacy ``values:`` sub-key
                for tb_name, tb_data in val.items():
                    if isinstance(tb_data, dict) and "values" in tb_data:
                        v = tb_data.pop("values")
                        if isinstance(v, dict):
                            tb_data.update(v)
                return key, val
    return "tests", {}


def sync_form_to_yaml(
    yaml_data: dict[str, Any],
    param_key: str,
    test_key: str,
    param_vars: list[dict[str, Any]],
    test_vars: list[dict[str, Any]],
    QuotedString: type,
) -> dict[str, Any]:
    """
    Write the form-variable state back into *yaml_data*.

    Parameters
    ----------
    yaml_data:
        The mutable YAML dict to update in-place.
    param_key, test_key:
        The YAML keys under which parameters / tests live.
    param_vars:
        List of ``{"key": StringVar, "val": StringVar}`` dicts.
    test_vars:
        List of ``{"tb_name": StringVar, "values": [...], "tran_signals": StringVar}`` dicts.
    QuotedString:
        The QuotedString subclass from yaml_dumper (passed to avoid circular imports).

    Returns
    -------
    dict
        The updated *yaml_data*.
    """
    if not isinstance(yaml_data, dict):
        yaml_data = {}

    # ── Parameters ────────────────────────────────────────────────────────────
    yaml_data[param_key] = {}
    for p_dict in param_vars:
        k = p_dict["key"].get().strip()
        v_str = p_dict["val"].get().strip()
        if not k:
            continue

        if v_str.startswith("range(") or v_str.startswith("np."):
            yaml_data[param_key][k] = v_str
            continue

        parsed_list: list[Any] = []
        for x in v_str.split(","):
            x = x.strip()
            if not x:
                continue
            if (x.startswith("'") and x.endswith("'")) or (x.startswith('"') and x.endswith('"')):
                parsed_list.append(QuotedString(x[1:-1]))
            else:
                try:
                    parsed_list.append(float(x) if "." in x else int(x))
                except ValueError:
                    parsed_list.append(x)
        yaml_data[param_key][k] = parsed_list

    # ── Tests ─────────────────────────────────────────────────────────────────
    yaml_data[test_key] = {}
    for t_dict in test_vars:
        tb_name = t_dict["tb_name"].get().strip()
        if not tb_name:
            continue

        tb_content: dict[str, Any] = {}

        # Analysis signal lists (transient / dc / ac) first so they appear at
        # the top of the block. The new ``analysis_signals`` dict carries all
        # three; ``tran_signals`` is the legacy alias still set by the form
        # for back-compat.
        analysis_vars = t_dict.get("analysis_signals")
        if isinstance(analysis_vars, dict):
            for yaml_key in ("transient_signals", "dc_signals", "ac_signals"):
                var = analysis_vars.get(yaml_key)
                if var is None:
                    continue
                raw = var.get().strip()
                if not raw:
                    continue
                signals = [s.strip()
                           for s in raw.replace(",", " ").split()
                           if s.strip()]
                if signals:
                    tb_content[yaml_key] = signals
        else:
            tran_raw = t_dict.get("tran_signals")
            if tran_raw is not None:
                tran_str = tran_raw.get().strip()
                if tran_str:
                    tran_list = [s.strip()
                                 for s in tran_str.replace(",", " ").split()
                                 if s.strip()]
                    if tran_list:
                        tb_content["transient_signals"] = tran_list

        for v_dict in t_dict["values"]:
            name = v_dict["name"].get().strip()
            if not name:
                continue
            v_data: dict[str, Any] = {}
            vmin_str = v_dict["vmin"].get().strip()
            vmax_str = v_dict["vmax"].get().strip()

            if vmin_str and vmin_str.lower() != "none":
                try:
                    v_data["min"] = float(vmin_str)
                except ValueError:
                    v_data["min"] = vmin_str
            if vmax_str and vmax_str.lower() != "none":
                try:
                    v_data["max"] = float(vmax_str)
                except ValueError:
                    v_data["max"] = vmax_str
            tb_content[name] = v_data

        yaml_data[test_key][tb_name] = tb_content

    return yaml_data
