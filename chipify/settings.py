# settings.py
"""Project path configuration.

Folder locations are read from ``settings.json`` in the project root (the
current working directory). Any path key that is missing or blank falls back
to the default folder structure under the project root. Paths are resolved
once at import, so edits to ``settings.json`` take effect on the next launch.

Configurable keys (in ``settings.json``):
    in_dir    – input datasheets    (default: ``datasheets/``)
    out_dir   – simulation output   (default: ``out/``)
    work_dir  – scratch / temp      (default: ``tmp/``)
    tb_dir    – testbench files     (default: ``tb/``)

Relative paths are resolved against the project root; absolute paths are used
as-is. ``FAST_TMP`` (volatile RAM scratch for Linux/Docker) is not configurable.
"""
import json
import logging
import os
from typing import Any

log = logging.getLogger("chipify.settings")

# The directory chipify was launched from — anchor for relative paths.
PROJECT_ROOT = os.getcwd()

# settings.json lives in the project root (the same file app_config reads/writes).
_CONFIG_PATH = os.path.join(PROJECT_ROOT, "settings.json")

# Default folder layout, relative to PROJECT_ROOT.
_DEFAULT_DIRS = {
    "in_dir": "datasheets",
    "out_dir": "out",
    "work_dir": "tmp",
    "tb_dir": "tb",
}


def _load_path_overrides() -> dict[str, Any]:
    """Read folder-path overrides from settings.json (``{}`` if absent/unreadable).

    Kept self-contained (no ``app_config`` import) because ``app_config`` imports
    this module — reading the JSON inline avoids a circular import.
    """
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_dir(key: str, overrides: dict[str, Any]) -> str:
    """Return the absolute path for *key*, honouring a settings.json override.

    Uses the override when it is a non-empty string (resolved against
    ``PROJECT_ROOT`` if relative); otherwise falls back to the default folder.
    The resulting directory is created. If a configured custom path cannot be
    created, a warning is logged and the default folder is used instead.
    """
    default_abs = os.path.join(PROJECT_ROOT, _DEFAULT_DIRS[key])

    raw = overrides.get(key)
    if isinstance(raw, str) and raw.strip():
        custom = raw.strip()
        if not os.path.isabs(custom):
            custom = os.path.join(PROJECT_ROOT, custom)
        try:
            os.makedirs(custom, exist_ok=True)
            return custom
        except OSError as exc:
            log.warning(
                "Could not create configured %s=%r (%s); using default %s",
                key, raw, exc, default_abs,
            )

    os.makedirs(default_abs, exist_ok=True)
    return default_abs


_overrides = _load_path_overrides()

IN_DIR = _resolve_dir("in_dir", _overrides)
OUT_DIR = _resolve_dir("out_dir", _overrides)
WORK_DIR = _resolve_dir("work_dir", _overrides)
TB_DIR = _resolve_dir("tb_dir", _overrides)

# Volatile RAM scratch space (kept absolute for Linux/Docker); not configurable.
FAST_TMP = "/tmp/sim_work/"
os.makedirs(FAST_TMP, exist_ok=True)
