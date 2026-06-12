# Copyright (c) 2026 Santiago Hofwimmer
"""
tests/test_data_loader_history.py

Unit tests for chipify.gui.services.data_loader.list_history_runs.

Covers:
- unfiltered listing (latest entry + newest-first history)
- strict datasheet filtering via .meta.json sidecars
- runs with missing or mismatching metadata are hidden when filtering
- "Latest (simulation_results)" survives filtering (it has no sidecar)
"""
from __future__ import annotations

import json
import os

from chipify.gui.services.data_loader import list_history_runs


def _make_run(history_dir: str, name: str, yaml_name: str | None) -> None:
    """Create a history CSV and, unless yaml_name is None, a meta sidecar."""
    csv_path = os.path.join(history_dir, name)
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("run_id,sim_error\n000001,None\n")
    if yaml_name is not None:
        meta_path = csv_path.replace(".csv", ".meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"schema_version": 1, "yaml": yaml_name}, f)


def _setup_out_dir(tmp_path, with_latest: bool = True) -> str:
    out_dir = str(tmp_path)
    if with_latest:
        with open(os.path.join(out_dir, "simulation_results.csv"), "w",
                  encoding="utf-8") as f:
            f.write("run_id,sim_error\n000001,None\n")
    history_dir = os.path.join(out_dir, "history")
    os.makedirs(history_dir)
    _make_run(history_dir, "run_20260601_100000.csv", "amp.yaml")
    _make_run(history_dir, "run_20260602_100000.csv", "filter.yaml")
    _make_run(history_dir, "run_20260603_100000.csv", None)  # no sidecar
    _make_run(history_dir, "run_20260604_100000.csv", "amp.yaml")
    return out_dir


def test_unfiltered_lists_all_newest_first(tmp_path) -> None:
    out_dir = _setup_out_dir(tmp_path)
    runs = list_history_runs(out_dir)
    assert runs == [
        "Latest (simulation_results)",
        "run_20260604_100000.csv",
        "run_20260603_100000.csv",
        "run_20260602_100000.csv",
        "run_20260601_100000.csv",
    ]


def test_filter_keeps_only_matching_datasheet(tmp_path) -> None:
    out_dir = _setup_out_dir(tmp_path)
    runs = list_history_runs(out_dir, yaml_name="amp.yaml")
    # Mismatching (filter.yaml) and meta-less runs are hidden; the live
    # "Latest" entry stays even though it has no sidecar.
    assert runs == [
        "Latest (simulation_results)",
        "run_20260604_100000.csv",
        "run_20260601_100000.csv",
    ]


def test_filter_without_latest_csv(tmp_path) -> None:
    out_dir = _setup_out_dir(tmp_path, with_latest=False)
    runs = list_history_runs(out_dir, yaml_name="filter.yaml")
    assert runs == ["run_20260602_100000.csv"]


def test_filter_with_unknown_datasheet_hides_history(tmp_path) -> None:
    out_dir = _setup_out_dir(tmp_path)
    runs = list_history_runs(out_dir, yaml_name="other.yaml")
    assert runs == ["Latest (simulation_results)"]


def _write_latest_meta(out_dir: str, yaml_name: str) -> None:
    with open(os.path.join(out_dir, "simulation_results.meta.json"), "w",
              encoding="utf-8") as f:
        json.dump({"schema_version": 1, "yaml": yaml_name}, f)


def test_latest_with_matching_meta_stays_visible(tmp_path) -> None:
    out_dir = _setup_out_dir(tmp_path)
    _write_latest_meta(out_dir, "amp.yaml")
    runs = list_history_runs(out_dir, yaml_name="amp.yaml")
    assert runs[0] == "Latest (simulation_results)"


def test_latest_with_mismatching_meta_is_hidden(tmp_path) -> None:
    out_dir = _setup_out_dir(tmp_path)
    _write_latest_meta(out_dir, "filter.yaml")
    runs = list_history_runs(out_dir, yaml_name="amp.yaml")
    assert "Latest (simulation_results)" not in runs
    # Unfiltered listing still shows it.
    assert list_history_runs(out_dir)[0] == "Latest (simulation_results)"


def test_empty_out_dir(tmp_path) -> None:
    assert list_history_runs(str(tmp_path)) == []
