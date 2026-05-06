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

Discovery
---------
Plugins are loaded lazily on first call to ``get_plot_plugins()`` /
``get_report_plugins()``.  Errors in individual plugin files are logged
and silently skipped so a bad plugin never crashes the main app.

Example plugin directory
------------------------
    ~/.chipify/plugins/
        my_plot.py
        my_report.py
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from typing import Type

log = logging.getLogger("chipify.plugins")

_PLUGIN_DIR_ENV = "CHIPIFY_PLUGINS"
_DEFAULT_PLUGIN_DIR = os.path.join(os.path.expanduser("~"), ".chipify", "plugins")

_plot_plugins:   list[Type["PlotPlugin"]]   | None = None
_report_plugins: list[Type["ReportPlugin"]] | None = None


# ── Base classes ──────────────────────────────────────────────────────────────

class PlotPlugin:
    """Base class for custom plot modes."""

    #: Display name shown in the mode dropdown (must be unique across all plugins).
    name: str = "Unnamed Plot Plugin"

    def draw(self, fig, ax, valid_df, stim) -> None:
        """
        Draw onto *ax* inside *fig*.

        Parameters
        ----------
        fig : matplotlib.figure.Figure
        ax  : matplotlib.axes.Axes
        valid_df : pd.DataFrame  – rows where sim_error == 'None'
        stim     : Stimuli       – parsed YAML object
        """
        ax.text(
            0.5, 0.5, f"Plugin '{self.name}' has no draw() implementation.",
            ha="center", va="center", transform=ax.transAxes, color="gray",
        )


class ReportPlugin:
    """Base class for custom report sections."""

    #: Display name used in the report-profile UI and as a section header.
    name: str = "Unnamed Report Plugin"

    def render_md(self, valid_df, stim) -> str:
        """Return Markdown text for this section."""
        return f"## {self.name}\n\n*(no content)*\n"

    def render_pdf(self, pdf, valid_df, stim) -> None:
        """Optionally add a page to an open ``matplotlib.backends.backend_pdf.PdfPages`` object."""


# ── Discovery ────────────────────────────────────────────────────────────────

def _plugin_dir() -> str:
    return os.environ.get(_PLUGIN_DIR_ENV, _DEFAULT_PLUGIN_DIR)


def _load_module_from_file(path: str):
    """Import a Python file as a module.  Returns the module or None on error."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"_chipify_plugin_{os.path.basename(path)}", path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        log.warning("Could not load plugin file %s: %s", path, exc)
        return None


def _discover(base_class: type) -> list[type]:
    """Scan the plugin directory and return all subclasses of *base_class*."""
    found: list[type] = []
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
                    found.append(obj)
                    log.info("Loaded plugin: %s from %s", obj.name, filename)
            except Exception:
                pass
    return found


def get_plot_plugins() -> list[Type[PlotPlugin]]:
    """Return all discovered PlotPlugin subclasses (cached after first call)."""
    global _plot_plugins
    if _plot_plugins is None:
        _plot_plugins = _discover(PlotPlugin)
    return _plot_plugins


def get_report_plugins() -> list[Type[ReportPlugin]]:
    """Return all discovered ReportPlugin subclasses (cached after first call)."""
    global _report_plugins
    if _report_plugins is None:
        _report_plugins = _discover(ReportPlugin)
    return _report_plugins


def reload_plugins() -> None:
    """Force re-discovery of all plugins on the next call."""
    global _plot_plugins, _report_plugins
    _plot_plugins   = None
    _report_plugins = None
    log.info("Plugin cache cleared; plugins will reload on next access.")


def plugin_dir() -> str:
    """Return the active plugin directory path."""
    return _plugin_dir()
