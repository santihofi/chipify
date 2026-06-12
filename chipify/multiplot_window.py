# Copyright (c) 2026 Santiago Hofwimmer
"""
multiplot_window.py – Multi-Plot Dashboard secondary window for Chipify.

Opens a detached CTkToplevel window containing a scrollable grid of
independently configurable PlotCell instances. The window live-updates
whenever the main application's data changes.

Usage (from SimifyGUI):
    self.multiplot_window = MultiPlotWindow(parent=self)
"""

import os
import tkinter as tk
import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from chipify.plot_manager import PlotManager
from chipify import app_config as _app_config
from chipify.gui.services import data_loader as _dl_mp
from chipify.gui.services import netlist_export as _netlist_export
from chipify.gui.services.scatter_hover import HoverState, ScatterHoverManager
from chipify.gui.services.throttled_redraw import ThrottledRedraw
from chipify.gui.widgets.export_button import attach_export_button
from chipify.gui.widgets.scrollable_option_menu import ScrollableOptionMenu
from chipify.gui.widgets.scrolling import bind_mousewheel as _bind_mousewheel

# ── Shared style ──────────────────────────────────────────────────────────────
# These remain as fallback defaults; live colours come from `_theme_colors()`
# below so the dashboard tracks the global appearance theme.
_BG       = "#000000"
_PANEL    = "#1a1a1a"
_ACCENT   = "#3484F0"


def _theme_colors():
    """Return the current (window_bg, panel, mpl_bg, mpl_fg) palette.

    Reads from chipify.gui.theme so the multiplot window matches whatever
    theme is currently active in the main app (night/dark/light).
    """
    try:
        from chipify.gui import theme as _t
        return _t.BACKGROUND_COLOR, _t.PANEL_COLOR, _t.MPL_BG_COLOR, _t.MPL_FG_COLOR
    except Exception:
        return _BG, _PANEL, _PANEL, "white"


def _plot_theme():
    """Return the active matplotlib palette dict."""
    try:
        from chipify.gui import theme as _t
        return _t.plot_theme()
    except Exception:
        return None

_ALL_MODES = [
    "Histogram",
    "Scatter Plot",
    "Corner Yield Matrix",
    "Correlation Heatmap",
    "Sensitivity (Tornado)",
    "Fail Breakdown (Pie Chart)",
    "Transient",
]

_DIST_TYPES = ["KDE (Smoothed)", "Gauss (Normal)", "None",
               "Uniform", "Log-Normal", "Exponential", "Chi-Squared"]
_BINS_OPTS  = ["Auto", "10", "20", "30", "50", "100"]

# ── PlotCell ──────────────────────────────────────────────────────────────────

class PlotCell(ctk.CTkFrame):
    """A single configurable plot panel inside the dashboard grid."""

    def __init__(self, parent_window, remove_cb, **kwargs):
        _, _panel_now, _, _ = _theme_colors()
        super().__init__(parent_window.grid_frame,
                         fg_color=_panel_now, corner_radius=8, **kwargs)
        self._win      = parent_window   # back-reference to MultiPlotWindow
        self._remove_cb = remove_cb
        self._show_hist_opts = ctk.BooleanVar(value=False)

        # ── Plot state ───────────────────────────────────────────────────────
        self._mode    = ctk.StringVar(value="Histogram")
        self._param   = ctk.StringVar(value="-")
        self._dist    = ctk.StringVar(value="KDE (Smoothed)")
        self._bins    = ctk.StringVar(value="Auto")
        self._group   = ctk.StringVar(value="None")
        self._compare = ctk.StringVar(value="None")
        self._do_zoom = ctk.BooleanVar(value=False)
        self._x_col   = ctk.StringVar(value="-")
        self._y_col   = ctk.StringVar(value="-")
        self._target  = ctk.StringVar(value="-")
        self._sc_plot = None
        self._scatter_df = None
        # Transient-specific state
        self._tran_signals = ctk.StringVar(value="")
        # Default to "First N" with a small N to keep dashboard updates cheap.
        self._tran_run_mode = ctk.StringVar(value="First N")
        self._tran_n = ctk.StringVar(value="10")

        self._build_header()
        self._build_controls()
        self._build_canvas()

    # ── Construction helpers ─────────────────────────────────────────────────

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))
        hdr.grid_columnconfigure(0, weight=1)

        self._mode_menu = ctk.CTkOptionMenu(
            hdr, values=_ALL_MODES, variable=self._mode,
            command=self._on_mode_change,
            width=200, dynamic_resizing=False,
        )
        self._mode_menu.grid(row=0, column=0, sticky="w")

        attach_export_button(
            hdr,
            get_fig=lambda: self._fig,
            suggested_name=lambda: self._mode.get(),
            get_theme=_plot_theme,
            width=90, height=28,
            grid_kwargs={"row": 0, "column": 1, "padx": (6, 0)},
        )

        self._btn_close = ctk.CTkButton(
            hdr, text="×", width=28, height=28,
            fg_color="transparent", border_width=1,
            text_color="gray", hover_color="#3a0000",
            command=self._remove_cb,
        )
        self._btn_close.grid(row=0, column=2, padx=(6, 0))

    def _build_controls(self):
        self._ctrl = ctk.CTkFrame(self, fg_color="transparent")
        self._ctrl.grid(row=1, column=0, sticky="ew", padx=6, pady=(2, 4))
        self._ctrl.grid_columnconfigure(99, weight=1)   # spacer
        self._rebuild_controls()

    def _rebuild_controls(self):
        for w in self._ctrl.winfo_children():
            w.destroy()

        mode = self._mode.get()

        if mode == "Histogram":
            ctk.CTkLabel(self._ctrl, text="Param:").grid(
                row=0, column=0, padx=(0, 4))
            ctk.CTkOptionMenu(
                self._ctrl, variable=self._param,
                values=["-"], width=150, dynamic_resizing=False,
                command=lambda *_: self._request_redraw(),
            ).grid(row=0, column=1, padx=(0, 10))

            ctk.CTkCheckBox(
                self._ctrl,
                text="Histogram options",
                variable=self._show_hist_opts,
                command=self._on_mode_change,
            ).grid(row=0, column=2, padx=(0, 8))

            if self._show_hist_opts.get():
                ctk.CTkLabel(self._ctrl, text="Fit:").grid(row=1, column=0, padx=(0, 4), pady=(4, 0))
                ctk.CTkOptionMenu(
                    self._ctrl, variable=self._dist,
                    values=_DIST_TYPES, width=150, dynamic_resizing=False,
                    command=lambda *_: self._request_redraw(),
                ).grid(row=1, column=1, padx=(0, 10), pady=(4, 0))

                ctk.CTkLabel(self._ctrl, text="Bins:").grid(row=1, column=2, padx=(0, 4), pady=(4, 0))
                ctk.CTkOptionMenu(
                    self._ctrl, variable=self._bins,
                    values=_BINS_OPTS, width=80, dynamic_resizing=False,
                    command=lambda *_: self._request_redraw(),
                ).grid(row=1, column=3, pady=(4, 0))

                ctk.CTkLabel(self._ctrl, text="Group by:").grid(row=2, column=0, padx=(0, 4), pady=(4, 0))
                ctk.CTkOptionMenu(
                    self._ctrl, variable=self._group,
                    values=["None"], width=150, dynamic_resizing=False,
                    command=lambda *_: self._request_redraw(),
                ).grid(row=2, column=1, padx=(0, 10), pady=(4, 0))

                ctk.CTkLabel(self._ctrl, text="Compare:").grid(row=2, column=2, padx=(0, 4), pady=(4, 0))
                ScrollableOptionMenu(
                    self._ctrl, variable=self._compare,
                    values=["None"], width=170, dynamic_resizing=False,
                    command=lambda *_: self._request_redraw(),
                ).grid(row=2, column=3, pady=(4, 0))

                ctk.CTkCheckBox(
                    self._ctrl,
                    text="Fit to plot",
                    variable=self._do_zoom,
                    command=self._request_redraw,
                ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        elif mode in ("Scatter Plot", "Corner Yield Matrix"):
            ctk.CTkLabel(self._ctrl, text="X:").grid(row=0, column=0, padx=(0, 4))
            ctk.CTkOptionMenu(
                self._ctrl, variable=self._x_col,
                values=["-"], width=120, dynamic_resizing=False,
                command=lambda *_: self._request_redraw(),
            ).grid(row=0, column=1, padx=(0, 10))

            ctk.CTkLabel(self._ctrl, text="Y:").grid(row=0, column=2, padx=(0, 4))
            ctk.CTkOptionMenu(
                self._ctrl, variable=self._y_col,
                values=["-"], width=120, dynamic_resizing=False,
                command=lambda *_: self._request_redraw(),
            ).grid(row=0, column=3)

        elif mode == "Sensitivity (Tornado)":
            ctk.CTkLabel(self._ctrl, text="Target:").grid(row=0, column=0, padx=(0, 4))
            ctk.CTkOptionMenu(
                self._ctrl, variable=self._target,
                values=["-"], width=160, dynamic_resizing=False,
                command=lambda *_: self._request_redraw(),
            ).grid(row=0, column=1)

        # Correlation Heatmap + Fail Breakdown have no extra controls — empty row

        elif mode == "Transient":
            ctk.CTkLabel(self._ctrl, text="Signal:").grid(row=0, column=0, padx=(0, 4))
            ctk.CTkOptionMenu(
                self._ctrl, variable=self._tran_signals,
                values=["All Signals"], width=170, dynamic_resizing=False,
                command=lambda *_: self._request_redraw(),
            ).grid(row=0, column=1, padx=(0, 12))

            ctk.CTkLabel(self._ctrl, text="Runs:").grid(row=0, column=2, padx=(0, 4))
            ctk.CTkOptionMenu(
                self._ctrl,
                variable=self._tran_run_mode,
                values=["All Valid", "Failing Only", "First N"],
                width=110, dynamic_resizing=False,
                command=lambda *_: self._request_redraw(),
            ).grid(row=0, column=3, padx=(0, 6))

            ctk.CTkEntry(
                self._ctrl, textvariable=self._tran_n,
                placeholder_text="N", width=52,
            ).grid(row=0, column=4)

    def _build_canvas(self):
        _, _, mpl_bg, _ = _theme_colors()
        if mpl_bg == "white":
            plt.style.use("default")
        else:
            plt.style.use("dark_background")
        self._fig = plt.figure(figsize=(5, 3.5))
        self._fig.patch.set_facecolor(mpl_bg)
        # ax created fresh each redraw via fig.clf()
        self._ax  = self._fig.add_subplot(111)
        self._ax.set_facecolor(mpl_bg)
        self._mpl_canvas = FigureCanvasTkAgg(self._fig, master=self)
        self._mpl_canvas.get_tk_widget().grid(
            row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._hover = ScatterHoverManager(
            self._mpl_canvas, self._fig,
            get_state=self._scatter_hover_state,
            on_point_click=self._on_scatter_point_click,
        )
        self._hover.connect()

    def apply_theme(self):
        """Re-colour cell frame + matplotlib figure to match the current theme."""
        _, panel, mpl_bg, _ = _theme_colors()
        try:
            self.configure(fg_color=panel)
        except Exception:
            pass
        try:
            self._fig.patch.set_facecolor(mpl_bg)
            for _ax in self._fig.get_axes():
                _ax.set_facecolor(mpl_bg)
            self._mpl_canvas.get_tk_widget().configure(background=mpl_bg)
        except Exception:
            pass
        # Re-render so axis labels / spines pick up the dark/light style.
        self._request_redraw()

    def _scatter_hover_state(self):
        """HoverState for the shared scatter hover/click manager."""
        if self._mode.get() != "Scatter Plot":
            return None
        if self._sc_plot is None or self._scatter_df is None:
            return None
        par = getattr(self._win, "_parent", None)
        pst = getattr(par, "app_state", None) if par is not None else None
        stim = pst.current_stim if pst is not None else getattr(par, "current_stim", None)
        return HoverState(
            self._sc_plot, self._scatter_df,
            self._x_col.get(), self._y_col.get(), stim,
        )

    def _on_scatter_point_click(self, row, state, event):
        par = getattr(self._win, "_parent", None)
        meta = getattr(par, "_viewed_run_meta", dict)() if par is not None else {}
        _netlist_export.show_export_menu(
            self._mpl_canvas.get_tk_widget(), event, state.stim, row,
            templates_dir=meta.get("templates_dir", ""))

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _on_mode_change(self, _=None):
        self._rebuild_controls()
        # Repopulate dropdowns with current data if available
        snap = self._win._get_data_snapshot()
        if snap is not None:
            self._populate_dropdowns(*snap)
        self._request_redraw()

    def _request_redraw(self):
        snap = self._win._get_data_snapshot()
        if snap is None:
            return
        self.redraw(*snap)

    def set_remove_callback(self, cb):
        """Attach/replace close callback for this plot cell."""
        self._remove_cb = cb
        self._btn_close.configure(command=self._remove_cb)

    def _populate_dropdowns(self, valid_df, stim, sweep_params, derived_cols, tran_dir=""):
        """Fill option-menu values without triggering a redraw."""
        mode = self._mode.get()

        if valid_df is None:
            return

        all_meas = []
        if stim is not None:
            for t in stim.tests:
                for v in t.value_lst:
                    if v.name in valid_df.columns and v.name not in all_meas:
                        all_meas.append(v.name)

        all_cols = list(dict.fromkeys(
            [c for c in valid_df.columns
             if not c.endswith("_pass") and not c.endswith("_overall_pass")
             and c not in ("global_pass", "sim_error", "simulation_duration_s_total")]
        ))

        if mode == "Histogram":
            options = list(dict.fromkeys(all_meas + derived_cols)) or ["-"]
            self._set_optmenu(self._ctrl, 1, options, self._param)
            if self._show_hist_opts.get():
                group_options = ["None"] + all_cols
                self._set_optmenu(self._ctrl, 1, group_options, self._group, row=2)
                compare_options = self._win._get_compare_run_options()
                self._set_optmenu(self._ctrl, 3, compare_options, self._compare, row=2)

        elif mode == "Scatter Plot":
            options = list(dict.fromkeys(sweep_params + all_meas + derived_cols)) or ["-"]
            self._set_optmenu(self._ctrl, 1, options, self._x_col)
            self._set_optmenu(self._ctrl, 3, options, self._y_col)

        elif mode == "Corner Yield Matrix":
            options = sweep_params or ["-"]
            self._set_optmenu(self._ctrl, 1, options, self._x_col)
            self._set_optmenu(self._ctrl, 3, options, self._y_col)

        elif mode == "Sensitivity (Tornado)":
            options = list(dict.fromkeys(all_meas + derived_cols)) or ["-"]
            self._set_optmenu(self._ctrl, 1, options, self._target)

        elif mode == "Transient":
            tran_sigs = ["All Signals"]
            if stim is not None:
                for t in stim.tests:
                    for sig in getattr(t, "transient_signals", []):
                        if sig not in tran_sigs:
                            tran_sigs.append(sig)
            for eq in _app_config.load_config().get("transient_equations", []):
                name = eq.get("name", "").strip()
                if name and name not in tran_sigs:
                    tran_sigs.append(name)
            self._set_optmenu(self._ctrl, 1, tran_sigs, self._tran_signals)

    @staticmethod
    def _set_optmenu(parent, grid_col, options, var, row=0):
        """Update the CTkOptionMenu at grid column grid_col inside parent."""
        for w in parent.grid_slaves(row=row, column=grid_col):
            w.configure(values=options)
            if var.get() not in options:
                var.set(options[0])

    # ── Public API ───────────────────────────────────────────────────────────

    def redraw(self, valid_df, stim, sweep_params, derived_cols, tran_dir=""):
        """Repopulate dropdowns then re-render the plot."""
        self._populate_dropdowns(valid_df, stim, sweep_params, derived_cols)

        mode = self._mode.get()

        _, _, mpl_bg, _ = _theme_colors()
        plot_th = _plot_theme()

        # Ghost-safe axis rebuild (see context.md §3 "Matplotlib Ghosting")
        self._fig.clf()
        self._fig.patch.set_facecolor(mpl_bg)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_facecolor(mpl_bg)
        self._sc_plot = None
        self._scatter_df = None
        self._hover.invalidate()  # fig.clf() destroyed the tooltip annotation

        try:
            if mode == "Histogram":
                param = self._param.get()
                if param == "-" or param not in valid_df.columns:
                    self._ax.text(0.5, 0.5, "Select a parameter",
                                  ha="center", va="center", color="gray",
                                  transform=self._ax.transAxes)
                    self._mpl_canvas.draw_idle()
                    return
                PlotManager.draw_histogram(
                    fig=self._fig,
                    ax=self._ax,
                    canvas=self._mpl_canvas,
                    valid_df=valid_df,
                    current_stim=stim,
                    param=param,
                    dist_type=self._dist.get(),
                    group_col=self._group.get(),
                    bins_val=self._bins.get(),
                    do_zoom=self._do_zoom.get(),
                    comp_run=self._compare.get(),
                    theme=plot_th,
                )
                return   # draw_histogram already calls canvas.draw()

            if mode == "Transient":
                # Determine which signals to plot from the dropdown selection.
                sig_sel = self._tran_signals.get().strip()
                if sig_sel == "All Signals" or not sig_sel:
                    # Collect all transient signals from stim
                    signals = []
                    if stim is not None:
                        for t in stim.tests:
                            for s in getattr(t, "transient_signals", []):
                                if s not in signals:
                                    signals.append(s)
                    for eq in _app_config.load_config().get("transient_equations", []):
                        name = eq.get("name", "").strip()
                        if name and name not in signals:
                            signals.append(name)
                else:
                    signals = [sig_sel]

                # Build run_id list based on run-filter mode.
                run_ids: list = []
                run_mode = self._tran_run_mode.get()
                par = self._win._parent
                pst = getattr(par, "app_state", None)
                parent_df = pst.active_df if pst is not None else getattr(par, "current_df", None)
                if parent_df is not None and "run_id" in parent_df.columns:
                    if run_mode == "All Valid":
                        run_ids = list(
                            parent_df[parent_df.get("sim_error", "None") == "None"]["run_id"].astype(str)
                        )
                    elif run_mode == "Failing Only":
                        if "global_pass" in parent_df.columns:
                            run_ids = list(
                                parent_df[parent_df["global_pass"] == False]["run_id"].astype(str)
                            )
                    else:  # First N
                        try:
                            n = int(self._tran_n.get())
                        except ValueError:
                            n = 10
                        run_ids = list(
                            parent_df[parent_df.get("sim_error", "None") == "None"]["run_id"]
                            .astype(str).head(n)
                        )
                run_ids = run_ids[:500]  # hard cap

                pass_map: dict = {}
                if parent_df is not None and "global_pass" in (parent_df.columns if parent_df is not None else []):
                    for _, row in parent_df[["run_id", "global_pass"]].dropna(subset=["run_id"]).iterrows():
                        pass_map[str(row["run_id"]).zfill(6)] = bool(row["global_pass"])

                equations = _app_config.load_config().get("transient_equations", [])
                PlotManager.draw_transient_plot(
                    self._fig, self._mpl_canvas,
                    tran_dir, run_ids, signals,
                    pass_map=pass_map,
                    bg_color=mpl_bg,
                    equations=equations,
                    theme=plot_th,
                )
                return   # draw_transient_plot already calls canvas.draw()

            # All other modes use draw_adv_plot
            self._sc_plot, self._scatter_df = PlotManager.draw_adv_plot(
                fig=self._fig,
                ax_dummy=self._ax,
                canvas=self._mpl_canvas,
                valid_df=valid_df,
                current_stim=stim,
                mode=mode,
                x_col=self._x_col.get(),
                y_col=self._y_col.get(),
                target=self._target.get(),
                bg_color=mpl_bg,
                theme=plot_th,
            )
            # Fill available panel space better for adv plots.
            if mode == "Correlation Heatmap":
                self._fig.subplots_adjust(left=0.20, right=0.96, bottom=0.22, top=0.90)
            elif mode == "Scatter Plot":
                self._fig.subplots_adjust(left=0.12, right=0.97, bottom=0.14, top=0.90)
            else:
                self._fig.subplots_adjust(left=0.12, right=0.97, bottom=0.12, top=0.90)
            self._mpl_canvas.draw_idle()
        except Exception as exc:
            self._fig.clf()
            self._fig.patch.set_facecolor(mpl_bg)
            ax = self._fig.add_subplot(111)
            ax.set_facecolor(mpl_bg)
            ax.text(0.5, 0.5, f"Error:\n{exc}",
                    ha="center", va="center", color="#e74c3c",
                    fontsize=8, wrap=True, transform=ax.transAxes)
            self._mpl_canvas.draw_idle()

    def get_config(self) -> dict:
        return {
            "mode":         self._mode.get(),
            "param":        self._param.get(),
            "dist":         self._dist.get(),
            "bins":         self._bins.get(),
            "group":        self._group.get(),
            "compare":      self._compare.get(),
            "do_zoom":      bool(self._do_zoom.get()),
            "x_col":        self._x_col.get(),
            "y_col":        self._y_col.get(),
            "target":       self._target.get(),
            "tran_signals": self._tran_signals.get(),
            "tran_run_mode": self._tran_run_mode.get(),
            "tran_n":       self._tran_n.get(),
        }

    def close_figure(self):
        """Release the matplotlib figure from pyplot's global registry.

        Without this, every removed cell leaks its figure (pyplot keeps a
        reference) and matplotlib starts warning after 20 open figures.
        """
        try:
            plt.close(self._fig)
        except Exception:
            pass

    def apply_config(self, cfg: dict):
        self._mode.set(cfg.get("mode",   "Histogram"))
        self._param.set(cfg.get("param", "-"))
        self._dist.set(cfg.get("dist",   "KDE (Smoothed)"))
        self._bins.set(cfg.get("bins",   "Auto"))
        self._group.set(cfg.get("group", "None"))
        self._compare.set(cfg.get("compare", "None"))
        self._do_zoom.set(bool(cfg.get("do_zoom", False)))
        self._x_col.set(cfg.get("x_col", "-"))
        self._y_col.set(cfg.get("y_col", "-"))
        self._target.set(cfg.get("target", "-"))
        self._tran_signals.set(cfg.get("tran_signals", ""))
        self._tran_run_mode.set(cfg.get("tran_run_mode", "First N"))
        self._tran_n.set(cfg.get("tran_n", "10"))
        self._rebuild_controls()


# ── MultiPlotWindow ───────────────────────────────────────────────────────────

class MultiPlotWindow(ctk.CTkToplevel):
    """
    Detached secondary window hosting a scrollable grid of PlotCell instances.

    Parameters
    ----------
    parent : SimifyGUI
        The main application window. Used to read `current_df`, `current_stim`,
        `sweep_params`, and `_derived_cols`.
    """

    _DEFAULT_COLS = 2

    def __init__(self, parent, **kwargs):
        bg, _, _, _ = _theme_colors()
        super().__init__(parent, fg_color=bg, **kwargs)
        self.title("Multi-Plot Dashboard")
        self.geometry("1200x820")
        self.minsize(640, 480)

        self._parent = parent
        self._cells: list[PlotCell] = []
        self._ncols  = self._DEFAULT_COLS

        self._build_toolbar()
        self._build_body()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._live_throttle = ThrottledRedraw(
            self, self.refresh_all, _app_config.get_live_throttle_ms()
        )
        st = getattr(parent, "app_state", None)
        if st is not None:
            try:
                st.on_data_chunk_added.connect(self._on_live_chunk_mp)
                st.data_changed.connect(self._on_data_changed_mp)
            except Exception:
                pass

    def _on_live_chunk_mp(self, **kwargs: object) -> None:
        try:
            if _app_config.is_live_plotting_enabled():
                self._live_throttle.request()
        except Exception:
            pass

    def _on_data_changed_mp(self, **kwargs: object) -> None:
        try:
            self._live_throttle.force_now()
        except Exception:
            pass

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        _, panel, _, _ = _theme_colors()
        self._toolbar = ctk.CTkFrame(self, fg_color=panel, corner_radius=0, height=48)
        tb = self._toolbar
        tb.pack(side="top", fill="x")
        tb.pack_propagate(False)

        ctk.CTkLabel(
            tb, text="Multi-Plot Dashboard",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left", padx=14)

        ctk.CTkButton(
            tb, text="+ Add Plot", width=100,
            command=self._action_add,
        ).pack(side="left", padx=(4, 4), pady=8)

        ctk.CTkButton(
            tb, text="↻ Refresh", width=90,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
            command=self.refresh_all,
        ).pack(side="left", padx=(0, 20), pady=8)

        # Columns spinner
        ctk.CTkLabel(tb, text="Columns:").pack(side="left", padx=(0, 4))
        self._cols_var = ctk.StringVar(value=str(self._DEFAULT_COLS))
        ctk.CTkOptionMenu(
            tb, values=["1", "2", "3"],
            variable=self._cols_var, width=60,
            command=self._on_cols_change,
        ).pack(side="left")

    def _build_body(self):
        bg, _, _, _ = _theme_colors()
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=bg, corner_radius=0)
        self._scroll.pack(side="top", fill="both", expand=True)
        _bind_mousewheel(self._scroll)

        self.grid_frame = self._scroll
        for c in range(self._ncols):
            self.grid_frame.grid_columnconfigure(c, weight=1, uniform="col")

        self._placeholder = ctk.CTkLabel(
            self.grid_frame,
            text='Click  "+ Add Plot"  to add a panel.',
            text_color="gray", font=ctk.CTkFont(size=14),
        )
        self._placeholder.grid(row=0, column=0,
                               columnspan=self._ncols,
                               pady=80)

    # ── Grid management ──────────────────────────────────────────────────────

    def _reflow(self):
        """Re-place all cells in the grid after add/remove/col-change."""
        for cell in self._cells:
            cell.grid_forget()

        ncols = self._ncols
        for i, cell in enumerate(self._cells):
            r, c = divmod(i, ncols)
            cell.grid(row=r, column=c, padx=8, pady=8, sticky="nsew")
            self.grid_frame.grid_rowconfigure(r, weight=1)

        # Show/hide placeholder
        if self._cells:
            self._placeholder.grid_remove()
        else:
            self._placeholder.grid(row=0, column=0,
                                   columnspan=ncols, pady=80)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _action_add(self):
        self.add_cell()

    def _on_cols_change(self, _=None):
        self._ncols = int(self._cols_var.get())
        for c in range(3):
            self.grid_frame.grid_columnconfigure(
                c, weight=(1 if c < self._ncols else 0),
                uniform=("col" if c < self._ncols else ""),
            )
        self._reflow()

    def _on_close(self):
        # Persist cell configs so they can be restored next time
        try:
            from chipify import app_config
            cfg = app_config.load_config()
            cfg["multiplot_config"] = [c.get_config() for c in self._cells]
            app_config.save_config(cfg)
        except Exception:
            pass
        try:
            st = getattr(self._parent, "app_state", None)
            if st is not None:
                st.on_data_chunk_added.disconnect(self._on_live_chunk_mp)
                st.data_changed.disconnect(self._on_data_changed_mp)
        except Exception:
            pass
        # Release every cell's matplotlib figure from pyplot's registry.
        for cell in self._cells:
            cell.close_figure()
        # Clear parent's reference so the button can re-open later
        try:
            self._parent.multiplot_window = None
        except Exception:
            pass
        self.destroy()

    # ── Public API ───────────────────────────────────────────────────────────

    def add_cell(self, mode: str = "Histogram", config: dict | None = None):
        """Append a new PlotCell to the grid and trigger an initial draw."""
        cell = PlotCell(parent_window=self, remove_cb=lambda: None)
        cell.set_remove_callback(lambda _cell=cell: self.remove_cell(_cell))

        if config:
            cell.apply_config(config)
        elif mode != "Histogram":
            cell._mode.set(mode)
            cell._rebuild_controls()

        self._cells.append(cell)
        self._reflow()

        # Draw immediately if data is available
        snap = self._get_data_snapshot()
        if snap is not None:
            cell.redraw(*snap)

        return cell

    def remove_cell(self, cell: PlotCell):
        if cell in self._cells:
            self._cells.remove(cell)
        cell.grid_forget()
        cell.close_figure()
        cell.destroy()
        self._reflow()

    def refresh_all(self):
        """Redraw every cell with the latest data from the parent window."""
        snap = self._get_data_snapshot()
        if snap is None:
            return
        for cell in self._cells:
            try:
                cell.redraw(*snap)
            except Exception:
                pass

    def change_theme(self, _mode: str | None = None) -> None:
        """Re-colour the dashboard, toolbar, and every plot cell to match the active theme."""
        bg, panel, _, _ = _theme_colors()
        try:
            self.configure(fg_color=bg)
        except Exception:
            pass
        try:
            self._toolbar.configure(fg_color=panel)
        except Exception:
            pass
        try:
            self._scroll.configure(fg_color=bg)
        except Exception:
            pass
        for cell in self._cells:
            try:
                cell.apply_theme()
            except Exception:
                pass

    def _get_data_snapshot(self):
        """
        Return (valid_df, stim, sweep_params, derived_cols, tran_dir) from parent,
        or None if no data is loaded.
        Always filters out error rows per the project gotcha.
        """
        p = self._parent
        state = getattr(p, "app_state", None)
        df_src = state.active_df if state is not None else getattr(p, "current_df", None)
        if df_src is None:
            return None
        df = df_src

        stim = None
        if state is not None:
            stim = state.current_stim
        if stim is None:
            stim = getattr(p, "current_stim", None)

        valid_df = df[df["sim_error"] == "None"].copy() if "sim_error" in df.columns else df.copy()

        sweep_params = getattr(p, "sweep_params", [])
        try:
            if stim is not None and not valid_df.empty:
                sweep_params = _dl_mp.compute_plot_cols(valid_df, stim).sweep_params
        except Exception:
            pass

        derived_cols = getattr(p, "_derived_cols", [])
        tran_dir = p._resolve_tran_dir() if callable(getattr(p, "_resolve_tran_dir", None)) else ""
        return valid_df, stim, sweep_params, derived_cols, tran_dir

    def _get_compare_run_options(self):
        """Return compare-run options aligned with the main histogram tab semantics."""
        opts = ["None"]
        try:
            hist_vals = list(getattr(self._parent, "history_dropdown").cget("values") or [])
            if "Latest (simulation_results)" not in hist_vals:
                hist_vals.insert(0, "Latest (simulation_results)")
            for v in hist_vals:
                if v and v != "No runs found" and v not in opts:
                    opts.append(v)
        except Exception:
            pass
        return opts

    def restore_from_config(self, cell_configs: list):
        """Re-create cells from a previously persisted config list."""
        for cfg in cell_configs:
            self.add_cell(config=cfg)
