# Copyright (c) 2026 Santiago Hofwimmer
"""Tests for chipify.export_latex waveform-overlay export.

Regression coverage: every run must be exported against its own X vector —
ngspice transient runs use adaptive timesteps, so reusing run 0's time
column would silently distort every other run's curve.
"""
from __future__ import annotations

import pytest

export_latex = pytest.importorskip("chipify.export_latex")
pd = pytest.importorskip("pandas")


def _write_run_csv(adir, rid: str, time, out) -> None:
    df = pd.DataFrame({"time": time, "v(out)": out})
    df.to_csv(adir / f"run_{rid}__tb_x.csv", index=False)


def test_transient_export_uses_per_run_time_axes(tmp_path) -> None:
    adir = tmp_path / "tran"
    adir.mkdir()
    # Two runs with *different* time grids (and lengths).
    _write_run_csv(adir, "000000", [0.0, 1e-6, 2e-6], [0.0, 1.0, 2.0])
    _write_run_csv(adir, "000001", [0.0, 0.5e-6, 1.5e-6, 3e-6], [0.0, 0.5, 1.5, 3.0])

    out_dir = tmp_path / "latex"
    csv_path, tex_path = export_latex.generate_transient_latex_export(
        str(out_dir), "tran", str(adir),
        ["000000", "000001"], ["v(out)"],
    )

    table = pd.read_csv(csv_path)
    # One x column per run, NaN-padded to the longest run.
    assert "x_000000" in table.columns and "x_000001" in table.columns
    assert len(table) == 4
    assert table["x_000000"].isna().sum() == 1          # padded
    # Time autoscale (µs range → ×1e6).
    assert table["x_000001"].iloc[3] == pytest.approx(3.0)
    assert table["x_000000"].iloc[2] == pytest.approx(2.0)

    tex = open(tex_path, encoding="utf-8").read()
    # Each addplot must reference its own run's x column.
    assert "table [x=x_000000, y=r_000000_v_out]" in tex
    assert "table [x=x_000001, y=r_000001_v_out]" in tex


def test_transient_export_raises_without_data(tmp_path) -> None:
    with pytest.raises(ValueError):
        export_latex.generate_transient_latex_export(
            str(tmp_path / "latex"), "tran", str(tmp_path), ["000000"], ["v(out)"],
        )


def test_bode_export_per_run_frequency(tmp_path) -> None:
    adir = tmp_path / "ac"
    adir.mkdir()
    pd.DataFrame({
        "frequency": [1.0, 10.0, 100.0],
        "out_mag": [1.0, 0.5, 0.1],
        "out_phase": [0.0, -45.0, -90.0],
    }).to_csv(adir / "run_000000__tb_x.csv", index=False)

    out_dir = tmp_path / "latex"
    csv_path, tex_path = export_latex.generate_bode_latex_export(
        str(out_dir), "bode", str(adir), ["000000"], ["out"],
    )
    table = pd.read_csv(csv_path)
    assert "x_000000" in table.columns
    tex = open(tex_path, encoding="utf-8").read()
    assert "x=x_000000" in tex
