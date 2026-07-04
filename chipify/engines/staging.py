# Copyright (c) 2026 Santiago Hofwimmer
"""
staging.py – Stage project support files into FAST_TMP before a sweep.

Simulators run with ``cwd=FAST_TMP`` (RAM-backed on typical Linux/Docker
setups), so model libraries and engine-specific support files must be
mirrored there. Engine-specific extras are staged via each engine's
``stage_extra_files()`` hook.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from chipify import settings
from chipify.engines.base import BaseSimulator

log = logging.getLogger("chipify.engines.staging")


def staged_copy_is_stale(src: str | os.PathLike[str],
                         dest: str | os.PathLike[str]) -> bool:
    """True if *dest* is missing or differs from *src* (size or older mtime).

    ``shutil.copy2`` preserves mtime, so an up-to-date staged copy has the
    same size and an mtime within filesystem resolution of the source.
    """
    try:
        s = Path(src).stat()
        d = Path(dest).stat()
    except OSError:
        return True
    return s.st_size != d.st_size or s.st_mtime > d.st_mtime + 1.0


def stage_files_to_ram(engines=None) -> None:
    """Stage library/model files into FAST_TMP.

    Always copies the project's *.lib/*.mod/*.inc from WORK_DIR. Files are
    re-copied whenever the source changed — FAST_TMP isn't cleaned between
    runs, so a skip-if-exists policy would let a stale cached copy mask
    edits to model files. *engines* may be a single engine, an iterable of
    engines, or None; every engine's ``stage_extra_files()`` hook is run once
    per engine class — used by VacaskSimulator to mirror OSDI compact-model
    objects so the netlist's ``load "*.osdi"`` directives resolve relative to
    FAST_TMP. A mixed-engine sweep therefore stages the extras for every
    engine it uses.
    """
    work_dir = Path(settings.WORK_DIR)
    fast_tmp = Path(settings.FAST_TMP)
    log.info("Staging library files to RAM disk: %s", fast_tmp)
    for pattern in ("*.lib", "*.mod", "*.inc"):
        for file_path in work_dir.glob(pattern):
            dest_path = fast_tmp / file_path.name
            if staged_copy_is_stale(file_path, dest_path):
                try:
                    shutil.copy2(file_path, dest_path)
                    log.debug("Staged: %s", file_path.name)
                except Exception as exc:
                    log.warning("Could not stage %s: %s", file_path.name, exc)

    # Stage tb/xschemrc (project-local xschem rc, no leading dot) so xschem
    # picks up XSCHEM_LIBRARY_PATH etc. and can resolve the DUT during
    # netlisting. Overwrite each run — FAST_TMP isn't cleaned between runs,
    # so a stale cached copy would mask edits.
    xschemrc_src = Path(settings.TB_DIR) / "xschemrc"
    if xschemrc_src.is_file():
        xschemrc_dest = fast_tmp / "xschemrc"
        try:
            shutil.copy2(xschemrc_src, xschemrc_dest)
            log.info("Staged tb/xschemrc → %s", xschemrc_dest)
        except Exception as exc:
            log.warning("Could not stage tb/xschemrc: %s", exc)
    else:
        log.debug("No tb/xschemrc to stage (looked at %s)", xschemrc_src)

    if engines is None:
        staged: list = []
    elif isinstance(engines, BaseSimulator):
        staged = [engines]
    else:
        staged = list(engines)
    seen: set = set()
    for eng in staged:
        if eng is None or type(eng).__name__ in seen:
            continue
        seen.add(type(eng).__name__)
        if hasattr(eng, "stage_extra_files"):
            eng.stage_extra_files()
