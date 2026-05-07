"""
tabs/base.py – Abstract base for all tab views.

Each tab is a self-contained object that:
  - owns its widgets (built into a parent CTkFrame supplied by SimifyGUI)
  - holds a reference to the main window (`app`) for shared state access
  - implements ``on_state_change()`` which is called whenever the shared
    AppState changes (new simulation data loaded, equations applied, etc.)

The ``app`` coupling is intentional for Phase 1: tabs read from ``app.current_df``,
``app.current_stim``, ``app.sweep_params``, and ``app._derived_cols`` directly.
Phase 2 will replace those with pure AppState signal subscriptions.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import customtkinter as ctk

if TYPE_CHECKING:
    pass  # avoid circular import for type hints


class TabFrame(ABC):
    """
    Abstract base for all Chipify tab views.

    Subclasses must implement ``build()`` which constructs all widgets into
    ``self.parent``.  ``on_state_change()`` is optional; implement it to react
    to new simulation data.
    """

    def __init__(self, parent: ctk.CTkFrame, app: object) -> None:
        """
        Parameters
        ----------
        parent:
            The CTkFrame (tab content area) to build widgets into.
        app:
            The SimifyGUI instance — used to read shared state such as
            ``current_df``, ``current_stim``, ``sweep_params``, etc.
        """
        self.parent = parent
        self.app = app

    @abstractmethod
    def build(self) -> None:
        """Construct all widgets inside ``self.parent``."""

    def on_state_change(self) -> None:
        """
        Called after ``app.current_df`` / ``app.current_stim`` change.

        Override to refresh the tab's plot, table, or dropdowns.
        Default implementation is a no-op.
        """
