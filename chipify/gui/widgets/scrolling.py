# Copyright (c) 2026 Santiago Hofwimmer
"""
scrolling.py – Mouse-wheel support for CTkScrollableFrame.

CustomTkinter binds wheel events on the scrollable frame's internal canvas,
but on Windows/Linux the events go to the widget *under the cursor* — so as
soon as the pointer is over an entry, button, or sub-frame inside the
scrollable area, scrolling stops working.

``bind_mousewheel(frame)`` fixes this with the standard Tk pattern: while the
pointer is inside the frame, a global (``bind_all``) wheel binding scrolls the
frame's canvas; it is removed again on ``<Leave>``. Only one frame can hold
the global binding at a time, which is exactly the desired behavior for
nested/side-by-side scroll areas.
"""
from __future__ import annotations

import logging

log = logging.getLogger("chipify.gui.scrolling")

_WHEEL_EVENTS = ("<MouseWheel>", "<Button-4>", "<Button-5>")


def _canvas_of(frame):
    """Return the internal canvas of a CTkScrollableFrame (None if unknown)."""
    return getattr(frame, "_parent_canvas", None)


def bind_mousewheel(frame) -> None:
    """Make the mouse wheel scroll *frame* while the pointer is anywhere inside it.

    *frame* is a ``ctk.CTkScrollableFrame``. Safe to call on any widget — if
    no internal canvas is found, the call is a silent no-op.
    """
    canvas = _canvas_of(frame)
    if canvas is None:
        log.debug("bind_mousewheel: no _parent_canvas on %r — skipped.", frame)
        return

    def _on_wheel(event):
        try:
            if canvas.yview() == (0.0, 1.0):
                return  # content fits — nothing to scroll
            if getattr(event, "num", None) == 4:        # Linux wheel up
                step = -1
            elif getattr(event, "num", None) == 5:      # Linux wheel down
                step = 1
            else:                                       # Windows ±120 / macOS small deltas
                step = -1 if event.delta > 0 else 1
            canvas.yview_scroll(step, "units")
        except Exception:
            pass
        return "break"

    def _on_enter(_event=None):
        try:
            for ev in _WHEEL_EVENTS:
                frame.bind_all(ev, _on_wheel)
        except Exception:
            pass

    def _on_leave(_event=None):
        try:
            for ev in _WHEEL_EVENTS:
                frame.unbind_all(ev)
        except Exception:
            pass

    frame.bind("<Enter>", _on_enter, add="+")
    frame.bind("<Leave>", _on_leave, add="+")
    # Also release the global binding when the frame goes away.
    frame.bind("<Destroy>", _on_leave, add="+")
