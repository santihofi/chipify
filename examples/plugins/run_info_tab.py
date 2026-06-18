"""Run Info — a complete, dependency-free QtTabPlugin example.

Copy this file into your plugin directory (``~/.chipify/plugins/`` or
``$CHIPIFY_PLUGINS``) and restart Chipify; a "Run Info" tab appears in the
main window. It demonstrates the full QtTabPlugin surface:

- ``build``            – constructing Qt widgets into the provided QWidget
- ``on_data_changed``  – refreshing when results / datasheet change
- ``on_show``          – reacting when the tab becomes visible
- ``context`` access   – summary, specs, history runs, netlists
- ``run_async``        – off-thread work with results delivered back to the UI

See PLUGINS.md → QtTabPlugin / PluginContext reference for the contract.
"""
import json

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from chipify.plugin_loader import QtTabPlugin


class RunInfoTab(QtTabPlugin):
    name = "Run Info"

    # ── build ─────────────────────────────────────────────────────────────────

    def build(self, parent, context):
        layout = QVBoxLayout(parent)

        bar = QHBoxLayout()
        self._headline = QLabel("No data loaded yet.")
        font = self._headline.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self._headline.setFont(font)
        bar.addWidget(self._headline)
        bar.addStretch(1)

        btn_count = QPushButton("Count netlist lines (async)")
        btn_count.clicked.connect(lambda: self._count_async(context))
        bar.addWidget(btn_count)
        btn_refresh = QPushButton("↺ Refresh")
        btn_refresh.clicked.connect(lambda: self.on_data_changed(context))
        bar.addWidget(btn_refresh)
        layout.addLayout(bar)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.Monospace)
        self._text.setFont(mono)
        layout.addWidget(self._text, stretch=1)

        self.on_data_changed(context)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_data_changed(self, context):
        s = context.summary()
        if s["total"] == 0:
            self._headline.setText("No data loaded yet.")
            self._text.setPlainText("Run a simulation or load a history run.")
            return

        self._headline.setText(
            f"{s['total']} runs  ·  {s['passed']} passing  ·  yield {s['yield_pct']}%"
        )
        lines = [
            f"chipify {context.chipify_version}  ·  plugin API {context.api_version}",
            f"datasheet: {context.datasheet_path or '—'}",
            f"history runs available: {len(context.history_runs())}",
            f"waveform data: {', '.join(context.analysis_kinds()) or 'none'}",
            "",
            "── specs() ──────────────────────────────────────────",
            json.dumps(context.specs(), indent=2, default=str),
        ]
        self._text.setPlainText("\n".join(lines))

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
            self._text.setPlainText(msg)

        context.run_async(work, on_done=done)
