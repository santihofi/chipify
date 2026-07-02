# Copyright (c) 2026 Santiago Hofwimmer
"""
rawfile.py – SPICE-format .raw waveform reader, shared across engines.

Handles the rawfile format that ngspice, VACASK and Spectre-compatible
simulators write: an ASCII header (Title/Plotname/Flags/No. Variables/
No. Points), a Variables section, then either ``Values:`` (ASCII) or
``Binary:`` data. A PyOPUS rawfile reader is preferred when installed;
the built-in parser is the fallback.

New engines whose simulator emits SPICE rawfiles can build their result
extraction on :func:`read_raw_file` directly.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("chipify.engines.rawfile")

_RE_SANITISE = re.compile(r"[^a-zA-Z0-9_]")


def sanitise_key(name: str) -> str:
    """Turn a SPICE signal name like v(out) into a Python identifier v_out_."""
    return _RE_SANITISE.sub("_", name)


def parse_raw_token(tok: str):
    """Parse one ASCII raw-file value token.

    Real values are plain floats; complex values are written as ``re,im``.
    Returns float, complex, or None if the token is not numeric.
    """
    if "," in tok:
        re_s, _, im_s = tok.partition(",")
        try:
            return complex(float(re_s), float(im_s))
        except ValueError:
            return None
    try:
        return float(tok)
    except ValueError:
        return None


def parse_ascii_raw(raw_file: str) -> dict:
    """Parse a SPICE-format .raw file (binary or ASCII).

    Handles the format ngspice and vacask both write: an ASCII header
    (Title/Plotname/Flags/No. Variables/No. Points), a Variables section,
    then either ``Values:`` (ASCII) or ``Binary:`` followed by little-endian
    float64 data (or complex128 if Flags contains ``complex``).
    """
    import numpy as np

    var_names: list[str] = []
    n_vars = 0
    n_points = 0
    is_complex = False

    with open(raw_file, "rb") as fh:
        section: "str | None" = None
        while True:
            line = fh.readline()
            if not line:
                return {}
            ls = line.decode("utf-8", errors="replace").strip()
            lower = ls.lower()

            if lower.startswith("flags:"):
                is_complex = "complex" in lower
            elif lower.startswith("no. variables:"):
                try:
                    n_vars = int(ls.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
            elif lower.startswith("no. points:"):
                try:
                    n_points = int(ls.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
            elif lower == "variables:":
                section = "variables"
            elif lower == "values:":
                section = "ascii_values"
                break
            elif lower == "binary:":
                section = "binary"
                break
            elif section == "variables":
                # Variable lines: "<idx>\t<name>\t<type>"
                parts = ls.split()
                if len(parts) >= 2:
                    var_names.append(parts[1].lower())

        if section == "binary":
            if n_vars <= 0 or n_points <= 0 or not var_names:
                return {}
            dtype = np.dtype("<c16") if is_complex else np.dtype("<f8")
            count = n_vars * n_points
            blob = fh.read(count * dtype.itemsize)
            data = np.frombuffer(blob, dtype=dtype)
            if data.size != count:
                log.warning(
                    "Binary .raw truncated: expected %d values (%d vars x %d points), got %d.",
                    count, n_vars, n_points, data.size,
                )
                return {}
            data = data.reshape(n_points, n_vars)
            return {var_names[i]: data[:, i].copy()
                    for i in range(min(n_vars, len(var_names)))}

        if section == "ascii_values":
            if n_vars <= 0:
                return {}
            values: list = []
            for raw_line in fh:
                ls = raw_line.decode("utf-8", errors="replace").strip()
                for tok in ls.split():
                    num = parse_raw_token(tok)
                    if num is not None:
                        values.append(num)

            # The SPICE ASCII format prefixes every point with its running
            # index ("0\t<v0>\n\t<v1>…"), giving n_vars+1 tokens per point.
            # Some writers omit the index; detect which layout we have, using
            # the declared point count when available and a 0,1,2,… index
            # heuristic otherwise.
            def _looks_indexed(stride: int) -> bool:
                idx_toks = values[::stride]
                return all(
                    isinstance(v, float) and v.is_integer() and int(v) == i
                    for i, v in enumerate(idx_toks)
                )

            n_tok = len(values)
            stride_idx = n_vars + 1
            if n_points > 0 and n_tok == n_points * stride_idx:
                indexed = True
            elif n_points > 0 and n_tok == n_points * n_vars:
                indexed = False
            elif n_tok % stride_idx == 0 and _looks_indexed(stride_idx):
                indexed = True
            elif n_tok % n_vars == 0:
                indexed = False
            else:
                log.warning(
                    "ASCII raw %s: %d value tokens do not align with %d variables.",
                    raw_file, n_tok, n_vars,
                )
                return {}

            stride = stride_idx if indexed else n_vars
            offset = 1 if indexed else 0
            rows: dict[str, list] = {nm: [] for nm in var_names}
            for start in range(0, n_tok - stride + 1, stride):
                row_vals = values[start + offset: start + stride]
                for i, nm in enumerate(var_names):
                    if i < len(row_vals):
                        rows[nm].append(row_vals[i])
            return {k: np.array(v) for k, v in rows.items() if v}

    return {}


def classify_analysis_kind(xlabel: str, plotname: str = "") -> str:
    """Map a raw-file xlabel / plotname to one of our Analysis.kind values."""
    xl = (xlabel or "").lower()
    pn = (plotname or "").lower()
    if "freq" in xl or "ac" in pn:
        return "ac"
    if "time" in xl or "tran" in pn:
        return "transient"
    return "dc"


def read_raw_file(raw_file: str) -> "dict | None":
    """Read a SPICE-format .raw → {analysis_kind: {signal_name_lower: np.ndarray}}.

    The bucket for each analysis kind also contains a sentinel ``"__x__"`` key
    holding the X-axis vector (time / frequency / sweep parameter) so callers
    don't need to know the X variable's name.

    Returns None if no analyses could be parsed at all. Empty dict on parse
    failure with no error.
    """
    # Preferred: PyOPUS rawfile reader (handles binary + ASCII)
    try:
        from pyopus.simulator.rawfile import RawFile  # type: ignore[import]
    except ImportError as exc:
        log.warning(
            "pyopus.simulator.rawfile import failed: %s. "
            "Vacask .raw files are typically binary (spectre format); install pyopus "
            "to parse them. Falling back to ASCII-only parser.",
            exc,
        )
    else:
        try:
            rf = RawFile(raw_file)
            buckets: dict[str, dict] = {}
            analyses = getattr(rf, "analyses", None) or [rf]
            for an in analyses:
                xvec = getattr(an, "xvec", None)
                xlabel = getattr(an, "xlabel", "") or ""
                plotname = (getattr(an, "name", "")
                            or getattr(an, "plotname", "")
                            or "")
                kind = classify_analysis_kind(xlabel, plotname)
                bucket = buckets.setdefault(kind, {})
                if xvec is not None:
                    bucket["__x__"] = xvec
                    if xlabel:
                        bucket[xlabel.lower()] = xvec
                for sv in getattr(an, "yvec", []):
                    bucket[sv.name.lower()] = sv.data
            if buckets:
                return buckets
            log.warning("pyopus parsed %s but produced no signals.", raw_file)
        except Exception:
            log.warning("pyopus failed to parse %s; trying ASCII fallback.",
                        raw_file, exc_info=True)

    # Fallback: built-in SPICE-format parser (handles binary + ASCII).
    # The ASCII fallback can only see one analysis at a time; classify by
    # looking for time / frequency in the column names.
    try:
        parsed = parse_ascii_raw(raw_file)
    except Exception:
        log.warning("Could not parse raw file %s.", raw_file, exc_info=True)
        return None
    if not parsed:
        log.warning("Raw file %s parsed to 0 signals — unknown format. "
                    "Expected ngspice/vacask SPICE rawfile (Title/Variables/Binary).",
                    raw_file)
        return None

    # Detect X-axis column and classify
    xlabel = ""
    for cand in ("time", "frequency", "freq"):
        if cand in parsed:
            xlabel = cand
            break
    if not xlabel:
        # First inserted column is the X axis for sweep analyses
        xlabel = next(iter(parsed), "")
    kind = classify_analysis_kind(xlabel)
    bucket = dict(parsed)
    if xlabel and xlabel in bucket:
        bucket["__x__"] = bucket[xlabel]
    return {kind: bucket}
