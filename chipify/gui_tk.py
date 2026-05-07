"""
gui_tk.py – Backward-compatibility shim.

All real code has moved to ``chipify.gui.main_window``.
This module is kept so that existing scripts and cli.py that do
``from chipify import gui_tk; gui_tk.main()`` continue to work without change.
"""
# noqa: F401
from chipify.gui.main_window import main, SimifyGUI, set_btn_start_ready  # noqa: F401
