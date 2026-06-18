# Copyright (c) 2026 Santiago Hofwimmer
"""
netlist_export.py – Export the rendered SPICE netlist for one Monte-Carlo
sample (scatter-plot point), with that sample's parameter values filled in.

Rendering mirrors simulator._simulate_single_case_with_engine(): the
testbench's Jinja2 template is rendered with the sample's parameter dict plus
one ``<kind>_out_path`` variable per declared analysis.

Templates are persisted per run via :func:`persist_templates` (referenced by
the run's ``.meta.json`` ``templates_dir`` field) using the same file naming
as ``simulator.generate_templates`` — so exports from history runs use the
templates that actually produced them, and the directory can equally feed a
re-run. Runs recorded before this existed fall back to the current in-memory
template, which may not match the historical testbench.
"""
from __future__ import annotations

import logging
import os

from jinja2 import StrictUndefined, Template

from chipify import app_config, settings

log = logging.getLogger("chipify.uikit.netlist_export")


def _safe_tb(tb_path: str) -> str:
    """Filesystem-safe testbench name (same as simulator.generate_templates)."""
    return tb_path.replace("/", "__").replace("\\", "__")


def engine_extension(test) -> str:
    """Netlist file extension for *test*'s engine (``.sim`` for vacask, else
    ``.spice``). Uses the testbench's own ``engine`` when set, otherwise the
    global ``simulator_engine`` default.
    """
    name = getattr(test, "engine", None) or app_config.load_config().get(
        "simulator_engine", "ngspice")
    return ".sim" if str(name).strip().lower() == "vacask" else ".spice"


def persist_templates(stim, dest_dir: str) -> str:
    """Write every test's in-memory Jinja2 template into *dest_dir*.

    File naming matches ``simulator.generate_templates(templates_dir=...)``
    (``<safe_tb><.spice|.sim>``), so the directory is both the faithful
    source for per-sample netlist exports and directly reusable for re-runs.

    Returns *dest_dir* if at least one template was written, else "".
    """
    wrote_any = False
    for test in getattr(stim, "tests", []) or []:
        text = getattr(test, "template_str", "") or ""
        if not text:
            continue
        os.makedirs(dest_dir, exist_ok=True)
        fp = os.path.join(dest_dir, _safe_tb(test.tb_path) + engine_extension(test))
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(text)
        wrote_any = True
    return dest_dir if wrote_any else ""


def resolve_template_text(test, templates_dir: str = "") -> str:
    """Return the Jinja2 netlist template for *test*.

    Resolution order:
    1. The viewed run's persisted templates (*templates_dir* from its meta
       sidecar) — faithful even when the testbench changed since.
    2. The in-memory template of the current session.
    3. The ``<stem>.spice|.sim`` file in the scratch directory from the last
       netlist generation (same logic as PluginContext.netlists()).
    ``""`` if none exists (no simulation ran in this project yet).
    """
    if templates_dir:
        safe = _safe_tb(test.tb_path)
        for ext in (".spice", ".sim"):
            fp = os.path.join(templates_dir, safe + ext)
            if os.path.isfile(fp):
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        return fh.read()
                except OSError:
                    break

    text = getattr(test, "template_str", "") or ""
    if not text:
        stem = os.path.splitext(os.path.basename(test.tb_path))[0]
        for ext in (".spice", ".sim"):
            fp = os.path.join(settings.FAST_TMP, stem + ext)
            if os.path.isfile(fp):
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError:
                    text = ""
                break
    return text


def render_netlist_for_row(test, row_dict: dict, run_id: str,
                           templates_dir: str = "") -> str:
    """Render *test*'s netlist template with one sample's parameter values.

    *row_dict* is the full results row — extra keys (measurements, pass
    flags) are harmless to Jinja2; it is passed positionally because some
    column names (tb_path-derived) are not valid Python identifiers.
    """
    text = resolve_template_text(test, templates_dir)
    if not text:
        raise ValueError(
            "No netlist template available — run a simulation first."
        )
    ctx = dict(row_dict)
    for an in getattr(test, "analyses", []) or []:
        # Stand-in output paths for the wrdata targets of the original run.
        ctx[an.jinja_var()] = f"run_{run_id}_{an.kind}.tab"
    return Template(text, undefined=StrictUndefined).render(ctx)
