# Copyright (c) 2026 Santiago Hofwimmer
"""Tests for datasheet-stored custom equations.

Covers schema parsing of the top-level ``equations:`` / ``transient_equations:``
blocks (mapping and legacy list shapes, identifier validation) and the
equation_service source resolution (datasheet first, settings.json fallback
until migrated).
"""
from __future__ import annotations

import pytest

from chipify.schema import SchemaError, validate_datasheet


# ── Schema parsing ────────────────────────────────────────────────────────────

def test_equations_mapping_parsed() -> None:
    stim = validate_datasheet({
        "equations": {"gain_lin": "10 ** (gain / 20)"},
        "transient_equations": {"vdiff": "v(outp) - v(outn)"},
    })
    assert stim.equations == [{"name": "gain_lin", "expr": "10 ** (gain / 20)"}]
    assert stim.transient_equations == [{"name": "vdiff", "expr": "v(outp) - v(outn)"}]


def test_equations_legacy_list_shape_parsed() -> None:
    stim = validate_datasheet({
        "equations": [{"name": "eff", "expr": "p_out / p_in"}],
    })
    assert stim.equations == [{"name": "eff", "expr": "p_out / p_in"}]


def test_equations_absent_is_empty() -> None:
    stim = validate_datasheet({})
    assert stim.equations == [] and stim.transient_equations == []


def test_equation_name_must_be_identifier() -> None:
    with pytest.raises(SchemaError, match="identifier"):
        validate_datasheet({"equations": {"bad name": "1 + 1"}})


def test_equation_expr_must_not_be_empty() -> None:
    with pytest.raises(SchemaError, match="empty"):
        validate_datasheet({"equations": {"x": "   "}})


def test_equations_wrong_type_rejected() -> None:
    with pytest.raises(SchemaError, match="mapping"):
        validate_datasheet({"equations": "gain * 2"})


# ── Source resolution (datasheet first, legacy settings fallback) ─────────────

class _Stim:
    def __init__(self, equations=None, transient_equations=None):
        self.equations = equations or []
        self.transient_equations = transient_equations or []


def test_scalar_equations_prefer_datasheet(monkeypatch) -> None:
    from chipify import app_config
    from chipify.uikit.services import equation_service as _eq

    monkeypatch.setattr(app_config, "load_config",
                        lambda: {"custom_equations": [{"name": "legacy", "expr": "1"}]})
    stim = _Stim(equations=[{"name": "ds", "expr": "2"}])
    assert _eq.scalar_equations(stim) == [{"name": "ds", "expr": "2"}]


def test_scalar_equations_fall_back_to_settings(monkeypatch) -> None:
    from chipify import app_config
    from chipify.uikit.services import equation_service as _eq

    monkeypatch.setattr(app_config, "load_config",
                        lambda: {"custom_equations": [{"name": "legacy", "expr": "1"}]})
    assert _eq.scalar_equations(_Stim()) == [{"name": "legacy", "expr": "1"}]
    # Objects without the attribute at all (fakes, old pickles) behave the same.
    assert _eq.scalar_equations(object()) == [{"name": "legacy", "expr": "1"}]


def test_transient_equations_sources(monkeypatch) -> None:
    from chipify import app_config
    from chipify.uikit.services import equation_service as _eq

    monkeypatch.setattr(app_config, "load_config",
                        lambda: {"transient_equations": [{"name": "tlegacy", "expr": "3"}]})
    assert _eq.transient_equations(_Stim()) == [{"name": "tlegacy", "expr": "3"}]
    stim = _Stim(transient_equations=[{"name": "tds", "expr": "4"}])
    assert _eq.transient_equations(stim) == [{"name": "tds", "expr": "4"}]


def test_stimuli_loads_equations_from_yaml(tmp_path) -> None:
    from chipify.util import Stimuli
    p = tmp_path / "ds.yaml"
    p.write_text(
        "parameters:\n  temp: [27]\n"
        "tests:\n  tb_x:\n    gain: {min: 0}\n"
        "equations:\n  gain_db: '20 * log10(gain)'\n"
        "transient_equations:\n  vd: 'v(a) - v(b)'\n",
        encoding="utf-8",
    )
    stim = Stimuli(str(p))
    assert stim.equations == [{"name": "gain_db", "expr": "20 * log10(gain)"}]
    assert stim.transient_equations == [{"name": "vd", "expr": "v(a) - v(b)"}]
