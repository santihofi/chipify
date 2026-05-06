"""
run_meta.py – Sidecar metadata for simulation history runs.

For every `run_<ts>.csv` saved in `out/history/`, a companion
`run_<ts>.meta.json` file can be written and read.

Schema (v1)
-----------
{
  "schema_version": 1,
  "timestamp":      "2026-05-06T15:00:00",
  "yaml":           "datasheet.yaml",
  "host":           "mypc",
  "python":         "3.12.3",
  "ngspice":        "40",          // best-effort, "" if not found
  "git_commit":     "a1b2c3d",     // best-effort, "" if not in a repo
  "duration_s":     42.1,
  "total_runs":     500,
  "valid_runs":     497,
  "global_yield":   99.4,
  "notes":          "",
  "tags":           []
}

All fields except `schema_version` and `timestamp` are optional /
best-effort so older code loading new meta files does not crash.
"""

from __future__ import annotations
import json
import os
import platform
import subprocess
import sys
import datetime
import logging

log = logging.getLogger("chipify.run_meta")

_SCHEMA_VERSION = 1


# ── helpers ───────────────────────────────────────────────────────────────────

def _ngspice_version() -> str:
    try:
        result = subprocess.run(
            ["ngspice", "--version"], capture_output=True, text=True, timeout=5
        )
        first = (result.stdout or result.stderr or "").splitlines()[0]
        return first.strip()
    except Exception:
        return ""


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _meta_path(csv_path: str) -> str:
    """Given a run CSV path, return the companion .meta.json path."""
    base, _ = os.path.splitext(csv_path)
    return base + ".meta.json"


# ── public API ────────────────────────────────────────────────────────────────

def write_meta(
    csv_path: str,
    *,
    yaml_name: str = "",
    duration_s: float | None = None,
    total_runs: int | None = None,
    valid_runs: int | None = None,
    global_yield: float | None = None,
    tran_dir: str = "",
) -> str:
    """
    Write a sidecar .meta.json next to *csv_path*.

    Returns the path written, or "" on failure.
    """
    meta: dict = {
        "schema_version": _SCHEMA_VERSION,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "yaml": yaml_name,
        "host": platform.node(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "ngspice": _ngspice_version(),
        "git_commit": _git_commit(),
        "duration_s": duration_s,
        "total_runs": total_runs,
        "valid_runs": valid_runs,
        "global_yield": global_yield,
        "tran_dir": tran_dir,
        "notes": "",
        "tags": [],
    }
    path = _meta_path(csv_path)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        log.info("Wrote run metadata: %s", path)
        return path
    except Exception as exc:
        log.warning("Could not write run metadata %s: %s", path, exc)
        return ""


def read_meta(csv_path: str) -> dict:
    """
    Load the sidecar .meta.json for *csv_path*.

    Returns an empty dict if the file does not exist or cannot be parsed.
    """
    path = _meta_path(csv_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        log.warning("Could not read run metadata %s: %s", path, exc)
        return {}


def update_meta(csv_path: str, **fields) -> bool:
    """
    Merge *fields* into an existing .meta.json (or create a minimal one).
    Returns True on success.
    """
    meta = read_meta(csv_path) or {
        "schema_version": _SCHEMA_VERSION,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    meta.update(fields)
    path = _meta_path(csv_path)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return True
    except Exception as exc:
        log.warning("Could not update run metadata %s: %s", path, exc)
        return False
