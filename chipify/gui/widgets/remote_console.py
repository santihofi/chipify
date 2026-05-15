"""
remote_console.py – Collapsible "Remote console" widget.

Shows the tail of the remote chipify-cli log line buffer that
``RemoteDispatcher`` exposes via the structured progress callback. When
the compute target is ``local`` this widget can be hidden entirely; on
``remote`` runs the simulation controller pushes the latest log_tail
into it on every progress tick.

Designed to be created once and live for the GUI lifetime: ``set_log``
is idempotent and short-circuits when nothing has changed.
"""
from __future__ import annotations

from typing import Iterable

import customtkinter as ctk


class RemoteConsole(ctk.CTkFrame):
    """Collapsible textbox that tails the remote chipify-cli output."""

    def __init__(self, master: ctk.CTkBaseClass, *, max_lines: int = 200) -> None:
        super().__init__(master, fg_color="transparent")
        self._max_lines = int(max_lines)
        self._last_signature: int = 0
        self._collapsed: bool = True

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x")

        self._toggle_btn = ctk.CTkButton(
            header,
            text="▸  Remote console (0)",
            anchor="w",
            fg_color="transparent",
            border_width=0,
            text_color=("gray10", "#DCE4EE"),
            hover_color=("gray80", "gray25"),
            command=self.toggle,
        )
        self._toggle_btn.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            header,
            text="Clear",
            width=60,
            fg_color="transparent",
            border_width=1,
            text_color=("gray10", "#DCE4EE"),
            command=self.clear,
        ).pack(side="right", padx=(4, 0))

        self._body = ctk.CTkTextbox(
            self,
            height=140,
            wrap="none",
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        # Body is hidden by default — toggle pack/forget for collapse.
        # Do not pack here; toggle() controls visibility.
        self._body.configure(state="disabled")

    # ── Public API ──────────────────────────────────────────────────────

    def set_log(self, lines: Iterable[str]) -> None:
        """Replace the content with the latest tail of *lines*.

        No-op when the content is unchanged, so this is safe to call every
        progress tick.
        """
        listing = list(lines)[-self._max_lines:]
        sig = hash(("\n".join(listing), len(listing)))
        if sig == self._last_signature:
            return
        self._last_signature = sig

        self._body.configure(state="normal")
        self._body.delete("1.0", "end")
        if listing:
            self._body.insert("end", "\n".join(listing) + "\n")
            self._body.see("end")
        self._body.configure(state="disabled")
        self._update_header(len(listing))

    def clear(self) -> None:
        self._body.configure(state="normal")
        self._body.delete("1.0", "end")
        self._body.configure(state="disabled")
        self._last_signature = 0
        self._update_header(0)

    def toggle(self) -> None:
        if self._collapsed:
            self._body.pack(fill="x", padx=2, pady=(2, 0))
            self._collapsed = False
        else:
            self._body.pack_forget()
            self._collapsed = True
        self._update_header()

    # ── Internals ───────────────────────────────────────────────────────

    def _update_header(self, count: int | None = None) -> None:
        if count is None:
            try:
                count = int(self._body.index("end-1c").split(".")[0]) - 1
            except (ValueError, AttributeError):
                count = 0
        arrow = "▸" if self._collapsed else "▾"
        self._toggle_btn.configure(text=f"{arrow}  Remote console ({count})")
