"""
yaml_editor_service.py – Pure-logic helpers for the YAML datasheet editor tab.

No tkinter imports.  The editor tab calls these functions to translate between
the raw YAML dict and the form-variable state, and to create new datasheet
files from a starter template.
"""
from __future__ import annotations

import os
import re
from typing import Any

_RE_BAD_FILENAME = re.compile(r'[\\/:*?"<>|]+')


# ── Parameter display helpers ─────────────────────────────────────────────────

def gui_repr_param(x: Any) -> str:
    """
    Return a user-facing string representation of a parameter value.

    - Strings that look like DSL calls or plain numbers are left as-is.
    - Other strings are wrapped in single quotes.
    - Numbers use compact %g formatting (1000000.0 → 1e+06).
    - Everything else uses ``str()``.
    """
    if isinstance(x, str):
        stripped = x.strip()
        # DSL call (range/linspace/logspace) or numpy expression
        if stripped.startswith(("range(", "linspace(", "logspace(", "np.")):
            return stripped
        # Plain numeric string
        if stripped.replace(".", "", 1).replace("-", "", 1).isdigit():
            return stripped
        return f"'{stripped}'"
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return f"{x:g}"
    return str(x)


def fmt_bound(v: Any) -> str:
    """Format a measurement bound for an entry field: compact for numbers."""
    if v is None:
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:g}"
    return str(v)


# ── New-datasheet helpers ─────────────────────────────────────────────────────

def new_datasheet_template() -> str:
    """Return a commented starter datasheet (see examples/datasheet.yaml)."""
    return (
        "# Chipify datasheet — see examples/datasheet.yaml for the full,\n"
        "# documented template.\n"
        "\n"
        "# Each entry becomes a swept dimension. Values may be a list of\n"
        "# discrete values or a range DSL string: range(N), linspace(a, b, N),\n"
        "# logspace(a, b, N).\n"
        "parameters:\n"
        "  temp: [27]\n"
        "  seed: range(10)\n"
        "\n"
        "# Each key under tests is the name of an Xschem testbench schematic\n"
        "# in your tb/ folder (without the .sch extension).\n"
        "tests:\n"
        "  tb_example:\n"
        "    my_measurement:\n"
        "      min: 0.0\n"
        "      max: 1.0\n"
        "      typ: 0.5\n"
    )


def create_datasheet(in_dir: str, name: str) -> str:
    """Create ``<in_dir>/<name>.yaml`` from the starter template.

    The name is sanitised (path separators and other illegal filename
    characters become underscores; a ``.yaml``/``.yml`` extension is added if
    missing). Raises ValueError for an empty name and FileExistsError if the
    file already exists. Returns the path written.
    """
    base = _RE_BAD_FILENAME.sub("_", (name or "").strip()).strip("._ ")
    if not base:
        raise ValueError("Datasheet name must not be empty.")
    if not base.lower().endswith((".yaml", ".yml")):
        base += ".yaml"

    os.makedirs(in_dir, exist_ok=True)
    path = os.path.join(in_dir, base)
    if os.path.exists(path):
        raise FileExistsError(f"{base} already exists in {in_dir}.")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_datasheet_template())
    return path


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


def _set_bound(v_data: dict[str, Any], primary: str, alias: str, raw: str) -> None:
    """Update one min/max bound on a measurement spec dict.

    Writes to whichever key the spec already uses (``min`` or the legacy
    ``vmin`` alias); an empty form field removes the bound. All other keys
    on the spec (``typ`` etc.) are left untouched.
    """
    target = alias if (alias in v_data and primary not in v_data) else primary
    if raw and raw.lower() != "none":
        try:
            v_data[target] = float(raw)
        except ValueError:
            v_data[target] = raw
    else:
        v_data.pop(primary, None)
        v_data.pop(alias, None)


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

    The tests section is merged, not rebuilt: keys the form does not edit
    (``measure:`` blocks, ``typ:`` values, anything user-defined) are
    preserved. Only the keys the form actually owns — testbench names,
    min/max bounds, and the three ``*_signals`` lists — are rewritten.

    Parameters
    ----------
    yaml_data:
        The mutable YAML dict to update in-place.
    param_key, test_key:
        The YAML keys under which parameters / tests live.
    param_vars:
        List of ``{"key": StringVar, "val": StringVar}`` dicts.
    test_vars:
        List of ``{"tb_name": StringVar, "values": [...], "tran_signals": StringVar}``
        dicts, in the same order as the testbench entries of *yaml_data*
        (build_editor_ui builds them that way). Each ``values`` entry may
        carry ``orig_name`` so renames can be tracked back to the original
        spec dict.
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

        # A DSL expression is a single value — never comma-split it
        # (linspace/logspace contain commas inside the call).
        if v_str.startswith(("range(", "linspace(", "logspace(", "np.")):
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

    # ── Tests (merge: preserve keys the form does not edit) ───────────────────
    old_tests_raw = yaml_data.get(test_key)
    old_tests: dict[str, Any] = (
        dict(old_tests_raw) if isinstance(old_tests_raw, dict) else {}
    )
    old_tb_keys = list(old_tests.keys())

    yaml_data[test_key] = {}
    for t_idx, t_dict in enumerate(test_vars):
        tb_name = t_dict["tb_name"].get().strip()
        if not tb_name:
            continue

        # Form rows are built in the dict's order, so index alignment maps a
        # (possibly renamed) form entry back to its original content — this
        # is what keeps measure:/typ:/custom keys alive across a save.
        orig_content = (
            old_tests.get(old_tb_keys[t_idx]) if t_idx < len(old_tb_keys) else None
        )
        tb_content: dict[str, Any] = (
            dict(orig_content) if isinstance(orig_content, dict) else {}
        )

        # Analysis signal lists (transient / dc / ac). The new
        # ``analysis_signals`` dict carries all three; ``tran_signals`` is the
        # legacy alias still set by the form for back-compat. An emptied form
        # field removes the corresponding key.
        analysis_vars = t_dict.get("analysis_signals")
        if isinstance(analysis_vars, dict):
            for yaml_key in ("transient_signals", "dc_signals", "ac_signals"):
                var = analysis_vars.get(yaml_key)
                if var is None:
                    continue
                raw = var.get().strip()
                signals = [s.strip()
                           for s in raw.replace(",", " ").split()
                           if s.strip()]
                if signals:
                    tb_content[yaml_key] = signals
                else:
                    tb_content.pop(yaml_key, None)
        else:
            tran_raw = t_dict.get("tran_signals")
            if tran_raw is not None:
                tran_str = tran_raw.get().strip()
                tran_list = [s.strip()
                             for s in tran_str.replace(",", " ").split()
                             if s.strip()]
                if tran_list:
                    tb_content["transient_signals"] = tran_list
                else:
                    tb_content.pop("transient_signals", None)

        for v_dict in t_dict["values"]:
            name = v_dict["name"].get().strip()
            orig_name = str(v_dict.get("orig_name", "") or "")
            orig_spec = tb_content.get(orig_name) if orig_name else None
            renamed = bool(orig_name) and name != orig_name
            if (renamed or not name) and orig_name in tb_content:
                del tb_content[orig_name]
            if not name:
                continue
            v_data: dict[str, Any] = (
                dict(orig_spec) if isinstance(orig_spec, dict) else {}
            )
            _set_bound(v_data, "min", "vmin", v_dict["vmin"].get().strip())
            _set_bound(v_data, "max", "vmax", v_dict["vmax"].get().strip())
            if "vtyp" in v_dict:  # older form states may not carry a typ field
                _set_bound(v_data, "typ", "vtyp", v_dict["vtyp"].get().strip())
            tb_content[name] = v_data

        yaml_data[test_key][tb_name] = tb_content

    return yaml_data
