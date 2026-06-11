"""
tests/test_run_meta.py

Unit tests for chipify.run_meta.update_meta (notes/tags annotation backend).
"""
from __future__ import annotations

import os

from chipify import run_meta


def test_update_meta_merges_into_existing(tmp_path) -> None:
    csv = os.path.join(str(tmp_path), "run_20260611_120000.csv")
    open(csv, "w", encoding="utf-8").close()
    run_meta.write_meta(csv, yaml_name="amp.yaml", total_runs=10)

    meta = run_meta.update_meta(csv, notes="hello", tags=["x"])
    assert meta["notes"] == "hello"
    assert meta["tags"] == ["x"]
    # Pre-existing fields survive the merge.
    assert meta["yaml"] == "amp.yaml"
    assert meta["total_runs"] == 10
    assert run_meta.read_meta(csv)["notes"] == "hello"


def test_update_meta_creates_minimal_sidecar(tmp_path) -> None:
    csv = os.path.join(str(tmp_path), "run_20260611_130000.csv")
    open(csv, "w", encoding="utf-8").close()

    meta = run_meta.update_meta(csv, notes="legacy run", tags=[])
    assert meta["notes"] == "legacy run"
    assert meta["schema_version"] == 1
    # No datasheet attribution is invented — filtering stays unaffected.
    assert "yaml" not in meta
