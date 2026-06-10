"""
project_config.py – Optional per-project configuration for Chipify.

A ``project.yaml`` file placed in the project root (alongside ``in/``)
lets teams share consistent defaults without touching ``settings.json``.

Schema (all fields optional)
-----------------------------
name: My IC Project
description: Short description shown in the GUI title bar.
default_datasheet: datasheet.yaml   # pre-selected YAML on startup
default_report_profile: datasheet   # compact | datasheet | deep-dive
default_num_cores: 4
default_tags: [nightly, tape-out-v2]
notes: |
  Multi-line freetext shown in the Settings dialog.

Inheritance
-----------
``app_config.load_config()`` values always win over ``project.yaml`` defaults
(user-local settings take precedence over project-level defaults).
``project.yaml`` in turn wins over ``app_config.DEFAULTS``.

Usage
-----
    from chipify import project_config

    pc = project_config.load()
    print(pc.get("name", "Chipify"))
    print(pc.get("default_num_cores", None))
"""

from __future__ import annotations

import logging
import os

import yaml

from chipify import settings

log = logging.getLogger("chipify.project_config")

PROJECT_FILE = os.path.join(settings.PROJECT_ROOT, "project.yaml")

_ALLOWED_KEYS = {
    "name",
    "description",
    "default_datasheet",
    "default_report_profile",
    "default_num_cores",
    "default_tags",
    "notes",
}


def load() -> dict:
    """
    Load ``project.yaml`` from the project root.

    Returns an empty dict if the file does not exist or cannot be parsed.
    """
    if not os.path.exists(PROJECT_FILE):
        return {}
    try:
        with open(PROJECT_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # silently drop unknown keys to avoid leaking unrelated YAML
        return {k: v for k, v in data.items() if k in _ALLOWED_KEYS}
    except Exception as exc:
        log.warning("Could not read project.yaml: %s", exc)
        return {}


def save(data: dict) -> bool:
    """Write *data* to ``project.yaml``. Returns True on success."""
    try:
        clean = {k: v for k, v in data.items() if k in _ALLOWED_KEYS}
        with open(PROJECT_FILE, "w", encoding="utf-8") as f:
            yaml.dump(clean, f, default_flow_style=False, allow_unicode=True)
        return True
    except Exception as exc:
        log.warning("Could not write project.yaml: %s", exc)
        return False
