# Copyright (c) 2026 Santiago Hofwimmer
"""
transient_loader.py – Helpers for loading analysis-result CSV files.

Historically this module was transient-only. It now serves all three analysis
kinds (transient / dc / ac) via the generic ``resolve_analysis_dir`` and
``load_analysis_df`` helpers. The transient-specific wrappers below keep the
old public API working so callers don't all need updating at once.

The on-disk layout is::

    {OUT_DIR}/analysis_data/{kind}/{timestamp}/run_<id>__<tb>.csv

with a fallback to the legacy ``{OUT_DIR}/tran_data/{timestamp}/`` location
for transient when no ``analysis_data`` directory exists.

No tkinter imports.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

from chipify.uikit.services.equation_service import apply_transient_equations

log = logging.getLogger("chipify.uikit.services.transient")


# ── Generic helpers ──────────────────────────────────────────────────────────

def resolve_analysis_dir(df: pd.DataFrame, out_dir: str | os.PathLike[str],
                         kind: str,
                         meta: dict[str, Any] | None = None) -> str:
    """
    Find the per-run CSV directory for ``kind`` (transient/dc/ac).

    Strategy (first match wins):
    1. ``df.attrs["analysis_dirs"][kind]`` — set by run_sim when CSVs are written.
    2. ``df.attrs["tran_dir"]`` — back-compat alias for kind="transient".
    3. *meta* — a run_meta sidecar dict for the loaded history run
       (``analysis_dirs`` / legacy ``tran_dir`` keys). Checked before the
       pointer files so an older history run resolves to its own data, not
       the most recent run's.
    4. ``{out_dir}/analysis_data/{kind}/.latest`` pointer file (and the
       legacy ``{out_dir}/tran_data/.latest`` for transient).
    5. Newest sub-directory under ``{out_dir}/analysis_data/{kind}/``.
    6. (transient only) newest sub-directory under the legacy ``{out_dir}/tran_data/``.
    """
    out_path = Path(out_dir)

    # 1. DataFrame attribute set by the live simulation run.
    if hasattr(df, "attrs"):
        adirs = df.attrs.get("analysis_dirs", {})
        if isinstance(adirs, dict):
            d = str(adirs.get(kind, "") or "")
            if d and Path(d).is_dir():
                return d
        # 2. Back-compat alias for transient.
        if kind == "transient":
            d = str(df.attrs.get("tran_dir", "") or "")
            if d and Path(d).is_dir():
                return d

    # 3. History run's meta sidecar.
    if isinstance(meta, dict):
        meta_adirs = meta.get("analysis_dirs", {})
        d = str(meta_adirs.get(kind, "") or "") if isinstance(meta_adirs, dict) else ""
        if d and Path(d).is_dir():
            return d
        if kind == "transient":
            d = str(meta.get("tran_dir", "") or "")
            if d and Path(d).is_dir():
                return d

    # 4. Pointer files.
    pointers = [out_path / "analysis_data" / kind / ".latest"]
    if kind == "transient":
        pointers.append(out_path / "tran_data" / ".latest")
    for ptr in pointers:
        if ptr.exists():
            try:
                d = ptr.read_text(encoding="utf-8").strip()
                if d and Path(d).is_dir():
                    return d
            except Exception:
                pass

    # 5. Newest timestamped subdir under analysis_data/<kind>/.
    newest = _newest_subdir(out_path / "analysis_data" / kind)
    if newest:
        return newest

    # 6. Legacy transient location.
    if kind == "transient":
        legacy = _newest_subdir(out_path / "tran_data")
        if legacy:
            return legacy

    return ""


def _newest_subdir(base: str | os.PathLike[str]) -> str:
    base = Path(base)
    if not base.is_dir():
        return ""
    subdirs = [
        d for d in base.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ]
    if not subdirs:
        return ""
    subdirs.sort(key=lambda p: p.name, reverse=True)
    return str(subdirs[0])


def list_analysis_signals(adir: str, kind: str) -> list[str]:
    """
    Return the union of plottable signal names found in CSVs under *adir*.

    For ac data, signals come paired as ``<sig>_mag`` / ``<sig>_phase``; this
    helper collapses them back to ``<sig>`` so the GUI picker shows one entry
    per requested signal. The Bode plotter then reads both columns by suffix.
    """
    if not adir or not Path(adir).is_dir():
        return []

    x_cols = {"time", "frequency", "sweep", "run_id"}
    signals: set[str] = set()
    for fname in Path(adir).glob("run_*.csv"):
        try:
            header = pd.read_csv(fname, nrows=0)
        except Exception:
            continue
        for col in header.columns:
            cs = str(col)
            if cs in x_cols:
                continue
            if kind == "ac" and cs.endswith(("_mag", "_phase")):
                signals.add(cs.rsplit("_", 1)[0])
            else:
                signals.add(cs)
    return sorted(signals)


def load_analysis_df(
    adir: str,
    run_ids: list[str],
    equations: list[dict[str, str]] | None = None,
) -> pd.DataFrame:
    """
    Load selected per-run CSVs into a combined ``(run_id, …)`` DataFrame.

    The X column name (``time`` / ``sweep`` / ``frequency``) is preserved
    as-is; consumers can read ``df.columns`` to discover it.
    """
    if not adir or not run_ids:
        return pd.DataFrame()

    run_id_set = set(run_ids)
    chunks: list[pd.DataFrame] = []

    for fname in Path(adir).glob("run_*.csv"):
        rid = fname.name[4:].split("__", 1)[0]
        if rid not in run_id_set:
            continue
        try:
            chunk = pd.read_csv(fname)
            if equations:
                chunk = apply_transient_equations(chunk, equations)
            chunk.insert(0, "run_id", rid)
            chunks.append(chunk)
        except Exception as exc:
            log.debug("Skipping %s: %s", fname, exc)

    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


# ── Back-compat transient-specific wrappers ──────────────────────────────────

def resolve_tran_dir(df: pd.DataFrame, out_dir: str) -> str:
    return resolve_analysis_dir(df, out_dir, "transient")


def list_available_signals(tran_dir: str) -> list[str]:
    return list_analysis_signals(tran_dir, "transient")


def load_tran_df(
    tran_dir: str,
    run_ids: list[str],
    equations: list[dict[str, str]] | None = None,
) -> pd.DataFrame:
    return load_analysis_df(tran_dir, run_ids, equations)
