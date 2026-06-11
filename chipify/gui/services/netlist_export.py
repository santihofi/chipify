"""
netlist_export.py – Export the rendered SPICE netlist for one Monte-Carlo
sample (scatter-plot point), with that sample's parameter values filled in.

Rendering mirrors simulator._simulate_single_case_with_engine(): the
testbench's Jinja2 template is rendered with the sample's parameter dict plus
one ``<kind>_out_path`` variable per declared analysis. Limitation: when an
old history run is viewed, the *current* template (in-memory or from the last
netlist generation) is used — it may not match the historical testbench.
"""
from __future__ import annotations

import logging
import os

from jinja2 import StrictUndefined, Template

from chipify import app_config, settings

log = logging.getLogger("chipify.gui.netlist_export")


def resolve_template_text(test) -> str:
    """Return the Jinja2 netlist template for *test*.

    Prefers the in-memory template of the current run; falls back to the
    ``<stem>.spice|.sim`` file in the scratch directory from the last netlist
    generation (same logic as PluginContext.netlists()). ``""`` if neither
    exists (no simulation ran in this project yet).
    """
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


def render_netlist_for_row(test, row_dict: dict, run_id: str) -> str:
    """Render *test*'s netlist template with one sample's parameter values.

    *row_dict* is the full results row — extra keys (measurements, pass
    flags) are harmless to Jinja2; it is passed positionally because some
    column names (tb_path-derived) are not valid Python identifiers.
    """
    text = resolve_template_text(test)
    if not text:
        raise ValueError(
            "No netlist template available — run a simulation first."
        )
    ctx = dict(row_dict)
    for an in getattr(test, "analyses", []) or []:
        # Stand-in output paths for the wrdata targets of the original run.
        ctx[an.jinja_var()] = f"run_{run_id}_{an.kind}.tab"
    return Template(text, undefined=StrictUndefined).render(ctx)


def _export_via_dialog(parent_widget, test, row) -> None:
    from tkinter import filedialog, messagebox

    run_id = str(row.get("run_id", row.name)).zfill(6)
    engine = app_config.load_config().get("simulator_engine", "ngspice")
    ext = ".sim" if engine == "vacask" else ".spice"
    stem = os.path.splitext(os.path.basename(test.tb_path))[0]

    try:
        rendering = render_netlist_for_row(test, dict(row), run_id)
    except Exception as exc:
        messagebox.showerror("Netlist Export", str(exc), parent=parent_widget)
        return

    path = filedialog.asksaveasfilename(
        parent=parent_widget,
        title=f"Export netlist for run #{run_id}",
        initialfile=f"run_{run_id}_{stem}{ext}",
        defaultextension=ext,
        filetypes=[("SPICE netlist", f"*{ext}"), ("All files", "*.*")],
    )
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(rendering)
    except OSError as exc:
        messagebox.showerror("Netlist Export", f"Could not write file:\n{exc}",
                             parent=parent_widget)
        return
    log.info("Exported netlist for run %s to %s", run_id, path)


def show_export_menu(canvas_widget, mpl_event, stim, row) -> None:
    """Open a small context menu at the clicked scatter point offering a
    netlist export per testbench."""
    import tkinter as tk

    tests = list(getattr(stim, "tests", []) or []) if stim is not None else []
    if not tests:
        return

    run_id = str(row.get("run_id", row.name)).zfill(6)
    menu = tk.Menu(canvas_widget, tearoff=0)
    for test in tests:
        menu.add_command(
            label=f"Export netlist {test.tb_path} (run #{run_id})…",
            command=lambda t=test: _export_via_dialog(canvas_widget, t, row),
        )

    gui_event = getattr(mpl_event, "guiEvent", None)
    if gui_event is not None and hasattr(gui_event, "x_root"):
        x, y = gui_event.x_root, gui_event.y_root
    else:
        # mpl y is measured from the bottom of the canvas.
        x = canvas_widget.winfo_rootx() + int(mpl_event.x)
        y = canvas_widget.winfo_rooty() + canvas_widget.winfo_height() - int(mpl_event.y)
    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()
