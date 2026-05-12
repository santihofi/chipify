"""
app_config.py – Persistent user preferences + application-wide logging setup.

Config file : settings.json  in PROJECT_ROOT
Log file    : out/chipify.log (rotating, max 2 MB × 3 files)
"""

import os
import json
import logging
import logging.handlers
from typing import Any

from chipify import settings

CONFIG_PATH = os.path.join(settings.PROJECT_ROOT, "settings.json")
LOG_PATH    = os.path.join(settings.OUT_DIR, "chipify.log")

DEFAULTS: dict[str, Any] = {
    "num_cores": None,                # None → auto-detect via util.get_num_cores()
    "simulator_engine": "ngspice",    # ngspice|vacask
    "vacask_binary": "vacask",        # path or PATH-resolvable name
    "vacask_netlist_source": "xschem",# xschem|ng2vc
    "vacask_pdk_dir": "/foss/pdks/ihp-sg13g2/libs.tech/vacask",  # contains osdi/ and models/
    "process_start_method": "auto",   # auto|forkserver|spawn
    "chunk_size": "auto",             # auto|1|2|4|8|16|32|64|128|256
    "live_plotting_enabled": False,   # off by default — avoids Tk/worker coupling cost
    "live_plot_throttle_ms": 1500,    # min ms between plot redraws (500–5000)
    "live_plot_emit_stride": 1,       # emit GUI chunks every N pool batches (1 = every batch)
    "custom_equations": [],           # [{"name": "eff", "expr": "p_out / p_in * 100"}, ...]
    "transient_equations": [],        # [{"name": "vdiff", "expr": "v(outp) - v(outn)"}, ...]
    "multiplot_config": [],           # persisted PlotCell configs for Multi-Plot Dashboard
    "theme": "night",                 # appearance theme: night|dark|light
}

_logging_ready = False
_config_cache: dict[str, Any] | None = None
_config_mtime: float | None = None


def setup_logging(level: int = logging.DEBUG) -> None:
    """
    Initialise the root 'chipify' logger once.
    Safe to call multiple times – subsequent calls are no-ops.
    """
    global _logging_ready
    if _logging_ready:
        return

    os.makedirs(settings.OUT_DIR, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler – 2 MB per file, keep 3 backups
    fh = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler – INFO and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    root = logging.getLogger("chipify")
    root.setLevel(level)
    root.addHandler(fh)
    root.addHandler(ch)
    root.propagate = False

    root.info("=" * 60)
    root.info("Chipify logging initialised  →  %s", LOG_PATH)
    root.info("=" * 60)

    _logging_ready = True


# ── Config persistence ────────────────────────────────────────────────────────

def load_config() -> dict[str, Any]:
    """
    Return the merged config (cached; invalidated when settings.json mtime changes).

    Priority (highest wins): settings.json  >  project.yaml defaults  >  DEFAULTS.
    """
    global _config_cache, _config_mtime

    current_mtime: float | None = None
    if os.path.exists(CONFIG_PATH):
        try:
            current_mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            pass

    if _config_cache is not None and current_mtime == _config_mtime:
        return _config_cache.copy()

    merged = DEFAULTS.copy()

    try:
        from chipify import project_config
        proj = project_config.load()
        _key_map = {
            "default_num_cores":      "num_cores",
            "default_report_profile": "pdf_profile",
        }
        for proj_key, cfg_key in _key_map.items():
            if proj_key in proj and merged.get(cfg_key) is None:
                merged[cfg_key] = proj[proj_key]
    except Exception:
        pass

    if current_mtime is not None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged.update(data)
        except Exception as exc:
            logging.getLogger("chipify.config").warning(
                "Could not read %s: %s – using defaults.", CONFIG_PATH, exc
            )

    _config_cache = merged
    _config_mtime = current_mtime
    return merged.copy()


def save_config(config: dict[str, Any]) -> None:
    """Persist *config* to settings.json, overwriting any previous file."""
    global _config_cache, _config_mtime
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        _config_cache = None
        _config_mtime = None
    except Exception as exc:
        logging.getLogger("chipify.config").error(
            "Could not write %s: %s", CONFIG_PATH, exc
        )


def save_config_key(key: str, value: Any) -> None:
    """Update a single config key and persist."""
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)


def is_live_plotting_enabled() -> bool:
    """Return whether live plotting is enabled in the current config."""
    cfg = load_config()
    return bool(cfg.get("live_plotting_enabled", False))


def get_live_throttle_ms() -> int:
    """Return the live-plot throttle interval in milliseconds."""
    cfg = load_config()
    raw = cfg.get("live_plot_throttle_ms", 1500)
    try:
        return max(500, min(5000, int(raw)))
    except (TypeError, ValueError):
        return 1500


def get_live_plot_emit_stride() -> int:
    """Emit live-plot chunks once every N completed pool batches (minimum 1)."""
    cfg = load_config()
    raw = cfg.get("live_plot_emit_stride", 1)
    try:
        return max(1, min(64, int(raw)))
    except (TypeError, ValueError):
        return 1
