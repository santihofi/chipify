"""
scrollable_option_menu.py – CTkOptionMenu drop-in with a scrollable dropdown.

The stock CTkOptionMenu uses a native tk.Menu for its dropdown, which renders
every entry at once — with hundreds of history runs it grows past the screen.
This subclass overrides only the internal ``_open_dropdown_menu`` hook (called
from ``CTkOptionMenu._clicked``) and shows a scrollable list capped at
``max_popup_height`` instead. Everything else (values/state configure,
set/get/cget, variable binding, command callback, theming) is inherited.

The list is a CTkFrame ``place()``-d inside the owner toplevel — NOT a
Toplevel: an ``overrideredirect`` CTkToplevel needs focus/grab tricks to see
real mouse clicks (CTkToplevel even re-withdraws itself on Windows shortly
after creation), which made item clicks unreliable. A placed frame receives
events like any ordinary widget. Trade-off: the popup cannot extend past the
owner window — acceptable for the sidebar/histogram dropdowns.

Known limitation: if a future customtkinter release renames
``_open_dropdown_menu``/``_dropdown_callback``, the override is silently
bypassed and the stock (unscrolled) menu opens — degraded but functional.
"""
from __future__ import annotations

import logging

import customtkinter as ctk

from chipify.gui.widgets.scrolling import bind_mousewheel

log = logging.getLogger("chipify.gui.scrollable_option_menu")

_ITEM_HEIGHT = 28   # px per option row (button height + padding)
_MAX_WIDTH = 360    # px cap for content-based popup width


class ScrollableOptionMenu(ctk.CTkOptionMenu):
    """CTkOptionMenu whose dropdown is a scrollable popup of capped height."""

    def __init__(self, master, max_popup_height: int = 350, **kwargs):
        super().__init__(master, **kwargs)
        self._max_popup_height = max_popup_height
        self._popup = None
        # Global bindings live for the widget's lifetime and no-op while the
        # popup is closed — unbind_all would also strip other instances'
        # handlers, so we never unbind.
        top = self.winfo_toplevel()
        top.bind_all("<Button-1>", self._on_global_click, add="+")
        top.bind_all("<Escape>", self._close_popup, add="+")
        # NB: a bind on a toplevel fires for every descendant; only close
        # when the window itself moves/resizes.
        top.bind("<Configure>", self._on_owner_configure, add="+")
        self.bind("<Destroy>", self._close_popup, add="+")

    # CTk internal — called by CTkOptionMenu._clicked() after the state and
    # empty-values guards, so we only need to render the popup here.
    def _open_dropdown_menu(self):
        if self._popup is not None:       # second click on the widget toggles
            self._close_popup()
            return
        try:
            self._open_scrollable_popup()
        except Exception:
            log.exception("Scrollable popup failed — falling back to tk.Menu.")
            super()._open_dropdown_menu()

    # ── Popup ─────────────────────────────────────────────────────────────────

    def _close_popup(self, _event=None):
        if self._popup is not None:
            try:
                self._popup.destroy()
            except Exception:
                pass
            self._popup = None

    def _on_owner_configure(self, event=None):
        if self._popup is None:
            return
        try:
            if event.widget is self.winfo_toplevel():
                self._close_popup()
        except Exception:
            self._close_popup()

    def _on_global_click(self, event=None):
        """Close when a click lands outside both the popup and the widget."""
        if self._popup is None:
            return
        try:
            w = str(event.widget)
        except Exception:
            self._close_popup()
            return
        for owner in (str(self._popup), str(self)):
            if w == owner or w.startswith(owner + "."):
                return
        self._close_popup()

    def _choose(self, value: str):
        self._close_popup()
        # Base-class selection path: sets the value + variable, fires command.
        self._dropdown_callback(value)

    def _open_scrollable_popup(self):
        values = list(self._values or [])
        if not values:
            return
        top = self.winfo_toplevel()

        # Content-based width so long run filenames are not clipped.
        font = ctk.CTkFont()
        text_w = max(font.measure(v) for v in values)
        width = max(self.winfo_width(), min(text_w + 48, _MAX_WIDTH))
        height = min(self._max_popup_height, len(values) * _ITEM_HEIGHT + 12)

        x = self.winfo_rootx() - top.winfo_rootx()
        y = self.winfo_rooty() - top.winfo_rooty() + self.winfo_height() + 2
        # Stay inside the owner window: shift left / open upwards if needed.
        x = max(0, min(x, top.winfo_width() - width))
        if y + height > top.winfo_height():
            y_above = self.winfo_rooty() - top.winfo_rooty() - height - 2
            if y_above >= 0:
                y = y_above
            else:
                height = max(_ITEM_HEIGHT * 2, top.winfo_height() - y - 4)

        popup = ctk.CTkFrame(top, corner_radius=6, border_width=1)
        self._popup = popup
        popup.place(x=x, y=y)
        popup.lift()

        frame = ctk.CTkScrollableFrame(popup, width=width - 16,
                                       height=height - 16, corner_radius=6)
        frame.pack(fill="both", expand=True, padx=2, pady=2)
        bind_mousewheel(frame)

        current = self.get()
        for value in values:
            btn = ctk.CTkButton(
                frame, text=value, anchor="w", height=_ITEM_HEIGHT - 4,
                fg_color="transparent" if value != current else None,
                command=lambda v=value: self._choose(v),
            )
            btn.pack(fill="x", padx=2, pady=1)
