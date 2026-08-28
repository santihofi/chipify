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


#: UI label -> ``Analysis.kind`` as written on disk and in
#: ``df.attrs["analysis_dirs"]``. One definition, shared by the Plots tab and
#: the Multi-plot dashboard cell so their kind selectors cannot drift apart.
KIND_LABELS: dict[str, str] = {"Transient": "transient", "DC Sweep": "dc",
                               "Bode": "ac"}


def kind_for_label(label: str) -> str:
    """Analysis kind for a UI label, defaulting to transient."""
    return KIND_LABELS.get(label, "transient")


def pad_run_id(value: Any) -> str:
    """Zero-pad a run id to the six digits used in ``run_<id>__<tb>.csv``.

    Necessary because a results frame read back from CSV parses ``run_id`` as
    an integer, so a plain ``astype(str)`` yields ``"4"`` where the waveform
    file is ``run_000004__tb.csv`` — and the overlay then silently matches no
    files at all for every loaded run.
    """
    return str(value).strip().zfill(6)


def padded_run_ids(df: pd.DataFrame) -> list[str]:
    """Every run id in *df*, zero-padded (empty when the column is absent)."""
    if df is None or "run_id" not in df.columns:
        return []
    return [pad_run_id(v) for v in df["run_id"]]


def run_pass_map(df: pd.DataFrame) -> dict[str, bool]:
    """``run_id -> passed`` for every run in *df*.

    Keys are zero-padded to six digits to match the ``run_<id>__<tb>.csv``
    filenames the overlay plotters parse.
    """
    if df is None or "run_id" not in df.columns or "global_pass" not in df.columns:
        return {}
    pairs = df[["run_id", "global_pass"]].dropna(subset=["run_id"])
    return {pad_run_id(rid): bool(ok)
            for rid, ok in zip(pairs["run_id"], pairs["global_pass"])}


def run_group_map(df: pd.DataFrame, group_col: str) -> dict[str, Any]:
    """``run_id -> value of *group_col*`` for every run in *df*.

    Lets a waveform overlay colour its curves by a swept input parameter
    (``temp``, ``corner``, …) instead of by bare run index. Same zero-padded
    keys as :func:`run_pass_map`. An unknown or unset column yields ``{}``,
    which the plotters read as "no grouping".
    """
    if (df is None or not group_col or group_col == "None"
            or "run_id" not in df.columns or group_col not in df.columns):
        return {}
    pairs = df[["run_id", group_col]].dropna(subset=["run_id"])
    return {pad_run_id(rid): val
            for rid, val in zip(pairs["run_id"], pairs[group_col])}


def list_kind_signals(stim: Any, kind: str) -> list[str]:
    """Signals declared for one analysis *kind*, in declaration order.

    Transient additionally offers the datasheet's ``transient_equations:``
    results, which are computed per run when the waveform is drawn.
    """
    seen: list[str] = []
    for test in getattr(stim, "tests", None) or []:
        for an in getattr(test, "analyses", None) or []:
            if an.kind != kind:
                continue
            for sig in an.signals:
                if sig not in seen:
                    seen.append(sig)
    if kind == "transient":
        from chipify.uikit.services import equation_service as _eq_svc
        for eq in _eq_svc.transient_equations(stim):
            name = (eq.get("name") or "").strip()
            if name and name not in seen:
                seen.append(name)
    return seen


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
