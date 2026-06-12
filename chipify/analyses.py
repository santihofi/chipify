# Copyright (c) 2026 Santiago Hofwimmer
"""
analyses.py – Analysis-type abstraction for Chipify.

A ``Test`` may declare zero or more ``Analysis`` instances:

  - ``TransientAnalysis`` – ``.tran`` waveforms
  - ``DCSweepAnalysis``   – ``.dc`` sweep curves
  - ``ACAnalysis``        – ``.ac`` magnitude / phase (Bode)

Each subclass knows:

  - which ngspice ``.control`` line(s) capture its vectors,
  - which Jinja variable carries its per-run tab-file path,
  - how to serialise its signals from a parsed .raw dict (VACASK path),
  - how to convert the engine's whitespace .tab output into the canonical
    per-run CSV that the GUI plotter and equation evaluator consume.

Per-run CSV layout
------------------
  transient: ``time, <sig0>, <sig1>, ...``                  (real)
  dc:        ``sweep, <sig0>, <sig1>, ...``                 (real)
  ac:        ``frequency, <sig0>_mag, <sig0>_phase, ...``   (linear V, degrees)

VACASK tab layout (single-X column, written by ``write_tab_from_raw``)
----------------------------------------------------------------------
  transient: ``time  sig0  sig1  ...``
  dc:        ``sweep sig0  sig1  ...``
  ac:        ``freq  mag0  phase0  mag1  phase1  ...``

ngspice tab layout (paired, written by ``wrdata``)
--------------------------------------------------
  transient: ``time sig0  time sig1  ...``       (2*n_sigs cols)
  dc:        ``sweep sig0 sweep sig1 ...``       (2*n_sigs cols)
  ac:        ``freq mag0  freq phase0  freq mag1 freq phase1 ...`` (4*n_sigs cols)

``persist_to_csv`` auto-detects which layout the .tab file uses.
"""
from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

log = logging.getLogger("chipify.analyses")


_RE_SANITISE = re.compile(r"[^a-zA-Z0-9_]")


def _sanitise_vec_name(name: str) -> str:
    """Turn a SPICE signal like ``v(out)`` into an ngspice ``let`` vector name."""
    return _RE_SANITISE.sub("_", name).strip("_") or "x"


def _read_tab(tab_path: str) -> pd.DataFrame | None:
    """Read a whitespace-separated .tab file. Returns None on empty / parse error."""
    try:
        df = pd.read_csv(tab_path, sep=r"\s+", header=None, comment="*")
    except Exception as exc:
        log.warning("Could not read tab file %s: %s", tab_path, exc)
        return None
    if df.empty:
        return None
    return df


def _write_tab_columns(out_path: str, x_vec: np.ndarray,
                       y_vecs: list[np.ndarray]) -> None:
    """Write a single-X-column tab file: ``x y0 y1 ...`` rows."""
    cols = [np.asarray(x_vec, dtype=float)] + [np.asarray(v, dtype=float)
                                               for v in y_vecs]
    n = min(len(c) for c in cols)
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            for i in range(n):
                fh.write("  ".join(f"{c[i]:.6e}" for c in cols) + "\n")
    except Exception as exc:
        log.warning("Could not write tab %s: %s", out_path, exc)


def _lookup_signal(bucket: dict, name: str) -> np.ndarray | None:
    """Find a signal in a parsed raw bucket, trying common naming variants."""
    name_lc = name.lower()
    candidates = (
        name_lc,
        _sanitise_vec_name(name_lc),
        f"v({name_lc})",
        f"i({name_lc})",
    )
    for c in candidates:
        if c in bucket:
            return bucket[c]
    return None


# ── Analysis hierarchy ────────────────────────────────────────────────────────

class Analysis(ABC):
    """One analysis (transient/dc/ac) captured from a testbench."""

    kind: str = ""
    x_axis_label: str = ""
    csv_x_col: str = ""

    def __init__(self, signals: list[str]) -> None:
        self.signals = list(signals)

    @abstractmethod
    def ngspice_inject(self) -> str:
        """Lines spliced into the ``.control`` block before ``.endc``.

        Includes the ``setplot <kind>1`` switch so ``wrdata`` pulls from the
        right vector store. The Jinja2 placeholder is filled per worker call.
        """

    @abstractmethod
    def jinja_var(self) -> str:
        """Name of the Jinja2 variable holding this analysis's tab-file path."""

    @abstractmethod
    def write_tab_from_raw(self, bucket: dict, out_path: str) -> None:
        """VACASK path: serialise this analysis's signals from a parsed .raw
        bucket into a tab file that ``persist_to_csv`` can ingest."""

    @abstractmethod
    def persist_to_csv(self, src_tab: str, dest_csv: str) -> None:
        """Convert the .tab file produced by either engine into the canonical
        per-run CSV layout. Removes the .tab file on success."""


class TransientAnalysis(Analysis):
    kind = "transient"
    x_axis_label = "Time"
    csv_x_col = "time"

    def jinja_var(self) -> str:
        return "tran_out_path"

    def ngspice_inject(self) -> str:
        sigs = " ".join(self.signals)
        return (
            "setplot tran1\n"
            f"wrdata {{{{ {self.jinja_var()} }}}} {sigs}"
        )

    def write_tab_from_raw(self, bucket: dict, out_path: str) -> None:
        x_vec = bucket.get("__x__")
        if x_vec is None:
            x_vec = bucket.get("time")
        if x_vec is None:
            return
        y_vecs: list[np.ndarray] = []
        for sig in self.signals:
            v = _lookup_signal(bucket, sig)
            if v is None:
                v = np.zeros_like(np.asarray(x_vec, dtype=float))
            y_vecs.append(np.asarray(v, dtype=float).real)
        _write_tab_columns(out_path, x_vec, y_vecs)

    def persist_to_csv(self, src_tab: str, dest_csv: str) -> None:
        try:
            df = _read_tab(src_tab)
            if df is None:
                return
            ncols = len(df.columns)
            n_sigs = len(self.signals)
            result = pd.DataFrame()
            result[self.csv_x_col] = df.iloc[:, 0]
            if ncols >= 2 * n_sigs and n_sigs > 0:
                # Paired layout: x sig0 x sig1 ...
                for i, sig in enumerate(self.signals):
                    col_idx = 2 * i + 1
                    if col_idx < ncols:
                        result[sig] = df.iloc[:, col_idx]
            else:
                # Single-X layout: x sig0 sig1 ...
                cols = min(ncols - 1, n_sigs)
                for i in range(cols):
                    result[self.signals[i]] = df.iloc[:, i + 1]
            os.makedirs(os.path.dirname(dest_csv), exist_ok=True)
            result.to_csv(dest_csv, index=False)
        except Exception as exc:
            log.warning("Could not persist %s data %s → %s: %s",
                        self.kind, src_tab, dest_csv, exc)
        finally:
            try:
                os.remove(src_tab)
            except OSError:
                pass


class DCSweepAnalysis(Analysis):
    kind = "dc"
    x_axis_label = "Sweep"
    csv_x_col = "sweep"

    def jinja_var(self) -> str:
        return "dc_out_path"

    def ngspice_inject(self) -> str:
        sigs = " ".join(self.signals)
        return (
            "setplot dc1\n"
            f"wrdata {{{{ {self.jinja_var()} }}}} {sigs}"
        )

    def write_tab_from_raw(self, bucket: dict, out_path: str) -> None:
        x_vec = bucket.get("__x__")
        if x_vec is None:
            return
        y_vecs: list[np.ndarray] = []
        for sig in self.signals:
            v = _lookup_signal(bucket, sig)
            if v is None:
                v = np.zeros_like(np.asarray(x_vec, dtype=float))
            y_vecs.append(np.asarray(v, dtype=float).real)
        _write_tab_columns(out_path, x_vec, y_vecs)

    persist_to_csv = TransientAnalysis.persist_to_csv  # same layout / handling


class ACAnalysis(Analysis):
    """AC small-signal analysis → Bode magnitude (linear V) and phase (deg)."""

    kind = "ac"
    x_axis_label = "Frequency"
    csv_x_col = "frequency"

    def jinja_var(self) -> str:
        return "ac_out_path"

    def ngspice_inject(self) -> str:
        # For each requested signal emit two ngspice vectors (mag + phase),
        # then wrdata them. We name the let-vectors deterministically so the
        # tab file's column order is known.
        lines: list[str] = ["setplot ac1"]
        let_names: list[str] = []
        for sig in self.signals:
            safe = _sanitise_vec_name(sig)
            mag_v = f"_ac_mag_{safe}"
            ph_v = f"_ac_phase_{safe}"
            lines.append(f"let {mag_v} = mag({sig})")
            lines.append(f"let {ph_v} = (180/pi)*ph({sig})")
            let_names.extend([mag_v, ph_v])
        lines.append(f"wrdata {{{{ {self.jinja_var()} }}}} " + " ".join(let_names))
        return "\n".join(lines)

    def write_tab_from_raw(self, bucket: dict, out_path: str) -> None:
        x_vec = bucket.get("__x__")
        if x_vec is None:
            x_vec = bucket.get("frequency") or bucket.get("freq")
        if x_vec is None:
            return
        x_arr = np.asarray(x_vec, dtype=float).real
        y_vecs: list[np.ndarray] = []
        for sig in self.signals:
            v = _lookup_signal(bucket, sig)
            if v is None:
                z = np.zeros_like(x_arr, dtype=complex)
                mag = np.abs(z)
                phase = np.zeros_like(x_arr)
            else:
                z = np.asarray(v, dtype=complex)
                mag = np.abs(z)
                phase = np.degrees(np.angle(z))
            y_vecs.append(mag)
            y_vecs.append(phase)
        _write_tab_columns(out_path, x_arr, y_vecs)

    def persist_to_csv(self, src_tab: str, dest_csv: str) -> None:
        try:
            df = _read_tab(src_tab)
            if df is None:
                return
            ncols = len(df.columns)
            n_sigs = len(self.signals)
            n_yvecs = 2 * n_sigs  # mag + phase per signal
            result = pd.DataFrame()
            result[self.csv_x_col] = df.iloc[:, 0]
            if ncols >= 2 * n_yvecs and n_yvecs > 0:
                # Paired ngspice layout: freq mag0 freq phase0 freq mag1 ...
                col_names: list[str] = []
                for sig in self.signals:
                    col_names.append(f"{sig}_mag")
                    col_names.append(f"{sig}_phase")
                for i, name in enumerate(col_names):
                    col_idx = 2 * i + 1
                    if col_idx < ncols:
                        result[name] = df.iloc[:, col_idx]
            else:
                # Single-X layout: freq mag0 phase0 mag1 phase1 ...
                col_names = []
                for sig in self.signals:
                    col_names.append(f"{sig}_mag")
                    col_names.append(f"{sig}_phase")
                cols = min(ncols - 1, n_yvecs)
                for i in range(cols):
                    result[col_names[i]] = df.iloc[:, i + 1]
            os.makedirs(os.path.dirname(dest_csv), exist_ok=True)
            result.to_csv(dest_csv, index=False)
        except Exception as exc:
            log.warning("Could not persist ac data %s → %s: %s",
                        src_tab, dest_csv, exc)
        finally:
            try:
                os.remove(src_tab)
            except OSError:
                pass


ANALYSIS_KIND_TO_CLASS: dict[str, type[Analysis]] = {
    "transient": TransientAnalysis,
    "dc":        DCSweepAnalysis,
    "ac":        ACAnalysis,
}


SCHEMA_KEY_TO_CLASS: dict[str, type[Analysis]] = {
    "transient_signals": TransientAnalysis,
    "dc_signals":        DCSweepAnalysis,
    "ac_signals":        ACAnalysis,
}
