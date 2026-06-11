"""Run Info — a complete, dependency-free TabPlugin example.

Copy this file into your plugin directory (``~/.chipify/plugins/`` or
``$CHIPIFY_PLUGINS``) and restart Chipify; a "Run Info" tab appears in the
main window. It demonstrates the full TabPlugin surface:

- ``build``            – constructing themed widgets into the provided frame
- ``on_data_changed``  – refreshing when results / datasheet change
- ``on_show``          – reacting when the tab becomes visible
- ``context`` access   – summary, specs, history runs, netlists
- ``run_async``        – off-thread work with results delivered back to the UI

See PLUGINS.md → TabPlugin / PluginContext reference for the contract.
"""
import json

import customtkinter as ctk

from chipify.plugin_loader import TabPlugin


class RunInfoTab(TabPlugin):
    name = "Run Info"

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self, parent, context):
        theme = context.theme()

        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(10, 6))
        self._headline = ctk.CTkLabel(
            bar, text="No data loaded yet.",
            font=ctk.CTkFont(size=14, weight="bold"))
        self._headline.pack(side="left")
        ctk.CTkButton(
            bar, text="↺  Refresh", width=100,
            command=lambda: self.on_data_changed(context),
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
        ).pack(side="right")
        ctk.CTkButton(
            bar, text="Count netlist lines (async)", width=190,
            command=lambda: self._count_async(context),
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
        ).pack(side="right", padx=(0, 8))

        self._text = ctk.CTkTextbox(
            parent, wrap="none", font=ctk.CTkFont(family="Courier", size=12),
            text_color=theme["fg"])
        self._text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.on_data_changed(context)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_data_changed(self, context):
        s = context.summary()
        if s["total"] == 0:
            self._headline.configure(text="No data loaded yet.")
            self._set_text("Run a simulation or load a history run.")
            return

        self._headline.configure(
            text=f"{s['total']} runs  ·  {s['passed']} passing"
                 f"  ·  yield {s['yield_pct']}%")

        lines = [
            f"chipify {context.chipify_version}  ·  plugin API {context.api_version}",
            f"datasheet: {context.datasheet_path or '—'}",
            f"history runs available: {len(context.history_runs())}",
            f"waveform data: {', '.join(context.analysis_kinds()) or 'none'}",
            "",
            "── specs() ──────────────────────────────────────────",
            json.dumps(context.specs(), indent=2, default=str),
        ]
        self._set_text("\n".join(lines))

    def on_show(self, context):
        # Cheap example of a lazy refresh when the tab becomes visible.
        context.set_status("Run Info tab active", "#3484F0")

    # ── async demo ────────────────────────────────────────────────────────────

    def _count_async(self, context):
        """Demonstrate run_async: gather data on the UI thread, work off it."""
        netlists = context.netlists()          # main thread: cheap copy

        def work():                            # worker thread: NO widgets here
            return {tb: text.count("\n") + 1 for tb, text in netlists.items()}

        def done(result):                      # main thread again: UI is safe
            msg = ("No netlists rendered yet — run a simulation first."
                   if not result else
                   "\n".join(f"{tb}: {n} lines" for tb, n in result.items()))
            self._set_text(msg)

        context.run_async(work, on_done=done)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _set_text(self, text: str):
        self._text.delete("1.0", "end")
        self._text.insert("end", text)
