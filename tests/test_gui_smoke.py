"""
tests/test_gui_smoke.py

GUI smoke tests: construct the real widgets and pump a few event-loop cycles.
Catches import errors, widget-construction errors, and layout crashes that
the pure-logic tests cannot see (e.g. the dead-hover and dropdown bugs).

Skipped automatically when no display is available (headless CI).
"""
from __future__ import annotations

import pytest


def _display_available() -> bool:
    try:
        import tkinter
        root = tkinter.Tk()
        root.destroy()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _display_available(), reason="no display available"
)


def test_main_window_and_settings_construct():
    from chipify.gui.main_window import ChipifyGUI
    from chipify.gui.widgets.settings_window import SettingsWindow

    app = ChipifyGUI()
    try:
        app.withdraw()
        app.update()
        dlg = SettingsWindow(app)
        app.update()
        # All four tabs must exist (Paths is the newest).
        for name in ("Simulation", "Performance", "Interface", "Paths"):
            dlg._tabs.set(name)
            app.update()
        dlg.destroy()
        app.update()
    finally:
        app.destroy()


def test_scrollable_option_menu_selects():
    import customtkinter as ctk
    from chipify.gui.widgets.scrollable_option_menu import ScrollableOptionMenu

    root = ctk.CTk()
    try:
        root.withdraw()
        fired: list = []
        menu = ScrollableOptionMenu(root, command=fired.append)
        menu.configure(values=[f"v{i}" for i in range(40)])
        menu.set("v0")
        menu.pack()
        root.update()
        menu._open_dropdown_menu()
        root.update()
        assert menu._popup is not None
        menu._choose("v7")
        root.update()
        assert fired == ["v7"]
        assert menu.get() == "v7"
        assert menu._popup is None
    finally:
        root.destroy()


def test_export_menu_is_ctk_and_closes():
    import customtkinter as ctk
    import pandas as pd
    from chipify.gui.services import netlist_export

    class _Test:
        tb_path = "tb_amp"
        template_str = "x {{ vdd }}"
        analyses: list = []

    class _Stim:
        tests = [_Test()]

    class _Evt:
        guiEvent = None
        x, y = 10, 10

    root = ctk.CTk()
    try:
        root.withdraw()
        anchor = ctk.CTkLabel(root, text="plot")
        anchor.pack()
        root.update()

        row = pd.Series({"run_id": "000003", "vdd": 1.8}, name=3)
        netlist_export.show_export_menu(anchor, _Evt(), _Stim(), row)
        root.update()
        menu = netlist_export._menu_state["menu"]
        assert menu is not None and menu.winfo_exists()
        btns = [c for c in menu.winfo_children() if isinstance(c, ctk.CTkButton)]
        assert len(btns) == 1
        assert "run #000003" in btns[0].cget("text")
        netlist_export._close_export_menu()
        assert netlist_export._menu_state["menu"] is None
    finally:
        netlist_export._menu_state["menu"] = None
        root.destroy()


def test_run_annotation_dialog_saves_meta(tmp_path):
    import customtkinter as ctk
    from chipify import run_meta
    from chipify.gui.widgets.run_annotation_dialog import RunAnnotationDialog

    csv = tmp_path / "run_20260611_120000.csv"
    csv.write_text("run_id,sim_error\n000001,None\n", encoding="utf-8")
    root = ctk.CTk()
    try:
        root.withdraw()
        dlg = RunAnnotationDialog(root, csv.name, str(csv))
        root.update()
        dlg._notes_box.insert("1.0", "smoke note ")
        dlg._tags_var.set("a, b")
        dlg._save()
        root.update()
    finally:
        root.destroy()
    meta = run_meta.read_meta(str(csv))
    assert meta.get("tags") == ["a", "b"]
    assert "smoke note" in meta.get("notes", "")
