# Copyright (c) 2026 Santiago Hofwimmer
"""
plugin_loader.py – Lightweight plugin system for Chipify.

Users place Python files in ``~/.chipify/plugins/`` (or the directory
pointed to by the ``CHIPIFY_PLUGINS`` environment variable).  Each file
may define one or more classes that inherit from the base types below.

Plugin contract
---------------

Plot plugin
^^^^^^^^^^^
    from chipify.plugin_loader import PlotPlugin

    class MyPlot(PlotPlugin):
        name = "My Custom Plot"          # shown in the mode dropdown

        def draw(self, fig, ax, valid_df, stim):
            '''Receives a blank Matplotlib figure+axis and the simulation data.'''
            ax.plot(valid_df.index, valid_df.iloc[:, 0])
            ax.set_title("My Custom Plot")

Report plugin
^^^^^^^^^^^^^
    from chipify.plugin_loader import ReportPlugin

    class MySection(ReportPlugin):
        name = "My Extra Section"        # shown in the report-profile UI

        def render_md(self, valid_df, stim) -> str:
            '''Return a Markdown string to append to md_export output.'''
            return "## My Extra Section\\n\\nHello world."

        def render_pdf(self, pdf, valid_df, stim):
            '''Optional: add a page to an open matplotlib PdfPages object.'''
            pass

Expression plugin
^^^^^^^^^^^^^^^^^
    from chipify.plugin_loader import ExpressionPlugin

    class MyExpr(ExpressionPlugin):
        name = "snr_db"
        expression = "20 * log10(abs(signal / noise))"

Exporter plugin
^^^^^^^^^^^^^^^
    from chipify.plugin_loader import ExporterPlugin

    class MyExporter(ExporterPlugin):
        name      = "TIFF Image"   # shown in the per-plot Export menu
        extension = "tiff"         # file extension (no leading dot)

        def export(self, fig, out_path, *, theme=None):
            '''Write `fig` (matplotlib Figure) to `out_path`.'''
            fig.savefig(out_path, format="tiff", dpi=200, bbox_inches="tight")
            return out_path

    PNG and SVG ship as built-in exporters; user plugins of the same
    ``name`` override the built-in.

Tab plugin
^^^^^^^^^^
    from PySide6.QtWidgets import QLabel, QVBoxLayout
    from chipify.plugin_loader import QtTabPlugin

    class MyTab(QtTabPlugin):
        name = "My Tab"            # tab title in the main window

        def build(self, parent, context):
            '''Build Qt widgets into `parent` (a QWidget). `context` is the
            PluginContext facade (results, specs, netlists, run_async, …).'''
            QVBoxLayout(parent).addWidget(QLabel("Hello", parent))

    See PLUGINS.md for the full QtTabPlugin / PluginContext reference. (The
    legacy Tk ``TabPlugin`` base still exists but is skipped by the Qt GUI.)

Simulator engine plugin
^^^^^^^^^^^^^^^^^^^^^^^
    from chipify.engines import BaseSimulator

    class MySim(BaseSimulator):
        name = "mysim"             # datasheet `engine:` / settings value
        netlist_ext = ".cir"

        def generate_test_template(self, test) -> str: ...
        def run(self, netlist, timeout_sec=10, test=None,
                analysis_tab_paths=None): ...

    Discovered by the engine registry (chipify.engines), not by this module's
    getters — but from the same plugin directory and with the same file
    format. See PLUGINS.md, section "Simulator engine plugin".

Discovery
---------
Plugins are loaded lazily on first call to ``get_plot_plugins()`` /
``get_report_plugins()`` / ``get_expression_plugins()`` /
``get_exporter_plugins()``.  Errors in individual plugin files are
logged with full tracebacks and silently skipped so a bad plugin
never crashes the main app.

If two plugins of the same type share the same ``name``, the second is
skipped and a warning is logged.

Example plugin directory
------------------------
    ~/.chipify/plugins/
        my_plot.py
        my_report.py
        my_expressions.py

API versioning
--------------
Each plugin class may declare ``api_version = "1"`` (default).  If a
future Chipify release increments the API version, plugins targeting an
older version will log a deprecation warning but continue to load.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Type

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_pdf import PdfPages

log = logging.getLogger("chipify.plugins")

_PLUGIN_DIR_ENV = "CHIPIFY_PLUGINS"
_DEFAULT_PLUGIN_DIR = str(Path.home() / ".chipify" / "plugins")
_CURRENT_API_VERSION = "1"

_plot_plugins:       list[Type["PlotPlugin"]]       | None = None
_report_plugins:     list[Type["ReportPlugin"]]     | None = None
_expression_plugins: list[Type["ExpressionPlugin"]] | None = None
_exporter_plugins:   list[Type["ExporterPlugin"]]   | None = None
_tab_plugins:        list[Type["TabPlugin"]]        | None = None
_qt_tab_plugins:     list[Type["QtTabPlugin"]]      | None = None


# ── Base classes ──────────────────────────────────────────────────────────────

class PlotPlugin:
    """Base class for custom plot modes."""

    #: Display name shown in the mode dropdown (must be unique across all plugins).
    name: str = "Unnamed Plot Plugin"

    #: Chipify plugin API version this plugin was written for.
    api_version: str = "1"

    #: Declare True when ``draw`` accepts a ``param=`` kwarg: the host then
    #: shows a measurement selector (plus an "all measurements" checkbox) and
    #: passes the chosen output name — or ``None`` for "plot everything".
    supports_param: bool = False

    def draw(
        self,
        fig: "Figure",
        ax: "Axes",
        valid_df: "pd.DataFrame",
        stim: Any,
        *,
        theme: dict | None = None,
    ) -> None:
        """
        Draw onto *ax* inside *fig*.

        Parameters
        ----------
        fig:
            Blank ``matplotlib.figure.Figure``.
        ax:
            ``matplotlib.axes.Axes`` to draw onto.
        valid_df:
            ``pd.DataFrame`` containing only rows where ``sim_error == 'None'``.
        stim:
            ``chipify.util.Stimuli`` — the parsed YAML test specification.
        theme:
            Optional palette dict for the active appearance theme. Keys:
            ``bg``, ``fg``, ``grid``, ``spine``, ``legend_bg``, ``legend_edge``,
            ``legend_text``, ``accent``. Plugins that ignore *theme* will draw
            with matplotlib's current rcParams. Plugins that omit the kwarg
            from their signature continue to work (the host calls via
            try/except fallback).
        """
        ax.text(
            0.5, 0.5, f"Plugin '{self.name}' has no draw() implementation.",
            ha="center", va="center", transform=ax.transAxes, color="gray",
        )


class ReportPlugin:
    """Base class for custom report sections."""

    #: Display name used in the report-profile UI and as a section header.
    name: str = "Unnamed Report Plugin"

    #: Chipify plugin API version this plugin was written for.
    api_version: str = "1"

    def render_md(self, valid_df: "pd.DataFrame", stim: Any) -> str:
        """
        Return Markdown text to append to the generated report.

        Parameters
        ----------
        valid_df:
            ``pd.DataFrame`` with only successful simulation rows.
        stim:
            ``chipify.util.Stimuli`` — the parsed YAML test specification.
        """
        return f"## {self.name}\n\n*(no content)*\n"

    def render_pdf(self, pdf: "PdfPages", valid_df: "pd.DataFrame", stim: Any) -> None:
        """
        Optionally add one or more pages to an open ``PdfPages`` object.

        Parameters
        ----------
        pdf:
            Open ``matplotlib.backends.backend_pdf.PdfPages`` file.
        valid_df:
            ``pd.DataFrame`` with only successful simulation rows.
        stim:
            ``chipify.util.Stimuli`` — the parsed YAML test specification.
        """


class ExpressionPlugin:
    """
    Base class for plugins that inject named scalar expressions into the equation engine.

    These are equivalent to entries in ``custom_equations`` in ``settings.json`` but
    can be versioned, shared, and distributed as Python files.

    The expression is evaluated row-by-row against the simulation DataFrame using
    ``SafeEvaluator`` (sandboxed asteval). All column names are available as variables.
    Numpy functions (``sin``, ``log10``, ``abs``, …) are available without a prefix.

    Example
    -------
    ::

        class SNR(ExpressionPlugin):
            name = "snr_db"
            expression = "20 * log10(abs(signal / noise))"
    """

    #: Output column name added to the result DataFrame.
    name: str = "unnamed_expression"

    #: Chipify plugin API version this plugin was written for.
    api_version: str = "1"

    #: The scalar expression string, evaluated via SafeEvaluator.
    expression: str = ""


class ExporterPlugin:
    """
    Base class for plugins that save a Matplotlib figure to a single file
    in a particular image format (PNG, SVG, TIFF, EPS, WebP, …).

    Each plot in the UI grows an "Export" button whose menu is built
    dynamically from every registered exporter. PNG and SVG ship as
    built-in exporters; users add formats by dropping a Python file
    into ``~/.chipify/plugins/`` (or the ``CHIPIFY_PLUGINS`` directory).

    Example
    -------
    ::

        class WebPExporter(ExporterPlugin):
            name      = "WebP Image"
            extension = "webp"

            def export(self, fig, out_path, *, theme=None):
                fig.savefig(out_path, format="webp", dpi=200,
                            bbox_inches="tight")
                return out_path
    """

    #: Display name shown in the per-plot Export menu (must be unique).
    name: str = "Unnamed Exporter"

    #: File extension without a leading dot, e.g. ``"png"``, ``"svg"``.
    extension: str = ""

    #: Optional one-line description (reserved for future tooltips).
    description: str = ""

    #: Chipify plugin API version this plugin was written for.
    api_version: str = "1"

    def export(
        self,
        fig: "Figure",
        out_path: str,
        *,
        theme: dict | None = None,
    ) -> str:
        """
        Write *fig* to *out_path* and return the path actually written.

        Parameters
        ----------
        fig:
            ``matplotlib.figure.Figure`` to save.
        out_path:
            Absolute filesystem path the exporter must write to.
        theme:
            Optional active palette dict (same keys as in :class:`PlotPlugin`).
            Built-in exporters preserve ``fig.get_facecolor()`` and ignore
            this; custom exporters may consult it for re-theming on save.
        """
        raise NotImplementedError


class TabPlugin:
    """
    **Legacy** base class for tab plugins targeting the old CustomTkinter GUI.

    Retained only so the current GUI can *detect* such plugins and skip them
    with a clear warning (see :func:`warn_unsupported_tab_plugins`). The PySide6
    (Qt) GUI loads :class:`QtTabPlugin` instead — port a legacy plugin by
    changing its base class to ``QtTabPlugin`` and building Qt widgets in
    ``build`` (the :class:`~chipify.uikit.services.plugin_context.PluginContext`
    facade is identical for both). See PLUGINS.md.
    """

    #: Tab title shown in the main window. Must be unique and must not
    #: collide with a built-in tab name.
    name: str = "Unnamed Tab Plugin"

    #: Chipify plugin API version this plugin was written for.
    api_version: str = "1"

    def build(self, parent: Any, context: Any) -> None:
        """Construct the tab's widgets into *parent* (a tk frame).

        Called exactly once at startup. *context* is the PluginContext —
        see PLUGINS.md for its full API. If this raises, the host replaces
        the tab content with an error panel; the app does not crash.
        """
        raise NotImplementedError

    def on_data_changed(self, context: Any) -> None:
        """Optional: called on the Tk main thread whenever new simulation
        results or a different datasheet are loaded."""

    def on_show(self, context: Any) -> None:
        """Optional: called when the user switches to this tab."""

    def on_close(self) -> None:
        """Optional: called once when the application shuts down."""


class QtTabPlugin:
    """
    Base class for plugins that add a whole tab to the PySide6 (Qt) GUI.

    Identical contract to :class:`TabPlugin`, except ``build`` receives a
    ``PySide6.QtWidgets.QWidget`` as *parent* instead of a Tk frame — the
    plugin lays its Qt widgets into it (e.g. with a ``QVBoxLayout``). The
    :class:`~chipify.uikit.services.plugin_context.PluginContext` facade is
    unchanged, so data access, ``run_async`` and ``subscribe_data_changed``
    behave exactly as documented in PLUGINS.md.

    Legacy Tk :class:`TabPlugin`\\ s are **not** loaded by the Qt GUI (it warns
    and skips them); port them by changing the base class to ``QtTabPlugin`` and
    building Qt widgets.

    Example
    -------
    ::

        from PySide6.QtWidgets import QLabel, QVBoxLayout
        from chipify.plugin_loader import QtTabPlugin

        class RunCounter(QtTabPlugin):
            name = "Run Counter"

            def build(self, parent, context):
                self._lbl = QLabel("no data", parent)
                QVBoxLayout(parent).addWidget(self._lbl)

            def on_data_changed(self, context):
                df = context.results()
                self._lbl.setText(f"{0 if df is None else len(df)} runs loaded")
    """

    #: Tab title shown in the main window. Must be unique and must not collide
    #: with a built-in tab name.
    name: str = "Unnamed Qt Tab Plugin"

    #: Chipify plugin API version this plugin was written for.
    api_version: str = "1"

    def build(self, parent: Any, context: Any) -> None:
        """Construct the tab's widgets into *parent* (a ``QWidget``).

        Called once at startup. If this raises, the host replaces the tab
        content with an error panel; the app does not crash.
        """
        raise NotImplementedError

    def on_data_changed(self, context: Any) -> None:
        """Optional: called on the GUI thread when new results / a different
        datasheet are loaded."""

    def on_show(self, context: Any) -> None:
        """Optional: called when the user switches to this tab."""

    def on_close(self) -> None:
        """Optional: called once when the application shuts down."""


# ── Discovery ────────────────────────────────────────────────────────────────

def _plugin_dir() -> str:
    return os.environ.get(_PLUGIN_DIR_ENV, _DEFAULT_PLUGIN_DIR)


def _load_module_from_file(path: str):
    """Import a Python file as a module.  Returns the module or None on error."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"_chipify_plugin_{Path(path).name}", path
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    except Exception as exc:
        log.warning("Could not load plugin file %s: %s", path, exc, exc_info=True)
        return None


def _discover(base_class: type) -> list[type]:
    """Scan the plugin directory and return all subclasses of *base_class*."""
    found: list[type] = []
    seen_names: set[str] = set()
    plugin_dir = Path(_plugin_dir())
    if not plugin_dir.is_dir():
        return found

    for fpath in sorted(plugin_dir.iterdir(), key=lambda p: p.name):
        if fpath.suffix != ".py":
            continue
        mod = _load_module_from_file(fpath)
        if mod is None:
            continue
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            try:
                if (
                    isinstance(obj, type)
                    and issubclass(obj, base_class)
                    and obj is not base_class
                    and getattr(obj, "name", None)
                ):
                    plugin_name: str = obj.name
                    if plugin_name in seen_names:
                        log.warning(
                            "Duplicate plugin name %r in %s – skipping.",
                            plugin_name, fpath.name,
                        )
                        continue
                    seen_names.add(plugin_name)
                    api_ver = getattr(obj, "api_version", "1")
                    if api_ver != _CURRENT_API_VERSION:
                        log.warning(
                            "Plugin %r targets api_version=%r; current is %r. "
                            "It may need updating.",
                            plugin_name, api_ver, _CURRENT_API_VERSION,
                        )
                    found.append(obj)
                    log.info("Loaded plugin: %s from %s", plugin_name, fpath.name)
            except Exception:
                pass
    return found


def discover_plugin_classes(base_class: type) -> list[type]:
    """Public discovery hook: scan the plugin directory for subclasses of
    *base_class*.

    Used by :mod:`chipify.engines` to find drop-in simulator engines
    (``BaseSimulator`` subclasses) with the same file-based mechanism as the
    GUI plugin types above. Not cached — callers cache their own results.
    """
    return _discover(base_class)


def get_plot_plugins() -> list[Type[PlotPlugin]]:
    """
    Return every available PlotPlugin: built-in distribution plots first,
    then user-supplied plugins discovered in the plugin directory. If a
    user plugin uses the same ``name`` as a built-in, the user plugin wins.

    Cached after the first call; clear via :func:`reload_plugins`.
    """
    global _plot_plugins
    if _plot_plugins is None:
        from chipify.plot_plugins import BUILTIN_PLOT_PLUGINS
        discovered: list[Type[PlotPlugin]] = _discover(PlotPlugin)  # type: ignore[assignment]
        discovered_names = {p.name for p in discovered}
        builtins = [p for p in BUILTIN_PLOT_PLUGINS if p.name not in discovered_names]
        _plot_plugins = builtins + discovered
    return _plot_plugins  # type: ignore[return-value]


def get_report_plugins() -> list[Type[ReportPlugin]]:
    """Return all discovered ReportPlugin subclasses (cached after first call)."""
    global _report_plugins
    if _report_plugins is None:
        _report_plugins = _discover(ReportPlugin)  # type: ignore[assignment]
    return _report_plugins  # type: ignore[return-value]


def get_expression_plugins() -> list[Type[ExpressionPlugin]]:
    """Return all discovered ExpressionPlugin subclasses (cached after first call)."""
    global _expression_plugins
    if _expression_plugins is None:
        _expression_plugins = _discover(ExpressionPlugin)  # type: ignore[assignment]
    return _expression_plugins  # type: ignore[return-value]


def get_exporter_plugins() -> list[Type[ExporterPlugin]]:
    """
    Return every available ExporterPlugin: built-in PNG/SVG first, then
    user-supplied plugins discovered in the plugin directory. If a user
    plugin uses the same ``name`` as a built-in, the user plugin wins.

    Cached after the first call; clear via :func:`reload_plugins`.
    """
    global _exporter_plugins
    if _exporter_plugins is None:
        from chipify.exporters import BUILTIN_EXPORTERS
        discovered: list[Type[ExporterPlugin]] = _discover(ExporterPlugin)  # type: ignore[assignment]
        discovered_names = {p.name for p in discovered}
        builtins = [p for p in BUILTIN_EXPORTERS if p.name not in discovered_names]
        _exporter_plugins = builtins + discovered
    return _exporter_plugins  # type: ignore[return-value]


def get_tab_plugins() -> list[Type[TabPlugin]]:
    """Return all discovered TabPlugin subclasses (cached after first call)."""
    global _tab_plugins
    if _tab_plugins is None:
        _tab_plugins = _discover(TabPlugin)  # type: ignore[assignment]
    return _tab_plugins  # type: ignore[return-value]


def get_qt_tab_plugins() -> list[Type[QtTabPlugin]]:
    """Return all discovered QtTabPlugin subclasses (cached after first call)."""
    global _qt_tab_plugins
    if _qt_tab_plugins is None:
        _qt_tab_plugins = _discover(QtTabPlugin)  # type: ignore[assignment]
    return _qt_tab_plugins  # type: ignore[return-value]


def warn_unsupported_tab_plugins() -> list[str]:
    """Log a warning for each legacy Tk :class:`TabPlugin` found.

    Tk tab plugins cannot run under the Qt GUI; the host calls this once at
    startup so users see an actionable message. Returns the offending names.
    """
    names = [p.name for p in get_tab_plugins()]
    for name in names:
        log.warning(
            "Tk TabPlugin %r is not supported by the Qt GUI — port it to "
            "QtTabPlugin (see PLUGINS.md).", name,
        )
    return names


def reload_plugins() -> None:
    """Force re-discovery of all plugins on the next call."""
    global _plot_plugins, _report_plugins, _expression_plugins, _exporter_plugins
    global _tab_plugins, _qt_tab_plugins
    _plot_plugins        = None
    _report_plugins      = None
    _expression_plugins  = None
    _exporter_plugins    = None
    _tab_plugins         = None
    _qt_tab_plugins      = None
    log.info("Plugin cache cleared; plugins will reload on next access.")


def plugin_dir() -> str:
    """Return the active plugin directory path."""
    return _plugin_dir()


def list_plugins() -> dict[str, list[dict[str, str]]]:
    """
    Return a diagnostic summary of all loaded plugins.

    Returns
    -------
    dict with keys ``"plot"``, ``"report"``, ``"expression"``, ``"exporter"``,
    ``"tab"``. Each value is a list of dicts with ``"name"`` and
    ``"api_version"``.

    Example
    -------
    ::

        from chipify.plugin_loader import list_plugins
        import pprint
        pprint.pprint(list_plugins())
    """
    def _describe(plugins: list[type]) -> list[dict[str, str]]:
        return [
            {"name": p.name, "api_version": getattr(p, "api_version", "1")}
            for p in plugins
        ]

    return {
        "plot":       _describe(get_plot_plugins()),
        "report":     _describe(get_report_plugins()),
        "expression": _describe(get_expression_plugins()),
        "exporter":   _describe(get_exporter_plugins()),
        "tab":        _describe(get_tab_plugins()),
        "qt_tab":     _describe(get_qt_tab_plugins()),
    }
