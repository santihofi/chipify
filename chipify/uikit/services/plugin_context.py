# Copyright (c) 2026 Santiago Hofwimmer
"""
plugin_context.py – Stable data facade handed to TabPlugin instances.

TabPlugins (see PLUGINS.md) never touch the main window or AppState
directly; everything they need flows through this context:

- read access to the loaded results, datasheet, specs, netlists, history
  runs, and waveform CSVs — always as defensive copies or plain
  JSON-serializable data, so a plugin cannot corrupt application state;
- ``run_async`` for off-thread work (API calls, file crunching) with results
  marshalled back to the Tk main thread;
- ``subscribe_data_changed`` for push-style updates, exception-wrapped so a
  failing plugin callback never breaks the host.

No tkinter imports — the Tk dependency is injected as a plain ``after``
callable, which keeps this module unit-testable headlessly.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from chipify import settings
from chipify import data_loader as _dl
from chipify.uikit.services import transient_loader as _tl
from chipify.uikit.state import AppState

log = logging.getLogger("chipify.plugins.context")

#: Version of the TabPlugin/PluginContext API contract.
PLUGIN_API_VERSION = "1"

_ANALYSIS_KINDS = ("transient", "dc", "ac")


def _jsonable(value: Any) -> Any:
    """Convert *value* into plain JSON-serializable Python data."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    # numpy scalars and anything else exotic
    for caster in (int, float):
        try:
            return caster(value)
        except (TypeError, ValueError):
            continue
    return str(value)


class PluginContext:
    """Read-mostly gateway between a TabPlugin and the application.

    Parameters
    ----------
    app_state:
        The application's :class:`~chipify.uikit.state.AppState`.
    get_yaml_path:
        Zero-arg callable returning the currently selected datasheet path
        (or None).
    tk_after:
        ``widget.after``-compatible callable ``(ms, fn)`` used to marshal
        worker-thread results back onto the Tk main thread.
    set_status:
        Optional ``(text, color)`` callable for the host's status bar.
    plugin_name:
        Used in log messages and thread names.
    """

    def __init__(
        self,
        app_state: AppState,
        get_yaml_path: Callable[[], str | None],
        tk_after: Callable[..., Any],
        set_status: Callable[[str, str], None] | None = None,
        plugin_name: str = "plugin",
    ) -> None:
        self._app_state = app_state
        self._get_yaml_path = get_yaml_path
        self._tk_after = tk_after
        self._set_status = set_status
        self._plugin_name = plugin_name
        self._subscriptions: list[Callable[..., None]] = []

    # ── Versioning ────────────────────────────────────────────────────────────

    @property
    def api_version(self) -> str:
        """Version of the TabPlugin/PluginContext contract."""
        return PLUGIN_API_VERSION

    @property
    def chipify_version(self) -> str:
        """The running chipify package version."""
        import chipify
        return getattr(chipify, "__version__", "unknown")

    # ── Results ───────────────────────────────────────────────────────────────

    def results(self, valid_only: bool = False) -> pd.DataFrame | None:
        """Copy of the currently loaded result DataFrame (None if no data).

        ``valid_only=True`` keeps only rows with ``sim_error == 'None'``.
        The copy is yours — mutating it never affects the application.
        """
        df = self._app_state.active_df
        if df is None:
            return None
        if valid_only:
            df = _dl.valid_rows(df)
        return df.copy()

    def summary(self) -> dict[str, Any]:
        """Run statistics: total / crashes / valid / passed / yield_pct."""
        df = self._app_state.active_df
        if df is None or len(df) == 0:
            return {"total": 0, "crashes": 0, "valid": 0,
                    "passed": 0, "yield_pct": 0.0}
        s = _dl.result_summary(_dl.prepare_results(df))
        return {
            "total": s.total,
            "crashes": s.crashes,
            "valid": s.valid,
            "passed": s.passed,
            "yield_pct": round(s.yield_pct, 2),
        }

    # ── Datasheet / specs ─────────────────────────────────────────────────────

    @property
    def datasheet_path(self) -> str | None:
        """Absolute path of the currently selected datasheet YAML (or None)."""
        return self._get_yaml_path()

    def datasheet_text(self) -> str:
        """Raw text of the current datasheet file, comments included.

        Returns "" when no datasheet is selected or the file is unreadable.
        """
        path = self._get_yaml_path()
        if not path:
            return ""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            log.warning("[%s] could not read datasheet %s: %s",
                        self._plugin_name, path, exc)
            return ""

    def specs(self) -> dict[str, Any]:
        """JSON-serializable view of the parsed datasheet.

        Shape::

            {
              "datasheet": "corner.yaml" | None,
              "parameters": {"temp": [-40, 27, 100], ...},
              "equations": {"gain_lin": "10 ** (gain / 20)", ...},
              "transient_equations": {"vdiff": "v(outp) - v(outn)", ...},
              "tests": {
                "tb_ota_gain": {
                  "measurements": {"gain": {"min": 40.0, "typ": 60.0, "max": 80.0}},
                  "signals": {"ac": ["out"]},
                  "measure": {"gbw": "gain * bandwidth"},
                },
                ...
              },
            }
        """
        path = self._get_yaml_path()
        out: dict[str, Any] = {
            "datasheet": Path(path).name if path else None,
            "parameters": {},
            "tests": {},
        }
        stim = self._app_state.current_stim
        if stim is None:
            return out
        out["parameters"] = {
            str(k): _jsonable(v) for k, v in getattr(stim, "params", {}).items()
        }
        # Datasheet-level custom equations (may be absent on older stims).
        out["equations"] = {
            eq["name"]: eq["expr"]
            for eq in getattr(stim, "equations", None) or []
        }
        out["transient_equations"] = {
            eq["name"]: eq["expr"]
            for eq in getattr(stim, "transient_equations", None) or []
        }
        for test in getattr(stim, "tests", []) or []:
            signals = {
                a.kind: list(a.signals)
                for a in getattr(test, "analyses", []) or []
            }
            out["tests"][test.tb_path] = {
                "measurements": {
                    v.name: {"min": v.vmin, "typ": v.vtyp, "max": v.vmax}
                    for v in getattr(test, "value_lst", []) or []
                },
                "signals": signals,
                "measure": dict(getattr(test, "measure", {}) or {}),
            }
        return out

    # ── Netlists / testbenches ────────────────────────────────────────────────

    def netlists(self) -> dict[str, str]:
        """Rendered SPICE netlist templates per testbench.

        Prefers the in-memory template of the current run; falls back to the
        ``<stem>.spice`` file in the scratch directory from the last netlist
        generation. ``{}`` when nothing has been rendered yet (netlists only
        exist after at least one simulation in this project).
        """
        out: dict[str, str] = {}
        stim = self._app_state.current_stim
        if stim is None:
            return out
        from chipify.uikit.services.netlist_export import _candidate_extensions
        for test in getattr(stim, "tests", []) or []:
            text = getattr(test, "template_str", "") or ""
            if not text:
                stem = Path(test.tb_path).stem
                fast_tmp = Path(settings.FAST_TMP)
                for ext in _candidate_extensions(test):
                    fp = fast_tmp / (stem + ext)
                    if fp.is_file():
                        try:
                            text = fp.read_text(encoding="utf-8", errors="replace")
                        except OSError:
                            text = ""
                        break
            if text:
                out[test.tb_path] = text
        return out

    def testbench_paths(self) -> dict[str, str]:
        """``{tb_name: absolute .sch path}`` for testbenches that exist on disk."""
        out: dict[str, str] = {}
        stim = self._app_state.current_stim
        if stim is None:
            return out
        tb_dir = Path(settings.TB_DIR)
        for test in getattr(stim, "tests", []) or []:
            path = tb_dir / (test.tb_path + ".sch")
            if path.is_file():
                out[test.tb_path] = str(path.resolve())
        return out

    # ── History runs ──────────────────────────────────────────────────────────

    def history_runs(self) -> list[str]:
        """Run labels, newest first (same labels as the History dropdown)."""
        return _dl.list_history_runs(settings.OUT_DIR)

    def load_run(self, label: str) -> pd.DataFrame | None:
        """Load one history run by label; None if it does not exist."""
        path = _dl.resolve_csv_path(label, settings.OUT_DIR)
        if path is None:
            return None
        return _dl.load_csv(path)

    def run_meta(self, label: str) -> dict[str, Any]:
        """Sidecar metadata for a history run ({} when absent)."""
        path = _dl.resolve_csv_path(label, settings.OUT_DIR)
        if path is None:
            return {}
        from chipify import run_meta as _rm
        meta = _rm.read_meta(path)
        return dict(meta) if isinstance(meta, dict) else {}

    # ── Waveforms ─────────────────────────────────────────────────────────────

    def analysis_kinds(self) -> list[str]:
        """Analysis kinds (transient/dc/ac) with data available for this run."""
        df = self._app_state.active_df
        base = df if df is not None else pd.DataFrame()
        return [k for k in _ANALYSIS_KINDS
                if _tl.resolve_analysis_dir(base, settings.OUT_DIR, k)]

    def waveforms(self, kind: str,
                  run_ids: list[str] | None = None) -> pd.DataFrame:
        """Combined per-run waveform DataFrame for *kind* (transient/dc/ac).

        Columns: ``run_id`` plus the X column (time/sweep/frequency) and the
        captured signals. *run_ids* defaults to every valid run of the
        current results — pass an explicit list to limit the load.
        """
        df = self._app_state.active_df
        base = df if df is not None else pd.DataFrame()
        adir = _tl.resolve_analysis_dir(base, settings.OUT_DIR, kind)
        if not adir:
            return pd.DataFrame()
        if run_ids is None:
            run_ids = []
            if df is not None and "run_id" in df.columns:
                run_ids = [str(r).zfill(6)
                           for r in _dl.valid_rows(df)["run_id"]]
        return _tl.load_analysis_df(adir, list(run_ids))

    # ── Project layout / theming ──────────────────────────────────────────────

    @property
    def dirs(self) -> dict[str, str]:
        """Project folders: ``in_dir``, ``out_dir``, ``tb_dir``, ``work_dir``."""
        # Plugin-facing API contract is dict[str, str] — stringify the Path
        # constants at this boundary.
        return {
            "in_dir": str(settings.IN_DIR),
            "out_dir": str(settings.OUT_DIR),
            "tb_dir": str(settings.TB_DIR),
            "work_dir": str(settings.WORK_DIR),
        }

    def theme(self) -> dict[str, str]:
        """Active palette so plugin UIs can match the app.

        Keys: the plot palette (``bg``, ``fg``, ``grid``, ``spine``,
        ``legend_*``, ``accent``) plus widget tokens ``window_bg``, ``panel``,
        ``card_bg``, ``card_border``, ``text_muted``, ``danger``.
        """
        try:
            # Lazy import keeps uikit headless-importable; only a plugin that
            # actually calls theme() pulls in the Qt theme module.
            from chipify.gui_qt import theme as _theme_mod
            mode = _theme_mod.load_theme_name()
            p = _theme_mod.palette(mode)
            palette = dict(_theme_mod.plot_theme(mode))
            palette.update({
                "window_bg": p["bg"],
                "panel": p["panel"],
                "card_bg": p["card_bg"],
                "card_border": p["card_border"],
                "text_muted": p["text_muted"],
                "danger": _theme_mod.DANGER,
            })
            return palette
        except Exception:  # headless / Qt unavailable
            return {
                "bg": "#1a1a1a", "fg": "white", "grid": "gray",
                "spine": "white", "legend_bg": "#2b2b2b",
                "legend_edge": "gray", "legend_text": "white",
                "accent": "#3484F0", "window_bg": "#000000",
                "panel": "#1a1a1a", "card_bg": "#111111",
                "card_border": "#2e2e2e", "text_muted": "#9a9a9a",
                "danger": "#e74c3c",
            }

    # ── Events ────────────────────────────────────────────────────────────────

    def subscribe_data_changed(self, callback: Callable[[], None]) -> None:
        """Call *callback* (no arguments, Tk main thread) when results or the
        datasheet change. Exceptions in the callback are logged, never raised.

        Most plugins should simply implement ``on_data_changed`` instead;
        this hook exists for helper objects that outlive a single method.
        """
        def _wrapped(**_kwargs: Any) -> None:
            try:
                callback()
            except Exception:
                log.exception("[%s] data_changed subscriber failed.",
                              self._plugin_name)

        self._subscriptions.append(_wrapped)
        self._app_state.data_changed.connect(_wrapped)

    def unsubscribe_all(self) -> None:
        """Remove every subscription made through this context (host calls
        this on shutdown; plugins normally never need it)."""
        for cb in self._subscriptions:
            self._app_state.data_changed.disconnect(cb)
        self._subscriptions.clear()

    # ── Threading bridge ──────────────────────────────────────────────────────

    def run_async(
        self,
        work: Callable[[], Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Run *work()* on a background thread; deliver the result on the Tk
        main thread.

        ``on_done(result)`` / ``on_error(exception)`` are invoked via the
        host's ``after()`` — they may safely touch widgets. *work* itself
        runs off-thread and **must not** touch any widget. This is the
        supported way to call external APIs (e.g. an LLM) without freezing
        the GUI.
        """
        def _post(fn: Callable[[], None]) -> None:
            def _guarded() -> None:
                try:
                    fn()
                except Exception:
                    log.exception("[%s] run_async callback failed.",
                                  self._plugin_name)
            try:
                self._tk_after(0, _guarded)
            except Exception:
                log.exception("[%s] run_async could not schedule callback.",
                              self._plugin_name)

        def _runner() -> None:
            try:
                result = work()
            except Exception as exc:
                log.warning("[%s] run_async worker failed: %s",
                            self._plugin_name, exc, exc_info=True)
                if on_error is not None:
                    # Re-bind: `exc` is unset once the except block exits,
                    # but the callback runs later on the Tk thread.
                    err = exc
                    handler = on_error

                    def _deliver_error() -> None:
                        handler(err)

                    _post(_deliver_error)
                return
            if on_done is not None:
                _post(lambda: on_done(result))

        threading.Thread(
            target=_runner, daemon=True,
            name=f"chipify-plugin-{self._plugin_name}",
        ).start()

    # ── Host conveniences ─────────────────────────────────────────────────────

    def set_status(self, text: str, color: str = "#3484F0") -> None:
        """Show *text* in the application's status bar (no-op headlessly)."""
        if self._set_status is None:
            return
        try:
            self._set_status(text, color)
        except Exception:
            log.exception("[%s] set_status failed.", self._plugin_name)
