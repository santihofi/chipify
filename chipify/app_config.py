"""
app_config.py – Persistent user preferences + application-wide logging setup.

Config file : settings.json  in PROJECT_ROOT
Log file    : out/chipify.log (rotating, max 2 MB × 3 files)
"""

import os
import json
import logging
import logging.handlers

from chipify import settings

CONFIG_PATH = os.path.join(settings.PROJECT_ROOT, "settings.json")
LOG_PATH    = os.path.join(settings.OUT_DIR, "chipify.log")

DEFAULTS: dict = {
    "num_cores": None,  # None → auto-detect via util.get_num_cores()
}

_logging_ready = False


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

def load_config() -> dict:
    """Return the merged config (file values on top of DEFAULTS)."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = DEFAULTS.copy()
            merged.update(data)
            return merged
        except Exception as exc:
            logging.getLogger("chipify.config").warning(
                "Could not read %s: %s – using defaults.", CONFIG_PATH, exc
            )
    return DEFAULTS.copy()


def save_config(config: dict) -> None:
    """Persist *config* to settings.json, overwriting any previous file."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as exc:
        logging.getLogger("chipify.config").error(
            "Could not write %s: %s", CONFIG_PATH, exc
        )
