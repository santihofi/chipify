"""
transient_loader.py – Helpers for loading transient waveform CSV files.

No tkinter imports.  The transient tab calls these to resolve directory paths
and build the combined waveform DataFrame used for plotting and hover events.
"""
from __future__ import annotations

import glob
import logging
import os

import pandas as pd

from chipify.gui.services.equation_service import apply_transient_equations

log = logging.getLogger("chipify.gui.services.transient")


def resolve_tran_dir(df: pd.DataFrame, out_dir: str) -> str:
    """
    Find the transient waveform directory for the current run.

    Strategy (first match wins):
    1. ``df.attrs["tran_dir"]`` — set by ``run_sim_thread`` when the sim writes CSVs.
    2. ``{out_dir}/tran_data/.latest`` pointer file written by ``run_sim_thread``.
    3. Newest sub-directory under ``{out_dir}/tran_data/``.

    Returns an empty string if no directory is found.
    """
    # 1. DataFrame attribute set by the live simulation run
    tran_dir: str = df.attrs.get("tran_dir", "") if hasattr(df, "attrs") else ""
    if tran_dir and os.path.isdir(tran_dir):
        return tran_dir

    # 2. Pointer file written by run_sim_thread
    ptr = os.path.join(out_dir, "tran_data", ".latest")
    if os.path.exists(ptr):
        try:
            with open(ptr, encoding="utf-8") as fh:
                tran_dir = fh.read().strip()
            if tran_dir and os.path.isdir(tran_dir):
                return tran_dir
        except Exception:
            pass

    # 3. Newest sub-directory under tran_data/
    tran_base = os.path.join(out_dir, "tran_data")
    if os.path.isdir(tran_base):
        subdirs = [
            d for d in os.listdir(tran_base)
            if os.path.isdir(os.path.join(tran_base, d)) and not d.startswith(".")
        ]
        if subdirs:
            subdirs.sort(reverse=True)
            return os.path.join(tran_base, subdirs[0])

    return ""


def list_available_signals(tran_dir: str) -> list[str]:
    """
    Return the union of all signal column names found in any waveform CSV.

    Excludes ``time`` and ``run_id`` (internal columns).
    """
    if not tran_dir or not os.path.isdir(tran_dir):
        return []

    signals: set[str] = set()
    for fname in glob.glob(os.path.join(tran_dir, "run_*.csv")):
        try:
            header = pd.read_csv(fname, nrows=0)
            for col in header.columns:
                if col not in ("time", "run_id"):
                    signals.add(str(col))
        except Exception:
            pass
    return sorted(signals)


def load_tran_df(
    tran_dir: str,
    run_ids: list[str],
    equations: list[dict[str, str]] | None = None,
) -> pd.DataFrame:
    """
    Load selected waveform CSVs into a combined ``(run_id, time, …)`` DataFrame.

    Parameters
    ----------
    tran_dir:
        Directory containing ``run_<id>__<tb>.csv`` files.
    run_ids:
        Zero-padded run ID strings to include (e.g. ``["000001", "000002"]``).
    equations:
        Optional transient equations applied per chunk before concatenation.

    Returns
    -------
    pd.DataFrame
        Empty DataFrame if no matching files are found.
    """
    if not tran_dir or not run_ids:
        return pd.DataFrame()

    run_id_set = set(run_ids)
    chunks: list[pd.DataFrame] = []

    for fname in glob.glob(os.path.join(tran_dir, "run_*.csv")):
        rid = os.path.basename(fname)[4:].split("__", 1)[0]
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
