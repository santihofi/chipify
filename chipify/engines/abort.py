# Copyright (c) 2026 Santiago Hofwimmer
"""
abort.py – File-based abort flag shared by the orchestrator and all engines.

The flag lives in FAST_TMP (namespaced per project, see settings.py) so the
GUI/CLI process can stop worker processes it cannot signal directly: workers
poll :func:`is_aborted` between progress ticks and while their simulator
subprocess runs.
"""
from __future__ import annotations

import logging
import os

from chipify import settings

log = logging.getLogger("chipify.engines.abort")

ABORT_FLAG_PATH = os.path.join(settings.FAST_TMP, "abort.flag")


def is_aborted() -> bool:
    return os.path.exists(ABORT_FLAG_PATH)


def clear_abort_flag() -> None:
    if os.path.exists(ABORT_FLAG_PATH):
        try:
            os.remove(ABORT_FLAG_PATH)
        except Exception:
            pass


def abort_simulation() -> None:
    log.info("abort_simulation() called – writing abort flag.")
    try:
        with open(ABORT_FLAG_PATH, "w", encoding="utf-8") as f:
            f.write("abort")
    except Exception as exc:
        log.error("Could not write abort flag: %s", exc)
