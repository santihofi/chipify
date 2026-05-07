"""
state.py – Application state model and minimal pub/sub bus.

``AppState`` is the single source of truth for all data that flows between
the GUI shell, controllers, and tab views.  Tabs read from it and subscribe
to its signals; controllers mutate it and call ``signal.emit()``.

No tkinter imports here — this module is usable in headless tests.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import pandas as pd

log = logging.getLogger("chipify.gui.state")


# ── Signal ────────────────────────────────────────────────────────────────────

class Signal:
    """
    Minimal synchronous publish/subscribe primitive.

    Usage::

        sig = Signal()
        sig.connect(my_callback)   # my_callback(**kwargs)
        sig.emit(foo=1, bar=2)     # calls my_callback(foo=1, bar=2)
        sig.disconnect(my_callback)
    """

    def __init__(self) -> None:
        self._callbacks: list[Callable[..., None]] = []

    def connect(self, callback: Callable[..., None]) -> None:
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def disconnect(self, callback: Callable[..., None]) -> None:
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    def emit(self, **kwargs: Any) -> None:
        for cb in list(self._callbacks):
            try:
                cb(**kwargs)
            except Exception:
                log.exception("Signal subscriber raised an exception: %r", cb)


# ── AppState ──────────────────────────────────────────────────────────────────

class AppState:
    """
    Holds all mutable GUI-wide state.

    Attributes
    ----------
    current_df
        The active simulation result DataFrame (``None`` until first load).
    current_stim
        The ``util.Stimuli`` object matching the active DataFrame.
    current_yaml_path
        Absolute path to the currently selected datasheet YAML.
    sweep_params
        Names of columns that are discrete sweep parameters (not outputs).
    all_plot_cols
        All numeric columns available for plotting (params + outputs).
    derived_cols
        Column names added by the Custom Equations feature.
    last_sim_duration_sec
        Wall-clock seconds of the most recent completed simulation run.
    multiplot_window
        Reference to the ``MultiPlotWindow`` Toplevel, or ``None``.

    Signals (connect callbacks to receive change notifications)
    -----------------------------------------------------------
    data_changed
        Emitted after ``current_df`` / ``current_stim`` are updated.
        kwargs: ``df``, ``stim``, ``switch_tab: bool``
    yaml_changed
        Emitted after the active YAML changes.
        kwargs: ``yaml_path: str``
    status_changed
        Emitted when a status-bar update is requested.
        kwargs: ``text: str``, ``color: str``
    """

    def __init__(self) -> None:
        # ── Data ──────────────────────────────────────────────────────────────
        self.current_df: pd.DataFrame | None = None
        self.current_stim: Any = None
        self.current_yaml_path: str | None = None

        self.sweep_params: list[str] = []
        self.all_plot_cols: list[str] = []
        self.derived_cols: list[str] = []
        self.last_sim_duration_sec: float | None = None

        # Weak reference to MultiPlotWindow Toplevel (may be destroyed externally)
        self.multiplot_window: Any = None

        # ── Signals ───────────────────────────────────────────────────────────
        self.data_changed: Signal = Signal()
        self.yaml_changed: Signal = Signal()
        self.status_changed: Signal = Signal()
