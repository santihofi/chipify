"""
settings_window.py – Modal settings dialog for persistent user preferences.

Extracted verbatim from gui_tk.py (lines 59-256).  The class is referenced
from gui_tk.py via ``from chipify.gui.widgets.settings_window import SettingsWindow``.
"""
from __future__ import annotations

import os

import customtkinter as ctk

from chipify import app_config, util


class SettingsWindow(ctk.CTkToplevel):
    """Modal settings dialog for persistent user preferences."""

    _ENGINE_HINTS = {
        "ngspice": "ngspice: default SPICE3 simulator",
        "vacask": "vacask: Verilog-A Circuit Analysis Kernel (PyOPUS required)",
    }
    _VALID_ENGINES = ["ngspice", "vacask"]

    def __init__(self, parent: ctk.CTk) -> None:
        super().__init__(parent)
        self.title("Global Settings")
        self.geometry("520x600")
        self.resizable(False, False)

        # grab_set needs a small delay so the window is fully mapped first
        self.after(50, self.grab_set)

        self._main_app = parent

        self._config = app_config.load_config()
        max_cores = os.cpu_count() or 1
        current_cores = int(self._config.get("num_cores") or util.get_num_cores())
        simulator_engine = self._config.get("simulator_engine", "ngspice")
        process_mode = self._config.get("process_start_method", "auto")
        chunk_size_mode = str(self._config.get("chunk_size", "auto"))
        vacask_binary = self._config.get("vacask_binary", "vacask")
        vacask_src = self._config.get("vacask_netlist_source", "xschem")
        current_theme = self._config.get("theme", "night")

        if simulator_engine not in self._VALID_ENGINES:
            simulator_engine = "ngspice"
        if process_mode not in ["auto", "forkserver", "spawn"]:
            process_mode = "auto"
        # Must accept every value the chunk-size menu offers, otherwise a
        # saved 64/128/256 silently resets to "auto" on the next dialog open.
        if chunk_size_mode not in ["auto", "1", "2", "4", "8", "16", "32",
                                   "64", "128", "256"]:
            chunk_size_mode = "auto"
        if vacask_src not in ["xschem", "ng2vc"]:
            vacask_src = "xschem"
        if current_theme not in ["night", "dark", "light"]:
            current_theme = "night"

        # ── Header ──────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self, text="Global Settings",
            font=ctk.CTkFont(size=17, weight="bold")
        ).pack(pady=(22, 10))

        # ── Tabs ────────────────────────────────────────────────────────────
        self._tabs = ctk.CTkTabview(self)
        self._tabs.pack(fill="both", expand=True, padx=14, pady=(0, 4))
        tab_sim = self._tabs.add("Simulation")
        tab_perf = self._tabs.add("Performance")
        tab_ui = self._tabs.add("Interface")

        # ── num_cores section ───────────────────────────────────────────────
        cores_outer = ctk.CTkFrame(tab_sim, fg_color="transparent")
        cores_outer.pack(fill="x", padx=16, pady=(8, 0))

        row = ctk.CTkFrame(cores_outer, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text="CPU Cores for Simulation:", anchor="w").pack(side="left")
        self._cores_lbl = ctk.CTkLabel(row, text=str(current_cores),
                                       font=ctk.CTkFont(weight="bold"), width=28)
        self._cores_lbl.pack(side="right")

        self._cores_var = ctk.IntVar(value=current_cores)
        self._slider = ctk.CTkSlider(
            cores_outer,
            from_=1, to=max_cores,
            number_of_steps=max(1, max_cores - 1),
            variable=self._cores_var,
            command=self._on_cores_change,
        )
        self._slider.pack(fill="x", pady=(6, 2))

        ctk.CTkLabel(
            cores_outer,
            text=f"Range: 1 – {max_cores} logical cores",
            text_color="gray", font=ctk.CTkFont(size=11)
        ).pack(anchor="w")

        # ── simulator engine section ────────────────────────────────────────
        self._sim_outer = ctk.CTkFrame(tab_sim, fg_color="transparent")
        self._sim_outer.pack(fill="x", padx=16, pady=(18, 0))
        ctk.CTkLabel(self._sim_outer, text="Simulation Engine:", anchor="w").pack(anchor="w")
        self._sim_engine_var = ctk.StringVar(value=simulator_engine)
        self._sim_engine_menu = ctk.CTkOptionMenu(
            self._sim_outer,
            variable=self._sim_engine_var,
            values=self._VALID_ENGINES,
            dynamic_resizing=False,
            width=180,
            command=self._on_engine_change,
        )
        self._sim_engine_menu.pack(anchor="w", pady=(6, 2))
        self._sim_engine_hint = ctk.CTkLabel(
            self._sim_outer,
            text=self._ENGINE_HINTS.get(simulator_engine, ""),
            text_color="gray", font=ctk.CTkFont(size=11)
        )
        self._sim_engine_hint.pack(anchor="w")

        # ── VACASK-specific settings ─────────────────────────────────────────
        self._vacask_frame = ctk.CTkFrame(tab_sim, fg_color="transparent")

        vc_bin_row = ctk.CTkFrame(self._vacask_frame, fg_color="transparent")
        vc_bin_row.pack(fill="x")
        ctk.CTkLabel(vc_bin_row, text="VACASK Binary:", anchor="w", width=130).pack(side="left")
        self._vacask_binary_var = ctk.StringVar(value=vacask_binary)
        ctk.CTkEntry(
            vc_bin_row, textvariable=self._vacask_binary_var,
            placeholder_text="vacask", width=200,
        ).pack(side="left", padx=(8, 0))

        vc_src_row = ctk.CTkFrame(self._vacask_frame, fg_color="transparent")
        vc_src_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(vc_src_row, text="Netlist Source:", anchor="w", width=130).pack(side="left")
        self._vacask_src_var = ctk.StringVar(value=vacask_src)
        ctk.CTkOptionMenu(
            vc_src_row,
            variable=self._vacask_src_var,
            values=["xschem", "ng2vc"],
            dynamic_resizing=False,
            width=200,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            self._vacask_frame,
            text="Requires PyOPUS  (pip install chipify[vacask])  and vacask on PATH",
            text_color="gray", font=ctk.CTkFont(size=11), wraplength=380,
        ).pack(anchor="w", pady=(6, 0))

        if simulator_engine == "vacask":
            self._vacask_frame.pack(fill="x", padx=16, pady=(8, 0),
                                    after=self._sim_outer)

        # ── process start method section ────────────────────────────────────
        proc_outer = ctk.CTkFrame(tab_perf, fg_color="transparent")
        proc_outer.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkLabel(proc_outer, text="Multiprocessing Start Method:", anchor="w").pack(anchor="w")
        self._proc_mode_var = ctk.StringVar(value=process_mode)
        self._proc_mode_menu = ctk.CTkOptionMenu(
            proc_outer,
            variable=self._proc_mode_var,
            values=["auto", "forkserver", "spawn"],
            dynamic_resizing=False,
            width=180,
        )
        self._proc_mode_menu.pack(anchor="w", pady=(6, 2))
        ctk.CTkLabel(
            proc_outer,
            text="auto = forkserver on Linux, spawn elsewhere",
            text_color="gray", font=ctk.CTkFont(size=11)
        ).pack(anchor="w")

        # ── chunk size section ───────────────────────────────────────────────
        chunk_outer = ctk.CTkFrame(tab_perf, fg_color="transparent")
        chunk_outer.pack(fill="x", padx=16, pady=(18, 0))
        ctk.CTkLabel(chunk_outer, text="Batch Chunk Size:", anchor="w").pack(anchor="w")
        self._chunk_var = ctk.StringVar(value=chunk_size_mode)
        self._chunk_menu = ctk.CTkOptionMenu(
            chunk_outer,
            variable=self._chunk_var,
            values=["auto", "1", "2", "4", "8", "16", "32", "64", "128", "256"],
            dynamic_resizing=False,
            width=180,
        )
        self._chunk_menu.pack(anchor="w", pady=(6, 2))
        ctk.CTkLabel(
            chunk_outer,
            text="Higher values can improve throughput, lower values improve responsiveness",
            text_color="gray", font=ctk.CTkFont(size=11)
        ).pack(anchor="w")

        # ── Live plotting ─────────────────────────────────────────────────────
        live_outer = ctk.CTkFrame(tab_ui, fg_color="transparent")
        live_outer.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkLabel(
            live_outer,
            text="Live plotting during simulation",
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w")

        self._live_plot_var = ctk.BooleanVar(value=app_config.is_live_plotting_enabled())
        ctk.CTkCheckBox(
            live_outer,
            text="Enable live plotting during simulation",
            variable=self._live_plot_var,
            command=self._on_live_plot_toggle,
        ).pack(anchor="w", pady=(8, 4))

        throttle_row = ctk.CTkFrame(live_outer, fg_color="transparent")
        throttle_row.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(throttle_row, text="Plot refresh interval (ms):").pack(side="left", padx=(0, 8))
        self._throttle_var = ctk.StringVar(value=str(app_config.get_live_throttle_ms()))
        throttle_entry = ctk.CTkEntry(throttle_row, textvariable=self._throttle_var, width=72)
        throttle_entry.pack(side="left")
        throttle_entry.bind("<FocusOut>", self._on_throttle_change_evt)
        throttle_entry.bind("<Return>", self._on_throttle_change_evt)
        ctk.CTkLabel(
            live_outer,
            text="500–5000 ms (lower = more frequent redraws)",
            text_color="gray",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(4, 0))

        # ── Appearance Theme ─────────────────────────────────────────────────
        theme_outer = ctk.CTkFrame(tab_ui, fg_color="transparent")
        theme_outer.pack(fill="x", padx=16, pady=(18, 0))
        ctk.CTkLabel(theme_outer, text="Appearance Theme:", anchor="w").pack(anchor="w")
        self._theme_var = ctk.StringVar(value=current_theme)
        ctk.CTkOptionMenu(
            theme_outer,
            variable=self._theme_var,
            values=["night", "dark", "light"],
            dynamic_resizing=False,
            width=180,
        ).pack(anchor="w", pady=(6, 2))
        ctk.CTkLabel(
            theme_outer,
            text="night: pitch black  •  dark: grey dark  •  light: light mode",
            text_color="gray", font=ctk.CTkFont(size=11),
        ).pack(anchor="w")

        # ── Buttons ─────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=36, pady=(8, 16))

        ctk.CTkButton(
            btn_row, text="Cancel", command=self.destroy,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE")
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="Save", command=self._save,
            fg_color="#2ecc71", hover_color="#27ae60"
        ).pack(side="right")

    def _on_cores_change(self, value: float) -> None:
        self._cores_lbl.configure(text=str(int(value)))

    def _on_live_plot_toggle(self) -> None:
        app_config.save_config_key("live_plotting_enabled", bool(self._live_plot_var.get()))

    def _on_throttle_change_evt(self, _evt=None) -> None:
        try:
            ms = max(500, min(5000, int(self._throttle_var.get())))
        except (ValueError, TypeError):
            ms = 1500
        self._throttle_var.set(str(ms))
        app_config.save_config_key("live_plot_throttle_ms", ms)
        main = self._main_app
        for t in getattr(main, "_all_throttles", []) or []:
            try:
                t.update_interval(ms)
            except Exception:
                pass
        mp = getattr(main, "multiplot_window", None)
        if mp is not None and hasattr(mp, "_live_throttle"):
            try:
                mp._live_throttle.update_interval(ms)
            except Exception:
                pass

    def _on_engine_change(self, choice: str) -> None:
        self._sim_engine_hint.configure(text=self._ENGINE_HINTS.get(choice, ""))
        if choice == "vacask":
            self._vacask_frame.pack(fill="x", padx=16, pady=(8, 0),
                                    after=self._sim_outer)
        else:
            self._vacask_frame.pack_forget()

    def _save(self) -> None:
        self._config["num_cores"] = int(self._cores_var.get())
        self._config["simulator_engine"] = self._sim_engine_var.get()
        self._config["vacask_binary"] = self._vacask_binary_var.get().strip() or "vacask"
        self._config["vacask_netlist_source"] = self._vacask_src_var.get()
        self._config["process_start_method"] = self._proc_mode_var.get()
        self._config["chunk_size"] = self._chunk_var.get()
        self._config["live_plotting_enabled"] = bool(self._live_plot_var.get())
        try:
            self._config["live_plot_throttle_ms"] = max(
                500, min(5000, int(self._throttle_var.get()))
            )
        except (ValueError, TypeError):
            self._config["live_plot_throttle_ms"] = 1500
        new_theme = self._theme_var.get()
        self._config["theme"] = new_theme

        app_config.save_config(self._config)
        if hasattr(self._main_app, "change_theme"):
            self._main_app.change_theme(new_theme)
        self.destroy()
