"""
app_config.py – Persistent user preferences for Chipify/Silicrunch.

Config file: settings.json in PROJECT_ROOT (where the app is launched from).
All keys are optional; missing keys fall back to DEFAULTS so the file stays
forward-compatible when new settings are added later.
"""

import os
import json

from chipify import settings

CONFIG_PATH = os.path.join(settings.PROJECT_ROOT, "settings.json")

DEFAULTS: dict = {
    "num_cores": None,  # None → auto-detect via util.get_num_cores()
}


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
            print(f"[app_config] Could not read {CONFIG_PATH}: {exc} – using defaults.")
    return DEFAULTS.copy()


def save_config(config: dict) -> None:
    """Persist *config* to settings.json, overwriting any previous file."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as exc:
        print(f"[app_config] Could not write {CONFIG_PATH}: {exc}")
