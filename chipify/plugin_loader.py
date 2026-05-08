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

Discovery
---------
Plugins are loaded lazily on first call to ``get_plot_plugins()`` /
``get_report_plugins()`` / ``get_expression_plugins()``.  Errors in
individual plugin files are logged with full tracebacks and silently
skipped so a bad plugin never crashes the main app.

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
from typing import TYPE_CHECKING, Any, Type

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_pdf import PdfPages

log = logging.getLogger("chipify.plugins")

_PLUGIN_DIR_ENV = "CHIPIFY_PLUGINS"
_DEFAULT_PLUGIN_DIR = os.path.join(os.path.expanduser("~"), ".chipify", "plugins")
_CURRENT_API_VERSION = "1"

_plot_plugins:       list[Type["PlotPlugin"]]       | None = None
_report_plugins:     list[Type["ReportPlugin"]]     | None = None
_expression_plugins: list[Type["ExpressionPlugin"]] | None = None


# ── Base classes ──────────────────────────────────────────────────────────────

class PlotPlugin:
    """Base class for custom plot modes."""

    #: Display name shown in the mode dropdown (must be unique across all plugins).
    name: str = "Unnamed Plot Plugin"

    #: Chipify plugin API version this plugin was written for.
    api_version: str = "1"

    def draw(
        self,
        fig: "Figure",
        ax: "Axes",
        valid_df: "pd.DataFrame",
        stim: Any,
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


# ── Discovery ────────────────────────────────────────────────────────────────

def _plugin_dir() -> str:
    return os.environ.get(_PLUGIN_DIR_ENV, _DEFAULT_PLUGIN_DIR)


def _load_module_from_file(path: str):
    """Import a Python file as a module.  Returns the module or None on error."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"_chipify_plugin_{os.path.basename(path)}", path
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
    plugin_dir = _plugin_dir()
    if not os.path.isdir(plugin_dir):
        return found

    for filename in sorted(os.listdir(plugin_dir)):
        if not filename.endswith(".py"):
            continue
        mod = _load_module_from_file(os.path.join(plugin_dir, filename))
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
                            plugin_name, filename,
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
                    log.info("Loaded plugin: %s from %s", plugin_name, filename)
            except Exception:
                pass
    return found


def get_plot_plugins() -> list[Type[PlotPlugin]]:
    """Return all discovered PlotPlugin subclasses (cached after first call)."""
    global _plot_plugins
    if _plot_plugins is None:
        _plot_plugins = _discover(PlotPlugin)  # type: ignore[assignment]
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


def reload_plugins() -> None:
    """Force re-discovery of all plugins on the next call."""
    global _plot_plugins, _report_plugins, _expression_plugins
    _plot_plugins        = None
    _report_plugins      = None
    _expression_plugins  = None
    log.info("Plugin cache cleared; plugins will reload on next access.")


def plugin_dir() -> str:
    """Return the active plugin directory path."""
    return _plugin_dir()


def list_plugins() -> dict[str, list[dict[str, str]]]:
    """
    Return a diagnostic summary of all loaded plugins.

    Returns
    -------
    dict with keys ``"plot"``, ``"report"``, ``"expression"``.
    Each value is a list of dicts with ``"name"`` and ``"api_version"``.

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
    }
