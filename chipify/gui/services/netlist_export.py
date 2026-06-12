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

log = logging.getLogger("chipify.gui.netlist_export")


def _safe_tb(tb_path: str) -> str:
    """Filesystem-safe testbench name (same as simulator.generate_templates)."""
    return tb_path.replace("/", "__").replace("\\", "__")


def persist_templates(stim, dest_dir: str) -> str:
    """Write every test's in-memory Jinja2 template into *dest_dir*.

    File naming matches ``simulator.generate_templates(templates_dir=...)``
    (``<safe_tb><.spice|.sim>``), so the directory is both the faithful
    source for per-sample netlist exports and directly reusable for re-runs.

    Returns *dest_dir* if at least one template was written, else "".
    """
    engine = app_config.load_config().get("simulator_engine", "ngspice")
    ext = ".sim" if engine == "vacask" else ".spice"
    wrote_any = False
    for test in getattr(stim, "tests", []) or []:
        text = getattr(test, "template_str", "") or ""
        if not text:
            continue
        os.makedirs(dest_dir, exist_ok=True)
        fp = os.path.join(dest_dir, _safe_tb(test.tb_path) + ext)
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


def _export_via_dialog(parent_widget, test, row, templates_dir: str = "") -> None:
    from tkinter import filedialog, messagebox

    run_id = str(row.get("run_id", row.name)).zfill(6)
    engine = app_config.load_config().get("simulator_engine", "ngspice")
    ext = ".sim" if engine == "vacask" else ".spice"
    stem = os.path.splitext(os.path.basename(test.tb_path))[0]

    try:
        rendering = render_netlist_for_row(test, dict(row), run_id, templates_dir)
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


# The export context menu is a CTkFrame place()-d inside the canvas's
# toplevel — NOT a native tk.Menu: tk_popup + grab_release can leave the menu
# posted without a grab, so it lingered and resurfaced on window-focus
# changes. Only one menu is open at a time, app-wide.
_menu_state: dict = {"menu": None}


def _close_export_menu(_event=None) -> None:
    menu = _menu_state["menu"]
    if menu is not None:
        _menu_state["menu"] = None
        try:
            menu.destroy()
        except Exception:
            pass


def _ensure_menu_bindings(root) -> None:
    """Register the app-global close bindings once per Tk root."""
    if getattr(root, "_chipify_export_menu_bound", False):
        return
    root._chipify_export_menu_bound = True

    def _on_global_click(event):
        menu = _menu_state["menu"]
        if menu is None:
            return
        # The click that opened the menu also reaches this "all"-tag
        # handler (it runs after the widget-tag mpl binding) — skip it.
        if getattr(menu, "_opening_click", False):
            menu._opening_click = False
            return
        try:
            w = str(event.widget)
        except Exception:
            w = ""
        path = str(menu)
        if w == path or w.startswith(path + "."):
            return
        _close_export_menu()

    def _on_configure(event):
        menu = _menu_state["menu"]
        if menu is not None and event.widget is menu.winfo_toplevel():
            _close_export_menu()

    root.bind_all("<Button-1>", _on_global_click, add="+")
    root.bind_all("<Button-3>", _on_global_click, add="+")
    root.bind_all("<Escape>", _close_export_menu, add="+")
    root.bind_all("<Configure>", _on_configure, add="+")


def show_export_menu(canvas_widget, mpl_event, stim, row,
                     templates_dir: str = "") -> None:
    """Open a small CTk-styled context menu at the clicked scatter point
    offering a netlist export per testbench. *templates_dir* is the viewed
    run's persisted-template directory (from its meta sidecar), "" for none."""
    import customtkinter as ctk

    tests = list(getattr(stim, "tests", []) or []) if stim is not None else []
    if not tests:
        return

    _close_export_menu()
    top = canvas_widget.winfo_toplevel()
    _ensure_menu_bindings(top)

    run_id = str(row.get("run_id", row.name)).zfill(6)
    menu = ctk.CTkFrame(top, corner_radius=6, border_width=1)

    def _pick(test):
        _close_export_menu()
        _export_via_dialog(canvas_widget, test, row, templates_dir)

    for test in tests:
        ctk.CTkButton(
            menu, text=f"Export netlist {test.tb_path} (run #{run_id})…",
            anchor="w", height=26, fg_color="transparent",
            command=lambda t=test: _pick(t),
        ).pack(fill="x", padx=4, pady=2)

    gui_event = getattr(mpl_event, "guiEvent", None)
    if gui_event is not None and hasattr(gui_event, "x_root"):
        x = gui_event.x_root - top.winfo_rootx()
        y = gui_event.y_root - top.winfo_rooty()
    else:
        # mpl y is measured from the bottom of the canvas.
        x = canvas_widget.winfo_rootx() - top.winfo_rootx() + int(mpl_event.x)
        y = (canvas_widget.winfo_rooty() - top.winfo_rooty()
             + canvas_widget.winfo_height() - int(mpl_event.y))

    menu.update_idletasks()
    x = max(0, min(x, top.winfo_width() - menu.winfo_reqwidth()))
    y = max(0, min(y, top.winfo_height() - menu.winfo_reqheight()))
    menu.place(x=x, y=y)
    menu.lift()
    menu._opening_click = True
    _menu_state["menu"] = menu
