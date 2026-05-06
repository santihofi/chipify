"""
multiplot_window.py – Multi-Plot Dashboard secondary window for Chipify.

Opens a detached CTkToplevel window containing a scrollable grid of
independently configurable PlotCell instances. The window live-updates
whenever the main application's data changes.

Usage (from SimifyGUI):
    self.multiplot_window = MultiPlotWindow(parent=self)
"""

import tkinter as tk
import customtkinter as ctk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from chipify.plot_manager import PlotManager

# ── Shared style (mirrors gui_tk.py constants) ────────────────────────────────
_BG       = "#000000"
_PANEL    = "#1a1a1a"
_ACCENT   = "#3484F0"

_ALL_MODES = [
    "Histogram",
    "Scatter Plot",
    "Corner Yield Matrix",
    "Correlation Heatmap",
    "Sensitivity (Tornado)",
    "Fail Breakdown (Pie Chart)",
]

_DIST_TYPES = ["KDE (Smoothed)", "Gauss (Normal)", "None",
               "Uniform", "Log-Normal", "Exponential", "Chi-Squared"]
_BINS_OPTS  = ["Auto", "10", "20", "30", "50", "100"]

# ── PlotCell ──────────────────────────────────────────────────────────────────

class PlotCell(ctk.CTkFrame):
    """A single configurable plot panel inside the dashboard grid."""

    def __init__(self, parent_window, remove_cb, **kwargs):
        super().__init__(parent_window.grid_frame,
                         fg_color=_PANEL, corner_radius=8, **kwargs)
        self._win      = parent_window   # back-reference to MultiPlotWindow
        self._remove_cb = remove_cb

        # ── Plot state ───────────────────────────────────────────────────────
        self._mode    = ctk.StringVar(value="Histogram")
        self._param   = ctk.StringVar(value="-")
        self._dist    = ctk.StringVar(value="KDE (Smoothed)")
        self._bins    = ctk.StringVar(value="Auto")
        self._x_col   = ctk.StringVar(value="-")
        self._y_col   = ctk.StringVar(value="-")
        self._target  = ctk.StringVar(value="-")

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

        ctk.CTkButton(
            hdr, text="✕", width=28, height=28,
            fg_color="transparent", border_width=1,
            text_color="gray", hover_color="#3a0000",
            command=self._remove_cb,
        ).grid(row=0, column=1, padx=(6, 0))

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
                values=["-"], width=130, dynamic_resizing=False,
                command=lambda *_: self._request_redraw(),
            ).grid(row=0, column=1, padx=(0, 10))

            ctk.CTkLabel(self._ctrl, text="Fit:").grid(row=0, column=2, padx=(0, 4))
            ctk.CTkOptionMenu(
                self._ctrl, variable=self._dist,
                values=_DIST_TYPES, width=130, dynamic_resizing=False,
                command=lambda *_: self._request_redraw(),
            ).grid(row=0, column=3, padx=(0, 10))

            ctk.CTkLabel(self._ctrl, text="Bins:").grid(row=0, column=4, padx=(0, 4))
            ctk.CTkOptionMenu(
                self._ctrl, variable=self._bins,
                values=_BINS_OPTS, width=70, dynamic_resizing=False,
                command=lambda *_: self._request_redraw(),
            ).grid(row=0, column=5)

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

    def _build_canvas(self):
        plt.style.use("dark_background")
        self._fig = plt.figure(figsize=(5, 3.5))
        self._fig.patch.set_facecolor(_PANEL)
        # ax created fresh each redraw via fig.clf()
        self._ax  = self._fig.add_subplot(111)
        self._ax.set_facecolor(_PANEL)
        self._canvas = FigureCanvasTkAgg(self._fig, master=self)
        self._canvas.get_tk_widget().grid(
            row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

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

    def _populate_dropdowns(self, valid_df, stim, sweep_params, derived_cols):
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
            self._ctrl.winfo_children()  # ensure built
            self._set_optmenu(self._ctrl, 1, options, self._param)

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

    @staticmethod
    def _set_optmenu(parent, grid_col, options, var):
        """Update the CTkOptionMenu at grid column grid_col inside parent."""
        for w in parent.grid_slaves(row=0, column=grid_col):
            w.configure(values=options)
            if var.get() not in options:
                var.set(options[0])

    # ── Public API ───────────────────────────────────────────────────────────

    def redraw(self, valid_df, stim, sweep_params, derived_cols):
        """Repopulate dropdowns then re-render the plot."""
        self._populate_dropdowns(valid_df, stim, sweep_params, derived_cols)

        mode = self._mode.get()

        # Ghost-safe axis rebuild (see context.md §3 "Matplotlib Ghosting")
        self._fig.clf()
        self._ax = self._fig.add_subplot(111)
        self._ax.set_facecolor(_PANEL)

        try:
            if mode == "Histogram":
                param = self._param.get()
                if param == "-" or param not in valid_df.columns:
                    self._ax.text(0.5, 0.5, "Select a parameter",
                                  ha="center", va="center", color="gray",
                                  transform=self._ax.transAxes)
                    self._canvas.draw_idle()
                    return
                PlotManager.draw_histogram(
                    fig=self._fig,
                    ax=self._ax,
                    canvas=self._canvas,
                    valid_df=valid_df,
                    current_stim=stim,
                    param=param,
                    dist_type=self._dist.get(),
                    group_col="None",
                    bins_val=self._bins.get(),
                    do_zoom=False,
                    comp_run="None",
                )
                return   # draw_histogram already calls canvas.draw()

            # All other modes use draw_adv_plot
            PlotManager.draw_adv_plot(
                fig=self._fig,
                ax_dummy=None,      # None → draw_adv_plot rebuilds ax itself
                canvas=self._canvas,
                valid_df=valid_df,
                current_stim=stim,
                mode=mode,
                x_col=self._x_col.get(),
                y_col=self._y_col.get(),
                target=self._target.get(),
                bg_color=_PANEL,
            )
        except Exception as exc:
            self._fig.clf()
            ax = self._fig.add_subplot(111)
            ax.set_facecolor(_PANEL)
            ax.text(0.5, 0.5, f"Error:\n{exc}",
                    ha="center", va="center", color="#e74c3c",
                    fontsize=8, wrap=True, transform=ax.transAxes)
            self._canvas.draw_idle()

    def get_config(self) -> dict:
        return {
            "mode":   self._mode.get(),
            "param":  self._param.get(),
            "dist":   self._dist.get(),
            "bins":   self._bins.get(),
            "x_col":  self._x_col.get(),
            "y_col":  self._y_col.get(),
            "target": self._target.get(),
        }

    def apply_config(self, cfg: dict):
        self._mode.set(cfg.get("mode",   "Histogram"))
        self._param.set(cfg.get("param", "-"))
        self._dist.set(cfg.get("dist",   "KDE (Smoothed)"))
        self._bins.set(cfg.get("bins",   "Auto"))
        self._x_col.set(cfg.get("x_col", "-"))
        self._y_col.set(cfg.get("y_col", "-"))
        self._target.set(cfg.get("target", "-"))
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
        super().__init__(parent, fg_color=_BG, **kwargs)
        self.title("Multi-Plot Dashboard")
        self.geometry("1200x820")
        self.minsize(640, 480)

        self._parent = parent
        self._cells: list[PlotCell] = []
        self._ncols  = self._DEFAULT_COLS

        self._build_toolbar()
        self._build_body()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = ctk.CTkFrame(self, fg_color=_PANEL, corner_radius=0, height=48)
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
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=_BG, corner_radius=0)
        self._scroll.pack(side="top", fill="both", expand=True)

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
        # Clear parent's reference so the button can re-open later
        try:
            self._parent.multiplot_window = None
        except Exception:
            pass
        self.destroy()

    # ── Public API ───────────────────────────────────────────────────────────

    def add_cell(self, mode: str = "Histogram", config: dict | None = None):
        """Append a new PlotCell to the grid and trigger an initial draw."""
        cell = PlotCell(
            parent_window=self,
            remove_cb=lambda c=None: self.remove_cell(c),
        )
        # Fix the lambda closure properly
        cell._remove_cb = lambda _cell=cell: self.remove_cell(_cell)

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

    def _get_data_snapshot(self):
        """
        Return (valid_df, stim, sweep_params, derived_cols) from parent,
        or None if no data is loaded.
        Always filters out error rows per the project gotcha.
        """
        p = self._parent
        if getattr(p, "current_df", None) is None:
            return None
        df = p.current_df
        valid_df = df[df["sim_error"] == "None"].copy() if "sim_error" in df.columns else df.copy()
        stim         = getattr(p, "current_stim",  None)
        sweep_params = getattr(p, "sweep_params",  [])
        derived_cols = getattr(p, "_derived_cols", [])
        return valid_df, stim, sweep_params, derived_cols

    def restore_from_config(self, cell_configs: list):
        """Re-create cells from a previously persisted config list."""
        for cfg in cell_configs:
            self.add_cell(config=cfg)
