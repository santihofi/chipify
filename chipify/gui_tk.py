import customtkinter as ctk
from tkinter import ttk, messagebox
import tkinter as tk
import os
import glob
import threading
import datetime
import logging
import time
import pandas as pd
import numpy as np
import yaml

from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from chipify import settings
from chipify import simulator
from chipify import util
from chipify import app_config

log = logging.getLogger("chipify.gui")

# --- NEUE MODULE IMPORTE ---
from chipify.plot_manager import PlotManager
from chipify import debug_export

# ==========================================
# --- YAML FORMATTING OVERRIDES ---
# ==========================================
def represent_list_inline(dumper, data):
    return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)

yaml.add_representer(list, represent_list_inline)
yaml.SafeDumper.add_representer(list, represent_list_inline)
yaml.Dumper.add_representer(list, represent_list_inline)

class QuotedString(str): pass

def represent_quoted_str(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style="'")

yaml.add_representer(QuotedString, represent_quoted_str)
yaml.SafeDumper.add_representer(QuotedString, represent_quoted_str)
yaml.Dumper.add_representer(QuotedString, represent_quoted_str)
# ==========================================

ctk.set_appearance_mode("dark")  
ctk.set_default_color_theme("blue")  

background_color = "#000000"
panel_color = "#1a1a1a"


# ==========================================
# GLOBAL SETTINGS MODAL
# ==========================================
class SettingsWindow(ctk.CTkToplevel):
    """Modal settings dialog for persistent user preferences."""

    def __init__(self, parent: ctk.CTk):
        super().__init__(parent)
        self.title("Global Settings")
        self.geometry("460x590")
        self.resizable(False, False)

        # grab_set needs a small delay so the window is fully mapped first
        self.after(50, self.grab_set)

        self._config = app_config.load_config()
        max_cores = os.cpu_count() or 1
        current_cores = int(self._config.get("num_cores") or util.get_num_cores())
        simulator_engine = self._config.get("simulator_engine", "ngspice")
        process_mode = self._config.get("process_start_method", "auto")
        chunk_size_mode = str(self._config.get("chunk_size", "auto"))
        if simulator_engine not in ["ngspice"]:
            simulator_engine = "ngspice"
        if process_mode not in ["auto", "forkserver", "spawn"]:
            process_mode = "auto"
        if chunk_size_mode not in ["auto", "1", "2", "4", "8", "16", "32"]:
            chunk_size_mode = "auto"

        # ── Header ──────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self, text="⚙️  Global Settings",
            font=ctk.CTkFont(size=17, weight="bold")
        ).pack(pady=(22, 18))

        # ── num_cores section ───────────────────────────────────────────────
        cores_outer = ctk.CTkFrame(self, fg_color="transparent")
        cores_outer.pack(fill="x", padx=36)

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
        sim_outer = ctk.CTkFrame(self, fg_color="transparent")
        sim_outer.pack(fill="x", padx=36, pady=(18, 0))
        ctk.CTkLabel(sim_outer, text="Simulation Engine:", anchor="w").pack(anchor="w")
        self._sim_engine_var = ctk.StringVar(value=simulator_engine)
        self._sim_engine_menu = ctk.CTkOptionMenu(
            sim_outer,
            variable=self._sim_engine_var,
            values=["ngspice"],
            dynamic_resizing=False,
            width=180,
        )
        self._sim_engine_menu.pack(anchor="w", pady=(6, 2))
        ctk.CTkLabel(
            sim_outer,
            text="Prepared for future engines (Xyce/Spectre)",
            text_color="gray", font=ctk.CTkFont(size=11)
        ).pack(anchor="w")

        # ── process start method section ────────────────────────────────────
        proc_outer = ctk.CTkFrame(self, fg_color="transparent")
        proc_outer.pack(fill="x", padx=36, pady=(18, 0))
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
        chunk_outer = ctk.CTkFrame(self, fg_color="transparent")
        chunk_outer.pack(fill="x", padx=36, pady=(18, 0))
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

        # ── Buttons ─────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=36, pady=(28, 0))

        ctk.CTkButton(
            btn_row, text="Cancel", command=self.destroy,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE")
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="💾  Save", command=self._save,
            fg_color="#2ecc71", hover_color="#27ae60"
        ).pack(side="right")

    def _on_cores_change(self, value: float) -> None:
        self._cores_lbl.configure(text=str(int(value)))

    def _save(self) -> None:
        self._config["num_cores"] = int(self._cores_var.get())
        self._config["simulator_engine"] = self._sim_engine_var.get()
        self._config["process_start_method"] = self._proc_mode_var.get()
        self._config["chunk_size"] = self._chunk_var.get()
        app_config.save_config(self._config)
        self.destroy()


class SimifyGUI(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=background_color)
        self.title("Chipify EDA Dashboard")
        self.geometry("1300x950")
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.current_df = None
        self.current_stim = None
        self.last_sim_duration_sec = None
        self.multiplot_window = None
        self.stop_event = threading.Event()
        
        self.all_plot_cols = []
        self.sweep_params = []
        
        # --- EDITOR STATE ---
        self.current_yaml_path = None
        self.current_yaml_data = {}
        self.raw_yaml_text = ""
        
        self.param_vars = [] 
        self.test_vars = []  
        self.param_key = 'params'
        self.test_key = 'tests'

        # --- EQUATIONS STATE ---
        # Each entry: {"name_var": StringVar, "expr_var": StringVar}
        self._eq_row_vars: list[dict] = []
        self._tran_eq_row_vars: list[dict] = []
        self._derived_cols: list[str] = []

        # --- TRANSIENT STATE ---
        self._tran_df = None                  # combined waveform DataFrame (lazily built)
        self._tran_line_orig: dict = {}       # {Line2D: (lw, alpha, zorder)} for hover restore
        self._tran_hover_line = None          # currently highlighted line

        self.setup_left_panel()
        self.setup_right_panel()
        self.apply_treeview_dark_style()
        
        self.after(200, self._startup_load)
        
    def _startup_load(self):
        self.refresh_yamls()
        self.refresh_history()
        self.tabs.set("Datasheet Editor")
        self.after(500, self.auto_load_latest_run)
        
    def setup_left_panel(self):
        self.left_frame = ctk.CTkFrame(self, width=260, corner_radius=0, fg_color=panel_color)
        self.left_frame.grid(row=0, column=0, sticky="nsew")
        self.left_frame.grid_rowconfigure(11, weight=1) 
        self.left_frame.grid_propagate(False)
        
        ctk.CTkLabel(self.left_frame, text="Configuration", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")
        ctk.CTkLabel(self.left_frame, text="Current Datasheet:").grid(row=1, column=0, padx=20, pady=(5, 0), sticky="w")
        self.yaml_dropdown = ctk.CTkOptionMenu(self.left_frame, dynamic_resizing=False, command=self.on_yaml_select)
        self.yaml_dropdown.grid(row=2, column=0, padx=20, pady=(5, 10), sticky="ew")
        
        self.btn_refresh = ctk.CTkButton(self.left_frame, text="Refresh Yamls", command=self.refresh_yamls, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"))
        self.btn_refresh.grid(row=3, column=0, padx=20, pady=(0, 15), sticky="ew")
        
        self.btn_start = ctk.CTkButton(self.left_frame, text="Start Simulation", command=self.start_simulation)
        self.btn_start.grid(row=4, column=0, padx=20, pady=(5, 5), sticky="ew")
        
        self.btn_stop = ctk.CTkButton(self.left_frame, text="Stop Simulation", command=self.stop_simulation, fg_color="#e74c3c", hover_color="#c0392b", state="disabled")
        self.btn_stop.grid(row=5, column=0, padx=20, pady=(0, 20), sticky="ew")
        
        ctk.CTkLabel(self.left_frame, text="History & Export", font=ctk.CTkFont(size=18, weight="bold")).grid(row=6, column=0, padx=20, pady=(10, 5), sticky="w")
        self.history_dropdown = ctk.CTkOptionMenu(self.left_frame, dynamic_resizing=False, command=self.on_history_select)
        self.history_dropdown.grid(row=7, column=0, padx=20, pady=(5, 10), sticky="ew")
        
        self.btn_pdf = ctk.CTkButton(self.left_frame, text="📄 Export PDF Report", command=self.export_pdf, fg_color="#8e44ad", hover_color="#9b59b6")
        self.btn_pdf.grid(row=8, column=0, padx=20, pady=(0, 4), sticky="ew")

        self.btn_open_folder = ctk.CTkButton(
            self.left_frame, text="📂  Open Output Folder",
            command=self.open_output_folder,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
        )
        self.btn_open_folder.grid(row=9, column=0, padx=20, pady=(0, 8), sticky="ew")

        self.btn_settings = ctk.CTkButton(
            self.left_frame, text="⚙️  Settings",
            command=self.open_settings,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE")
        )
        self.btn_settings.grid(row=10, column=0, padx=20, pady=(0, 8), sticky="ew")

        self.btn_multiplot = ctk.CTkButton(
            self.left_frame, text="🗖  Multi-Plot Dashboard",
            command=self.open_multiplot,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
        )
        self.btn_multiplot.grid(row=11, column=0, padx=20, pady=(0, 10), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self.left_frame)
        self.progress_bar.grid(row=12, column=0, padx=20, pady=(10, 0), sticky="ew")
        self.progress_bar.set(0)
        
        self.lbl_status = ctk.CTkLabel(self.left_frame, text="Status: Ready", text_color="gray")
        self.lbl_status.grid(row=13, column=0, padx=20, pady=(5, 20), sticky="w")
        
    def setup_right_panel(self):
        self.right_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.right_frame.grid_columnconfigure(0, weight=1)
        self.right_frame.grid_rowconfigure(2, weight=1) 
        
        header_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(header_frame, text="Dashboard", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, sticky="w")
        self.lbl_current_run = ctk.CTkLabel(header_frame, text="Viewing: [No Data]", text_color="gray", font=ctk.CTkFont(size=14))
        self.lbl_current_run.grid(row=0, column=1, sticky="e")
        
        self.metrics_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.metrics_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        
        self.lbl_total = ctk.CTkLabel(self.metrics_frame, text="Iterations: -", font=ctk.CTkFont(size=14))
        self.lbl_total.grid(row=0, column=0, padx=(0, 40))
        
        self.lbl_crashes = ctk.CTkLabel(self.metrics_frame, text="Crashes: -", font=ctk.CTkFont(size=14))
        self.lbl_crashes.grid(row=0, column=1, padx=(0, 40))
        
        self.lbl_yield = ctk.CTkLabel(self.metrics_frame, text="Global Yield: -", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_yield.grid(row=0, column=2)
        
        self.tabs = ctk.CTkTabview(self.right_frame, fg_color=panel_color,
                                    command=self._on_tab_change)
        self.tabs.grid(row=2, column=0, sticky="nsew")
        
        self.tab_editor = self.tabs.add("Datasheet Editor") 
        self.tab_table = self.tabs.add("Measurements")
        self.tab_worst = self.tabs.add("Worst-Case Analysis")
        self.tab_hist = self.tabs.add("Histograms")
        self.tab_adv = self.tabs.add("Advanced Analytics")
        self.tab_eq = self.tabs.add("Custom Equations")
        self.tab_tran = self.tabs.add("Transient")

        self.setup_editor_tab()
        self.setup_table_tab()
        self.setup_worst_case_tab()
        self.setup_histogram_tab()
        self.setup_adv_analytics_tab()
        self.setup_equations_tab()
        self.setup_transient_tab()

    # ==========================================
    # HISTORY & DATA LOADING
    # ==========================================
    def refresh_history(self):
        history_dir = os.path.join(settings.OUT_DIR, "history")
        runs = []
        if os.path.exists(os.path.join(settings.OUT_DIR, "simulation_results.csv")):
            runs.append("Latest (simulation_results)")
        if os.path.exists(history_dir):
            hist_files = glob.glob(os.path.join(history_dir, "run_*.csv"))
            hist_files.sort(reverse=True) 
            for f in hist_files:
                runs.append(os.path.basename(f))
                
        if not runs:
            self.history_dropdown.configure(values=["No runs found"])
            self.history_dropdown.set("No runs found")
            self.compare_dropdown.configure(values=["None"])
            self.compare_dropdown.set("None")
        else:
            self.history_dropdown.configure(values=runs)
            self.history_dropdown.set(runs[0])
            comp_runs = ["None"] + runs
            self.compare_dropdown.configure(values=comp_runs)
            self.compare_dropdown.set("None")

    def auto_load_latest_run(self):
        runs = self.history_dropdown.cget("values")
        if runs and runs[0] != "No runs found" and self.current_yaml_path:
            self.on_history_select(runs[0], switch_tab=False)
            self.lbl_status.configure(text="Status: Auto-loaded last run.", text_color="#3484F0")

    def on_history_select(self, selection, switch_tab=True):
        if not selection or selection == "No runs found" or not self.current_yaml_path: return
        if selection == "Latest (simulation_results)":
            csv_path = os.path.join(settings.OUT_DIR, "simulation_results.csv")
        else:
            csv_path = os.path.join(settings.OUT_DIR, "history", selection)
            
        if not os.path.exists(csv_path): return
        
        try:
            df = pd.read_csv(csv_path)
            stim = util.Stimuli(self.current_yaml_path)
            self.lbl_current_run.configure(text=f"Viewing: {selection}")
            self.update_ui_results(df, stim, switch_tab=switch_tab)
            self.lbl_status.configure(text=f"Status: Loaded {selection}", text_color="#2ecc71")
            # Transient tab refreshes via update_ui_results hook above;
            # signal list and plot update are called there automatically.
        except Exception as e:
            messagebox.showwarning("Load Error", f"Could not parse run data. Ensure the current Datasheet fits the old run.\n\n{e}")

    # ==========================================
    # PDF EXPORT
    # ==========================================
    def export_pdf(self):
        if self.current_df is None or self.current_stim is None:
            messagebox.showwarning("Export Error", "No simulation data available to export.")
            return

        report_dir = os.path.join(settings.OUT_DIR, "reports")
        self.lbl_status.configure(text="Status: Generating PDF Report...", text_color="yellow")
        self.update() 

        try:
            from chipify import pdf_export
            pdf_path = pdf_export.generate_pdf_report(
                self.current_df,
                self.current_stim,
                self.current_yaml_path,
                report_dir,
                sim_duration_sec=self.last_sim_duration_sec,
            )
            self.lbl_status.configure(text=f"Status: PDF saved to out/reports/", text_color="#2ecc71")
            messagebox.showinfo("Export Successful", f"Report saved as:\n{os.path.basename(pdf_path)}")
        except Exception as e:
            self.lbl_status.configure(text="Status: PDF Export Failed", text_color="red")
            messagebox.showerror("Export Error", f"Failed to generate PDF:\n{e}")

    # ==========================================
    # CUSTOM EQUATIONS TAB  (Epic 2)
    # ==========================================
    def setup_equations_tab(self):
        self.tab_eq.grid_columnconfigure(0, weight=1)
        self.tab_eq.grid_rowconfigure(1, weight=1)

        # ── Top bar with Scalar / Transient mode selector ─────────────────────
        top_bar = ctk.CTkFrame(self.tab_eq, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ctk.CTkLabel(
            top_bar, text="Custom Equations",
            font=ctk.CTkFont(size=16, weight="bold"), text_color="#3484F0"
        ).pack(side=tk.LEFT, padx=5)

        self._eq_mode_var = ctk.StringVar(value="Scalar")
        ctk.CTkSegmentedButton(
            top_bar, values=["Scalar", "Transient"],
            variable=self._eq_mode_var,
            command=self._on_eq_mode_change,
            width=180,
        ).pack(side=tk.LEFT, padx=(16, 0))

        self.btn_apply_eq = ctk.CTkButton(
            top_bar, text="▶  Apply to Data", width=150,
            command=self._action_apply_equations,
            fg_color="#3484F0", hover_color="#1a6fc4",
        )
        self.btn_apply_tran_eq = ctk.CTkButton(
            top_bar, text="▶  Apply to Waveforms", width=175,
            command=self._action_apply_tran_equations,
            fg_color="#2ecc71", hover_color="#27ae60",
        )
        self.btn_apply_eq.pack(side=tk.RIGHT, padx=5)
        # btn_apply_tran_eq is packed/forgotten by _on_eq_mode_change

        # ── Scalar card ───────────────────────────────────────────────────────
        self._scalar_eq_card = ctk.CTkFrame(self.tab_eq, fg_color=panel_color, corner_radius=8)
        self._scalar_eq_card.grid(row=1, column=0, sticky="nsew")
        self._scalar_eq_card.grid_columnconfigure(0, weight=1)
        self._scalar_eq_card.grid_rowconfigure(1, weight=1)

        shdr = ctk.CTkFrame(self._scalar_eq_card, fg_color="transparent")
        shdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        ctk.CTkLabel(shdr, text="Name", text_color="gray",
                     font=ctk.CTkFont(size=12), width=140, anchor="w").pack(side=tk.LEFT)
        ctk.CTkLabel(shdr,
                     text="Expression  (reference scalar column names, e.g.  p_out / p_in * 100)",
                     text_color="gray", font=ctk.CTkFont(size=12), anchor="w").pack(
            side=tk.LEFT, padx=(24, 0))

        self._eq_scroll = ctk.CTkScrollableFrame(self._scalar_eq_card, fg_color="transparent")
        self._eq_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self._eq_scroll.grid_columnconfigure(1, weight=1)

        self._eq_log = ctk.CTkTextbox(
            self._scalar_eq_card, height=80, state="disabled",
            font=ctk.CTkFont(family="Courier", size=12),
            fg_color="#0d0d0d", text_color="#b0b0b0",
        )
        self._eq_log.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 0))

        sadd = ctk.CTkFrame(self._scalar_eq_card, fg_color="transparent")
        sadd.grid(row=3, column=0, sticky="ew", padx=16, pady=(6, 12))
        ctk.CTkButton(
            sadd, text="+ Add Equation", width=140,
            command=self._action_add_equation,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
        ).pack(side=tk.LEFT)

        saved = app_config.load_config().get("custom_equations", [])
        for eq in saved:
            self._eq_row_vars.append({
                "name_var": ctk.StringVar(value=eq.get("name", "")),
                "expr_var": ctk.StringVar(value=eq.get("expr", "")),
            })
        self._build_equations_ui()

        # ── Transient card ────────────────────────────────────────────────────
        self._tran_eq_card = ctk.CTkFrame(self.tab_eq, fg_color=panel_color, corner_radius=8)
        self._tran_eq_card.grid(row=1, column=0, sticky="nsew")
        self._tran_eq_card.grid_columnconfigure(0, weight=1)
        self._tran_eq_card.grid_rowconfigure(1, weight=1)

        thdr = ctk.CTkFrame(self._tran_eq_card, fg_color="transparent")
        thdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        ctk.CTkLabel(thdr, text="Name", text_color="gray",
                     font=ctk.CTkFont(size=12), width=140, anchor="w").pack(side=tk.LEFT)
        ctk.CTkLabel(thdr,
                     text="Expression  (reference waveform column names, e.g.  v(outp) - v(outn))",
                     text_color="gray", font=ctk.CTkFont(size=12), anchor="w").pack(
            side=tk.LEFT, padx=(24, 0))

        self._tran_eq_scroll = ctk.CTkScrollableFrame(self._tran_eq_card, fg_color="transparent")
        self._tran_eq_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self._tran_eq_scroll.grid_columnconfigure(1, weight=1)

        self._tran_eq_log = ctk.CTkTextbox(
            self._tran_eq_card, height=80, state="disabled",
            font=ctk.CTkFont(family="Courier", size=12),
            fg_color="#0d0d0d", text_color="#b0b0b0",
        )
        self._tran_eq_log.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 0))

        tadd = ctk.CTkFrame(self._tran_eq_card, fg_color="transparent")
        tadd.grid(row=3, column=0, sticky="ew", padx=16, pady=(6, 12))
        ctk.CTkButton(
            tadd, text="+ Add Transient Equation", width=185,
            command=self._action_add_tran_equation,
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
        ).pack(side=tk.LEFT)

        saved_tran = app_config.load_config().get("transient_equations", [])
        for eq in saved_tran:
            self._tran_eq_row_vars.append({
                "name_var": ctk.StringVar(value=eq.get("name", "")),
                "expr_var": ctk.StringVar(value=eq.get("expr", "")),
            })
        self._build_tran_equations_ui()

        # Start in Scalar mode
        self._on_eq_mode_change("Scalar")

    def _build_equations_ui(self):
        for widget in self._eq_scroll.winfo_children():
            widget.destroy()

        for idx, row in enumerate(self._eq_row_vars):
            r = ctk.CTkFrame(self._eq_scroll, fg_color="transparent")
            r.pack(fill="x", pady=3)
            r.grid_columnconfigure(1, weight=1)

            ctk.CTkEntry(r, textvariable=row["name_var"], width=140,
                         placeholder_text="signal_name").pack(side=tk.LEFT, padx=(0, 6))
            ctk.CTkLabel(r, text="=", font=ctk.CTkFont(weight="bold"),
                         width=14).pack(side=tk.LEFT)
            ctk.CTkEntry(r, textvariable=row["expr_var"],
                         placeholder_text="e.g.  p_out / p_in * 100").pack(
                side=tk.LEFT, padx=(6, 8), fill="x", expand=True)
            ctk.CTkButton(
                r, text="🗑️", width=30,
                fg_color="#e74c3c", hover_color="#c0392b",
                command=lambda i=idx: self._action_del_equation(i)
            ).pack(side=tk.LEFT)

        if not self._eq_row_vars:
            ctk.CTkLabel(
                self._eq_scroll,
                text="No equations defined yet.  Click  '+ Add Equation'  to start.",
                text_color="gray"
            ).pack(pady=30)

    def _on_eq_mode_change(self, mode: str):
        """Show the active equation card and its Apply button."""
        if mode == "Scalar":
            self._tran_eq_card.grid_remove()
            self._scalar_eq_card.grid(row=1, column=0, sticky="nsew")
            self.btn_apply_tran_eq.pack_forget()
            self.btn_apply_eq.pack(side=tk.RIGHT, padx=5)
        else:
            self._scalar_eq_card.grid_remove()
            self._tran_eq_card.grid(row=1, column=0, sticky="nsew")
            self.btn_apply_eq.pack_forget()
            self.btn_apply_tran_eq.pack(side=tk.RIGHT, padx=5)

    def _build_tran_equations_ui(self):
        for widget in self._tran_eq_scroll.winfo_children():
            widget.destroy()

        for idx, row in enumerate(self._tran_eq_row_vars):
            r = ctk.CTkFrame(self._tran_eq_scroll, fg_color="transparent")
            r.pack(fill="x", pady=3)
            r.grid_columnconfigure(1, weight=1)

            ctk.CTkEntry(r, textvariable=row["name_var"], width=140,
                         placeholder_text="signal_name").pack(side=tk.LEFT, padx=(0, 6))
            ctk.CTkLabel(r, text="=", font=ctk.CTkFont(weight="bold"),
                         width=14).pack(side=tk.LEFT)
            ctk.CTkEntry(r, textvariable=row["expr_var"],
                         placeholder_text="e.g.  v(outp) - v(outn)").pack(
                side=tk.LEFT, padx=(6, 8), fill="x", expand=True)
            ctk.CTkButton(
                r, text="🗑️", width=30,
                fg_color="#e74c3c", hover_color="#c0392b",
                command=lambda i=idx: self._action_del_tran_equation(i)
            ).pack(side=tk.LEFT)

        if not self._tran_eq_row_vars:
            ctk.CTkLabel(
                self._tran_eq_scroll,
                text="No transient equations defined.  Click  '+ Add Transient Equation'  to start.",
                text_color="gray"
            ).pack(pady=30)

    def _action_add_tran_equation(self):
        self._tran_eq_row_vars.append({
            "name_var": ctk.StringVar(value=""),
            "expr_var": ctk.StringVar(value=""),
        })
        self._build_tran_equations_ui()

    def _action_del_tran_equation(self, idx: int):
        if idx < len(self._tran_eq_row_vars):
            self._tran_eq_row_vars.pop(idx)
        self._build_tran_equations_ui()

    def _collect_tran_equations(self) -> list[dict]:
        return [
            {"name": r["name_var"].get().strip(), "expr": r["expr_var"].get().strip()}
            for r in self._tran_eq_row_vars
            if r["name_var"].get().strip() and r["expr_var"].get().strip()
        ]

    def _action_apply_tran_equations(self):
        """Save transient equations and refresh the transient signal list."""
        equations = self._collect_tran_equations()
        cfg = app_config.load_config()
        cfg["transient_equations"] = equations
        app_config.save_config(cfg)
        self._tran_eq_log_write(
            f"Saved {len(equations)} transient equation(s).\n"
            "Click  '↺ Refresh'  in the Transient tab to apply to waveforms.\n"
        )
        self._refresh_transient_signal_list()

    def _tran_eq_log_write(self, text: str):
        try:
            self._tran_eq_log.configure(state="normal")
            self._tran_eq_log.delete("1.0", "end")
            self._tran_eq_log.insert("end", text)
            self._tran_eq_log.configure(state="disabled")
        except Exception:
            pass

    def _action_add_equation(self):
        self._eq_row_vars.append({
            "name_var": ctk.StringVar(value=""),
            "expr_var": ctk.StringVar(value=""),
        })
        self._build_equations_ui()

    def _action_del_equation(self, idx: int):
        if idx < len(self._eq_row_vars):
            self._eq_row_vars.pop(idx)
        self._build_equations_ui()

    def _collect_equations(self) -> list[dict]:
        return [
            {"name": r["name_var"].get().strip(), "expr": r["expr_var"].get().strip()}
            for r in self._eq_row_vars
            if r["name_var"].get().strip() and r["expr_var"].get().strip()
        ]

    def _action_apply_equations(self):
        """Save equations to settings.json then apply to current DataFrame."""
        equations = self._collect_equations()
        cfg = app_config.load_config()
        cfg["custom_equations"] = equations
        app_config.save_config(cfg)

        if self.current_df is None:
            self._eq_log_write("[!] No data loaded — equations saved but not applied yet.\n")
            return

        self._derived_cols = self._apply_custom_equations(equations)
        self._eq_log_write("Applied  {}/{} equations.  "
                           "Derived columns: {}\n".format(
                               len(self._derived_cols), len(equations),
                               ", ".join(self._derived_cols) or "—"))
        # Refresh dropdowns with new derived columns
        self._refresh_plot_dropdowns_with_derived()
        self._notify_multiplot()

    def _apply_custom_equations(self, equations: list[dict] | None = None) -> list[str]:
        """
        Evaluate each equation via DataFrame.eval(engine='python') and append
        the result as a new column to self.current_df.
        Returns the list of column names that were successfully computed.
        """
        if self.current_df is None:
            return []
        if equations is None:
            equations = app_config.load_config().get("custom_equations", [])

        derived = []
        log_lines = []
        import re
        valid_ident = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

        for eq in equations:
            name = eq.get("name", "").strip()
            expr = eq.get("expr", "").strip()
            if not name or not expr:
                continue
            if not valid_ident.match(name):
                log_lines.append(f"[✗] {name}  →  Name must be a valid Python identifier")
                log.warning("Equation '%s' skipped: invalid name.", name)
                continue
            try:
                self.current_df = self.current_df.eval(
                    f"{name} = {expr}", engine='python'
                )
                n_valid = int((self.current_df['sim_error'] == 'None').sum())
                log_lines.append(f"[✓] {name} = {expr}  →  ok  ({n_valid} rows)")
                log.debug("Applied equation: %s = %s", name, expr)
                derived.append(name)
            except Exception as exc:
                log_lines.append(f"[✗] {name} = {expr}  →  {exc}")
                log.warning("Equation '%s' failed: %s", name, exc)

        if log_lines:
            self._eq_log_write("\n".join(log_lines) + "\n")
        return derived

    def _eq_log_write(self, text: str):
        try:
            self._eq_log.configure(state="normal")
            self._eq_log.delete("1.0", "end")
            self._eq_log.insert("end", text)
            self._eq_log.configure(state="disabled")
        except Exception:
            pass

    def _refresh_plot_dropdowns_with_derived(self):
        """Add derived columns to histogram and scatter dropdowns."""
        if not self._derived_cols or self.current_df is None:
            return
        valid_derived = [
            c for c in self._derived_cols
            if c in self.current_df.columns
        ]
        if not valid_derived:
            return

        # Histogram meas dropdown
        current_hist_vals = list(self.plot_param_dropdown.cget("values") or [])
        new_hist_vals = current_hist_vals + [c for c in valid_derived if c not in current_hist_vals]
        if new_hist_vals != current_hist_vals:
            self.plot_param_dropdown.configure(values=new_hist_vals)

        # all_plot_cols (used by scatter / corner matrix)
        for c in valid_derived:
            if c not in self.all_plot_cols:
                self.all_plot_cols.append(c)

        # Tornado target dropdown
        current_tornado = list(self.tornado_target_dropdown.cget("values") or [])
        new_tornado = current_tornado + [c for c in valid_derived if c not in current_tornado]
        if new_tornado != current_tornado:
            self.tornado_target_dropdown.configure(values=new_tornado)

    def _on_tab_change(self, *_args):
        """Auto-refresh the Transient tab whenever it becomes active."""
        try:
            if self.tabs.get() == "Transient":
                self.update_transient_plot()
        except Exception:
            pass

    def _load_tran_df(self, tran_dir: str, run_ids: list,
                      equations: list | None = None) -> "pd.DataFrame":
        """Load selected waveform CSVs into a combined (run_id, time, …) DataFrame."""
        if not tran_dir or not run_ids:
            return pd.DataFrame()
        run_id_set = set(run_ids)
        chunks = []
        for fname in glob.glob(os.path.join(tran_dir, "run_*.csv")):
            rid = os.path.basename(fname)[4:].split("__", 1)[0]
            if rid not in run_id_set:
                continue
            try:
                df_chunk = pd.read_csv(fname)
                if equations:
                    for eq in equations:
                        eq_n = eq.get("name", "").strip()
                        eq_e = eq.get("expr", "").strip()
                        if eq_n and eq_e:
                            try:
                                df_chunk = df_chunk.eval(f"{eq_n} = {eq_e}", engine="python")
                            except Exception:
                                pass
                df_chunk.insert(0, "run_id", rid)
                chunks.append(df_chunk)
            except Exception:
                pass
        return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()

    def open_multiplot(self):
        from chipify.multiplot_window import MultiPlotWindow
        from chipify import app_config
        if self.multiplot_window is not None:
            try:
                self.multiplot_window.deiconify()
                self.multiplot_window.lift()
                self.multiplot_window.focus_force()
                return
            except Exception:
                self.multiplot_window = None

        self.multiplot_window = MultiPlotWindow(parent=self)

        # Restore persisted cell layout
        try:
            cfg = app_config.load_config()
            saved = cfg.get("multiplot_config", [])
            if saved:
                self.multiplot_window.restore_from_config(saved)
        except Exception:
            pass

    def open_output_folder(self):
        """Open the simulation output directory in the OS file manager."""
        import subprocess, sys as _sys
        path = settings.OUT_DIR
        os.makedirs(path, exist_ok=True)
        try:
            if _sys.platform.startswith("win"):
                os.startfile(path)
            elif _sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Open Folder", f"Could not open folder:\n{exc}")

    def open_settings(self):
        win = SettingsWindow(self)
        self.wait_window(win)

    # ==========================================
    # DATASHEET EDITOR
    # ==========================================
    def setup_editor_tab(self):
        self.tab_editor.grid_columnconfigure(0, weight=1)
        self.tab_editor.grid_rowconfigure(1, weight=1)
        top_bar = ctk.CTkFrame(self.tab_editor, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.lbl_editor_title = ctk.CTkLabel(top_bar, text="Loading...", font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_editor_title.pack(side="left", padx=5)
        self.editor_mode = ctk.StringVar(value="Form View")
        self.mode_selector = ctk.CTkSegmentedButton(top_bar, values=["Form View", "Raw YAML"], variable=self.editor_mode, command=self.switch_editor_mode)
        self.mode_selector.pack(side="left", padx=30)
        btn_save = ctk.CTkButton(top_bar, text="💾 Save Datasheet", command=self.save_yaml, fg_color="#2ecc71", hover_color="#27ae60")
        btn_save.pack(side="right", padx=5)
        self.editor_scroll = ctk.CTkScrollableFrame(self.tab_editor, fg_color="transparent")
        self.editor_scroll.grid(row=1, column=0, sticky="nsew")
        self.editor_scroll.grid_columnconfigure(0, weight=1)
        self.raw_editor = ctk.CTkTextbox(self.tab_editor, font=ctk.CTkFont(family="Courier", size=14))

    def switch_editor_mode(self, mode):
        if mode == "Form View":
            self.raw_editor.grid_remove()
            self.editor_scroll.grid(row=1, column=0, sticky="nsew")
            try:
                raw_text = self.raw_editor.get("1.0", "end-1c")
                self.current_yaml_data = yaml.safe_load(raw_text) or {}
                self.get_params_dict()
                self.get_tests_dict()
                self.build_editor_ui()
            except Exception as e:
                messagebox.showerror("YAML Error", f"Syntax error in Raw Editor:\n{e}")
                self.editor_mode.set("Raw YAML")
                self.switch_editor_mode("Raw YAML")
        else:
            self.editor_scroll.grid_remove()
            self.raw_editor.grid(row=1, column=0, sticky="nsew")
            self.sync_ui_to_state()
            raw_text = yaml.dump(self.current_yaml_data, default_flow_style=False, sort_keys=False)
            self.raw_editor.delete("1.0", "end")
            self.raw_editor.insert("1.0", raw_text)

    def get_params_dict(self):
        if not isinstance(self.current_yaml_data, dict): return 'params', {}
        for key in ['params', 'parameters', 'sweep']:
            if key in self.current_yaml_data:
                val = self.current_yaml_data[key]
                if isinstance(val, dict): return key, val
        return 'params', {}

    def get_tests_dict(self):
        if not isinstance(self.current_yaml_data, dict): return 'tests', {}
        for key in ['tests', 'testbenches', 'measurements']:
            if key in self.current_yaml_data:
                val = self.current_yaml_data[key]
                if isinstance(val, dict):
                    for tb_name, tb_data in val.items():
                        if isinstance(tb_data, dict) and 'values' in tb_data:
                            v = tb_data.pop('values')
                            if isinstance(v, dict): tb_data.update(v)
                    return key, val
        return 'tests', {}

    def on_yaml_select(self, selected_yaml):
        if not selected_yaml or selected_yaml == "No files found": return
        self.current_yaml_path = os.path.join(settings.IN_DIR, selected_yaml)
        try:
            with open(self.current_yaml_path, 'r') as f:
                raw_text = f.read()
            self.current_yaml_data = yaml.safe_load(raw_text) or {}
            self.param_key, _ = self.get_params_dict()
            self.test_key, _ = self.get_tests_dict()
            self.raw_yaml_text = yaml.dump(self.current_yaml_data, default_flow_style=False, sort_keys=False)
        except Exception as e:
            messagebox.showerror("Load Error", f"Error loading {selected_yaml}:\n{e}")
            return
        self.lbl_editor_title.configure(text=f"Editing: {selected_yaml}")
        self.raw_editor.delete("1.0", "end")
        self.raw_editor.insert("1.0", self.raw_yaml_text)
        self.build_editor_ui()
        if self.editor_mode.get() == "Form View":
            self.raw_editor.grid_remove()
            self.editor_scroll.grid(row=1, column=0, sticky="nsew")
        else:
            self.editor_scroll.grid_remove()
            self.raw_editor.grid(row=1, column=0, sticky="nsew")

    def gui_repr_param(self, x):
        if isinstance(x, str):
            if x.startswith("range(") or x.startswith("np.") or x.replace('.', '', 1).isdigit():
                return x
            return f"'{x}'"
        return str(x)
        
    def build_editor_ui(self):
        for widget in self.editor_scroll.winfo_children(): widget.destroy()
        self.param_vars = []
        self.test_vars = []
        self.param_key, params_dict = self.get_params_dict()
        self.test_key, tests_dict = self.get_tests_dict()
        
        param_header = ctk.CTkFrame(self.editor_scroll, fg_color="transparent")
        param_header.pack(fill="x", pady=(10, 5))
        ctk.CTkLabel(param_header, text="Sweep Parameters", font=ctk.CTkFont(size=16, weight="bold"), text_color="#3484F0").pack(side="left", padx=5)
        ctk.CTkButton(param_header, text="+ Add Parameter", width=120, height=24, command=self.action_add_param, border_width=1).pack(side="right", padx=5)
        
        params_frame = ctk.CTkFrame(self.editor_scroll, fg_color=panel_color)
        params_frame.pack(fill="x", padx=5, pady=5)
        params_frame.grid_columnconfigure(1, weight=1)
        
        r = 0
        for p_name, p_val in params_dict.items():
            key_var = ctk.StringVar(value=str(p_name))
            if not isinstance(p_val, list): val_str = self.gui_repr_param(p_val)
            else: val_str = ", ".join(self.gui_repr_param(x) for x in p_val)
            val_var = ctk.StringVar(value=val_str)
            
            ctk.CTkEntry(params_frame, textvariable=key_var, width=150).grid(row=r, column=0, padx=10, pady=5, sticky="w")
            ctk.CTkEntry(params_frame, textvariable=val_var).grid(row=r, column=1, padx=10, pady=5, sticky="ew")
            ctk.CTkButton(params_frame, text="🗑️", width=30, fg_color="#e74c3c", hover_color="#c0392b", command=lambda idx=r: self.action_del_param(idx)).grid(row=r, column=2, padx=10, pady=5)
            self.param_vars.append({'key': key_var, 'val': val_var})
            r += 1
            
        if r == 0:
            ctk.CTkLabel(params_frame, text="No parameters defined.", text_color="gray").grid(row=0, column=0, padx=10, pady=10)

        test_header = ctk.CTkFrame(self.editor_scroll, fg_color="transparent")
        test_header.pack(fill="x", pady=(20, 5))
        ctk.CTkLabel(test_header, text="Specifications (Boundaries)", font=ctk.CTkFont(size=16, weight="bold"), text_color="#3484F0").pack(side="left", padx=5)
        ctk.CTkButton(test_header, text="+ Add Testbench", width=140, height=24, command=self.action_add_test).pack(side="right", padx=5)

        for t_idx, (tb_name, tb_data) in enumerate(tests_dict.items()):
            if not isinstance(tb_data, dict): tb_data = {}
            frame = ctk.CTkFrame(self.editor_scroll, border_width=1, border_color="#565b5e")
            frame.pack(fill="x", pady=10, padx=5)
            frame.grid_columnconfigure(1, weight=1)
            
            tb_name_var = ctk.StringVar(value=str(tb_name))
            row_header = ctk.CTkFrame(frame, fg_color="transparent")
            row_header.pack(fill="x", padx=10, pady=(10, 5))
            ctk.CTkLabel(row_header, text="Testbench Name:", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 10))
            ctk.CTkEntry(row_header, textvariable=tb_name_var, width=200).pack(side="left")
            ctk.CTkButton(row_header, text="🗑️ Delete Testbench", width=140, height=24, fg_color="#e74c3c", hover_color="#c0392b", command=lambda idx=t_idx: self.action_del_test(idx)).pack(side="right")
            
            val_frame = ctk.CTkFrame(frame, fg_color="transparent")
            val_frame.pack(fill="x", padx=10, pady=5)
            ctk.CTkLabel(val_frame, text="Measurement", text_color="gray").grid(row=0, column=0, padx=5, pady=2, sticky="w")
            ctk.CTkLabel(val_frame, text="Min Spec", text_color="gray").grid(row=0, column=1, padx=5, pady=2, sticky="w")
            ctk.CTkLabel(val_frame, text="Max Spec", text_color="gray").grid(row=0, column=2, padx=5, pady=2, sticky="w")
            
            test_val_vars = []
            for v_idx, (v_name, v_data) in enumerate(tb_data.items()):
                if v_name in ('values', 'transient_signals'): continue
                if not isinstance(v_data, dict): v_data = {}
                v_name_var = ctk.StringVar(value=str(v_name))
                
                min_val = v_data.get('vmin', v_data.get('min', ''))
                max_val = v_data.get('vmax', v_data.get('max', ''))
                
                v_min = ctk.StringVar(value=str(min_val) if min_val is not None else '')
                v_max = ctk.StringVar(value=str(max_val) if max_val is not None else '')
                
                ctk.CTkEntry(val_frame, textvariable=v_name_var, width=150).grid(row=1+v_idx, column=0, padx=5, pady=2)
                ctk.CTkEntry(val_frame, textvariable=v_min, width=80).grid(row=1+v_idx, column=1, padx=5, pady=2)
                ctk.CTkEntry(val_frame, textvariable=v_max, width=80).grid(row=1+v_idx, column=2, padx=5, pady=2)
                ctk.CTkButton(val_frame, text="X", width=24, height=24, fg_color="transparent", border_width=1, command=lambda t=t_idx, v=v_name: self.action_del_value(t, v)).grid(row=1+v_idx, column=3, padx=5, pady=2)
                
                test_val_vars.append({'name': v_name_var, 'vmin': v_min, 'vmax': v_max})

            # Transient signals row
            existing_tran = tb_data.get('transient_signals', [])
            tran_str = ", ".join(str(s) for s in existing_tran) if isinstance(existing_tran, list) else str(existing_tran)
            tran_var = ctk.StringVar(value=tran_str)
            tran_row = ctk.CTkFrame(frame, fg_color="transparent")
            tran_row.pack(fill="x", padx=10, pady=(4, 0))
            ctk.CTkLabel(tran_row, text="Transient Signals:", text_color="#3484F0",
                         font=ctk.CTkFont(size=12)).pack(side=tk.LEFT, padx=(0, 8))
            ctk.CTkEntry(tran_row, textvariable=tran_var,
                         placeholder_text="e.g.  v(out), v(in), i(vdd)").pack(side=tk.LEFT, fill="x", expand=True)
                
            self.test_vars.append({'tb_name': tb_name_var, 'values': test_val_vars, 'tran_signals': tran_var})
            ctk.CTkButton(frame, text="+ Add Measurement", width=140, height=24, fg_color="transparent", border_width=1, command=lambda idx=t_idx: self.action_add_value(idx)).pack(anchor="w", padx=10, pady=(5, 10))

    def sync_ui_to_state(self):
        if not isinstance(self.current_yaml_data, dict): self.current_yaml_data = {}
        self.current_yaml_data[self.param_key] = {}
        for p_dict in self.param_vars:
            k = p_dict['key'].get().strip()
            v_str = p_dict['val'].get().strip()
            if not k: continue 
            
            if v_str.startswith("range(") or v_str.startswith("np."):
                self.current_yaml_data[self.param_key][k] = v_str
                continue
                
            parsed_list = []
            for x in v_str.split(','):
                x = x.strip()
                if not x: continue
                if (x.startswith("'") and x.endswith("'")) or (x.startswith('"') and x.endswith('"')):
                    parsed_list.append(QuotedString(x[1:-1]))
                else:
                    try: parsed_list.append(float(x) if '.' in x else int(x))
                    except ValueError: parsed_list.append(x)
            self.current_yaml_data[self.param_key][k] = parsed_list
            
        self.current_yaml_data[self.test_key] = {}
        for t_dict in self.test_vars:
            tb_name = t_dict['tb_name'].get().strip()
            if not tb_name: continue
            
            tb_content = {}

            # Persist transient_signals before scalar measurements so it appears first.
            tran_raw = t_dict.get('tran_signals')
            if tran_raw is not None:
                tran_str = tran_raw.get().strip()
                if tran_str:
                    tran_list = [s.strip() for s in tran_str.replace(",", " ").split() if s.strip()]
                    if tran_list:
                        tb_content['transient_signals'] = tran_list

            for v_dict in t_dict['values']:
                name = v_dict['name'].get().strip()
                if not name: continue
                v_data = {}
                vmin_str = v_dict['vmin'].get().strip()
                vmax_str = v_dict['vmax'].get().strip()
                
                if vmin_str and vmin_str.lower() != 'none': 
                    try: v_data['min'] = float(vmin_str)
                    except ValueError: v_data['min'] = vmin_str
                if vmax_str and vmax_str.lower() != 'none': 
                    try: v_data['max'] = float(vmax_str)
                    except ValueError: v_data['max'] = vmax_str
                tb_content[name] = v_data
            self.current_yaml_data[self.test_key][tb_name] = tb_content

    def action_add_param(self):
        self.sync_ui_to_state()
        self.current_yaml_data[self.param_key]['new_param'] = [1, 2]
        self.build_editor_ui()

    def action_del_param(self, idx):
        self.sync_ui_to_state()
        keys = list(self.current_yaml_data[self.param_key].keys())
        if idx < len(keys): del self.current_yaml_data[self.param_key][keys[idx]]
        self.build_editor_ui()

    def action_add_test(self):
        self.sync_ui_to_state()
        self.current_yaml_data[self.test_key]['new_testbench'] = {}
        self.build_editor_ui()

    def action_del_test(self, idx):
        self.sync_ui_to_state()
        keys = list(self.current_yaml_data[self.test_key].keys())
        if idx < len(keys): del self.current_yaml_data[self.test_key][keys[idx]]
        self.build_editor_ui()

    def action_add_value(self, test_idx):
        self.sync_ui_to_state()
        keys = list(self.current_yaml_data[self.test_key].keys())
        if test_idx < len(keys):
            tb_key = keys[test_idx]
            base_name = 'new_measurement'
            name = base_name
            count = 1
            while name in self.current_yaml_data[self.test_key][tb_key]:
                name = f"{base_name}_{count}"
                count += 1
            self.current_yaml_data[self.test_key][tb_key][name] = {}
        self.build_editor_ui()

    def action_del_value(self, test_idx, val_name):
        self.sync_ui_to_state()
        keys = list(self.current_yaml_data[self.test_key].keys())
        if test_idx < len(keys):
            tb_key = keys[test_idx]
            if val_name in self.current_yaml_data[self.test_key][tb_key]:
                del self.current_yaml_data[self.test_key][tb_key][val_name]
        self.build_editor_ui()

    def save_yaml(self):
        if not self.current_yaml_path: return
        try:
            if self.editor_mode.get() == "Form View":
                self.sync_ui_to_state()
                text_to_save = yaml.dump(self.current_yaml_data, default_flow_style=False, sort_keys=False)
                self.raw_editor.delete("1.0", "end")
                self.raw_editor.insert("1.0", text_to_save)
            else:
                text_to_save = self.raw_editor.get("1.0", "end-1c")
                yaml.safe_load(text_to_save) 
            with open(self.current_yaml_path, 'w') as f:
                f.write(text_to_save)
            self.lbl_status.configure(text=f"Status: Datasheet saved successfully!", text_color="#2ecc71")
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save datasheet:\n{str(e)}")

    # ==========================================
    # MEASUREMENTS & WORST CASE TAB
    # ==========================================
    def refresh_yamls(self):
        yaml_files = glob.glob(os.path.join(settings.IN_DIR, "*.yaml"))
        yaml_names = [os.path.basename(f) for f in yaml_files]
        if yaml_names:
            self.yaml_dropdown.configure(values=yaml_names)
            curr = self.yaml_dropdown.get()
            if not curr or curr not in yaml_names:
                self.yaml_dropdown.set(yaml_names[0])
                curr = yaml_names[0]
            self.on_yaml_select(curr)
        else:
            self.yaml_dropdown.configure(values=["No files found"])
            self.yaml_dropdown.set("No files found")
            self.current_yaml_path = None
            self.current_yaml_data = {}
            self.raw_editor.delete("1.0", "end")
            self.build_editor_ui()
            
    def setup_table_tab(self):
        self.tab_table.grid_columnconfigure(0, weight=1)
        self.tab_table.grid_rowconfigure(0, weight=1)
        
        self.tree_frame = ctk.CTkFrame(self.tab_table, fg_color="transparent")
        self.tree_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        self.tree_frame.grid_columnconfigure(0, weight=1)
        self.tree_frame.grid_rowconfigure(0, weight=1)
        
        columns = ("param", "sim_min", "sim_typ", "sim_max", "spec_min", "spec_max", "cpk", "sigma", "status")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings")
        
        self.tree.heading("param", text="Parameter")
        self.tree.heading("sim_min", text="Sim Min")
        self.tree.heading("sim_typ", text="Sim Typ")
        self.tree.heading("sim_max", text="Sim Max")
        self.tree.heading("spec_min", text="Spec Min")
        self.tree.heading("spec_max", text="Spec Max")
        self.tree.heading("cpk", text="Cpk")
        self.tree.heading("sigma", text="Sigma")
        self.tree.heading("status", text="Status")
        
        for col in columns: self.tree.column(col, width=70, anchor=tk.CENTER)
        self.tree.column("param", width=120, anchor=tk.W)
        self.tree.column("status", width=60, anchor=tk.CENTER)
        
        scrollbar = ttk.Scrollbar(self.tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        
        self.tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Right-click context menu for tree rows
        self._tree_menu = tk.Menu(self.tree_frame, tearoff=0, bg="#1a1a1a",
                                  fg="white", activebackground="#3484F0",
                                  activeforeground="white", relief="flat")
        self._tree_menu.add_command(label="Plot Histogram", command=self._ctx_plot_histogram)
        self._tree_menu.add_command(label="Copy Value (Typ)", command=self._ctx_copy_value)
        self._tree_menu.add_separator()
        self._tree_menu.add_command(label="Add to Equations", command=self._ctx_add_to_equations)
        self.tree.bind("<Button-3>", self._on_tree_right_click)  # Windows/Linux
        self.tree.bind("<Button-2>", self._on_tree_right_click)  # macOS

    def setup_worst_case_tab(self):
        self.tab_worst.grid_columnconfigure(0, weight=1)
        self.tab_worst.grid_rowconfigure(1, weight=1)
        
        top_bar = ctk.CTkFrame(self.tab_worst, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        lbl = ctk.CTkLabel(top_bar, text="Outliers & Fails", font=ctk.CTkFont(size=16, weight="bold"))
        lbl.pack(side=tk.LEFT, padx=10)
        
        self.btn_export_debug = ctk.CTkButton(top_bar, text="🪲 Export Fails for Debugging", command=self.action_export_debug, fg_color="#e67e22", hover_color="#d35400")
        self.btn_export_debug.pack(side=tk.RIGHT, padx=10)
        
        self.wc_scroll = ctk.CTkScrollableFrame(self.tab_worst, fg_color="transparent")
        self.wc_scroll.grid(row=1, column=0, sticky="nsew")
        self.lbl_wc_empty = ctk.CTkLabel(self.wc_scroll, text="Start a simulation to see outliers...", text_color="gray")
        self.lbl_wc_empty.pack(pady=50)

    def action_export_debug(self):
        if self.current_df is None: return
        out_dir = os.path.join(settings.OUT_DIR, "debug")
        count = debug_export.export_fails(self.current_df, self.current_stim, out_dir)
        if count > 0:
            messagebox.showinfo("Export Debug", f"Erfolgreich {count} fehlgeschlagene Runs exportiert nach:\n{out_dir}")
        else:
            messagebox.showinfo("Export Debug", "Keine fehlgeschlagenen Runs zum Exportieren vorhanden (100% Yield!).")

    # ── Tree context menu ────────────────────────────────────────────────────

    def _on_tree_right_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        self.tree.selection_set(row_id)
        try:
            self._tree_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._tree_menu.grab_release()

    def _selected_tree_param(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.item(sel[0], "values")[0]  # first column = param name

    def _ctx_plot_histogram(self):
        param = self._selected_tree_param()
        if not param or self.current_df is None:
            return
        opts = list(self.plot_param_dropdown.cget("values") or [])
        if param in opts:
            self.plot_param_var.set(param)
            self.update_plot()
            self.tabs.set("Histograms")

    def _ctx_copy_value(self):
        param = self._selected_tree_param()
        if not param:
            return
        sel = self.tree.selection()
        if sel:
            typ_val = self.tree.item(sel[0], "values")[2]  # sim_typ column
            self.clipboard_clear()
            self.clipboard_append(str(typ_val))

    def _ctx_add_to_equations(self):
        param = self._selected_tree_param()
        if not param:
            return
        self._eq_row_vars.append({
            "name_var": ctk.StringVar(value=f"new_{param}"),
            "expr_var": ctk.StringVar(value=param),
        })
        self._build_equations_ui()
        self.tabs.set("Custom Equations")

    # ==========================================
    # HISTOGRAM & ADVANCED PLOTS TAB
    # ==========================================
    def setup_histogram_tab(self):
        self.tab_hist.grid_columnconfigure(0, weight=1)
        self.tab_hist.grid_rowconfigure(1, weight=1)
        
        control_frame = ctk.CTkFrame(self.tab_hist, fg_color="transparent")
        control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        row1 = ctk.CTkFrame(control_frame, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        row2 = ctk.CTkFrame(control_frame, fg_color="transparent")
        row2.pack(fill="x", pady=2)
        
        ctk.CTkLabel(row1, text="Meas:").pack(side=tk.LEFT, padx=(0, 5))
        self.plot_param_var = ctk.StringVar(value="-")
        self.plot_param_dropdown = ctk.CTkOptionMenu(row1, variable=self.plot_param_var, command=self.update_plot, dynamic_resizing=False, width=130)
        self.plot_param_dropdown.pack(side=tk.LEFT, padx=(0, 15))
        
        ctk.CTkLabel(row1, text="Group by:").pack(side=tk.LEFT, padx=(5, 5))
        self.group_by_var = ctk.StringVar(value="None")
        self.group_by_dropdown = ctk.CTkOptionMenu(row1, variable=self.group_by_var, command=self.on_group_by_change, dynamic_resizing=False, width=130)
        self.group_by_dropdown.pack(side=tk.LEFT, padx=(0, 15))
        
        ctk.CTkLabel(row1, text="Fit Curve:").pack(side=tk.LEFT, padx=(5, 5))
        self.plot_dist_var = ctk.StringVar(value="Gauss (Normal)")
        self.plot_dist_dropdown = ctk.CTkOptionMenu(
            row1, variable=self.plot_dist_var, 
            values=["Gauss (Normal)", "KDE (Smoothed)", "Uniform", "Log-Normal", "Exponential", "Chi-Squared", "None"],
            command=self.update_plot, dynamic_resizing=False, width=140
        )
        self.plot_dist_dropdown.pack(side=tk.LEFT)

        self.kpi_frame = ctk.CTkFrame(row1, fg_color="#1e2d3d", corner_radius=5)
        self.kpi_frame.pack(side=tk.RIGHT, padx=(20, 0))
        # Individual KPI labels — updated together in update_plot()
        self.lbl_kpi_cpk   = ctk.CTkLabel(self.kpi_frame, text="Cpk: —", text_color="white",  font=ctk.CTkFont(size=11, weight="bold"), width=70)
        self.lbl_kpi_sigma = ctk.CTkLabel(self.kpi_frame, text="σ: —",   text_color="white",  font=ctk.CTkFont(size=11))
        self.lbl_kpi_mean  = ctk.CTkLabel(self.kpi_frame, text="μ: —",   text_color="#aaaaaa", font=ctk.CTkFont(size=11))
        self.lbl_kpi_std   = ctk.CTkLabel(self.kpi_frame, text="std: —", text_color="#aaaaaa", font=ctk.CTkFont(size=11))
        self.lbl_kpi_fail  = ctk.CTkLabel(self.kpi_frame, text="Fail: —",text_color="#e74c3c", font=ctk.CTkFont(size=11))
        for lbl in (self.lbl_kpi_cpk, self.lbl_kpi_sigma,
                    self.lbl_kpi_mean, self.lbl_kpi_std, self.lbl_kpi_fail):
            lbl.pack(side=tk.LEFT, padx=(8, 0), pady=2)
        ctk.CTkLabel(self.kpi_frame, text="", width=6).pack(side=tk.LEFT)  # right margin

        # keep legacy alias so existing call sites that still use lbl_hist_metrics don't break
        self.lbl_hist_metrics = self.lbl_kpi_cpk

        ctk.CTkLabel(row2, text="Compare (Ref):", text_color="#f1c40f").pack(side=tk.LEFT, padx=(0, 5))
        self.compare_var = ctk.StringVar(value="None")
        self.compare_dropdown = ctk.CTkOptionMenu(row2, variable=self.compare_var, command=self.update_plot, dynamic_resizing=False, fg_color="#d35400", button_color="#8e44ad", button_hover_color="#9b59b6", width=140)
        self.compare_dropdown.pack(side=tk.LEFT, padx=(0, 20))
        
        ctk.CTkLabel(row2, text="Bins:").pack(side=tk.LEFT, padx=(5, 5))
        self.bins_var = ctk.StringVar(value="Auto")
        self.bins_dropdown = ctk.CTkOptionMenu(row2, variable=self.bins_var, values=["Auto", "10", "20", "50", "100", "200"], command=self.update_plot, dynamic_resizing=False, width=80)
        self.bins_dropdown.pack(side=tk.LEFT, padx=(0, 20))
        
        self.zoom_var = ctk.BooleanVar(value=False)
        self.zoom_checkbox = ctk.CTkCheckBox(row2, text="Zoom to Fit Data", variable=self.zoom_var, command=self.update_plot)
        self.zoom_checkbox.pack(side=tk.LEFT, padx=(0, 20))

        self.btn_latex = ctk.CTkButton(row2, text="TeX Export", command=self.action_export_latex, fg_color="#27ae60", hover_color="#2ecc71", width=90)
        self.btn_latex.pack(side=tk.LEFT)

        plt.style.use('dark_background')
        self.fig, self.ax = plt.subplots(figsize=(6, 4))
        self.fig.patch.set_facecolor(panel_color) 
        self.ax.set_facecolor(panel_color)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.tab_hist)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

    def action_export_latex(self):
        if self.current_df is None or self.plot_param_var.get() == "-": return
        param = self.plot_param_var.get()
        dist_type = self.plot_dist_var.get()
        bins_val = self.bins_var.get()
        b = 'auto' if bins_val == "Auto" else int(bins_val)
        
        valid_df = self.current_df[self.current_df['sim_error'] == 'None']
        if param not in valid_df.columns: return
        data = valid_df[param].dropna()
        if len(data) == 0: return

        from simify import export_latex
        out_dir = os.path.join(settings.OUT_DIR, "latex")
        
        try:
            export_latex.generate_latex_export(param, data, dist_type, b, out_dir)
            messagebox.showinfo("LaTeX Export", f"Erfolgreich exportiert nach:\n{out_dir}")
        except Exception as e:
            messagebox.showerror("Export Error", f"LaTeX Export fehlgeschlagen:\n{e}")

    def on_group_by_change(self, choice):
        if choice != "None": self.compare_dropdown.configure(state="disabled")
        else: self.compare_dropdown.configure(state="normal")
        self.update_plot()

    def update_plot(self, *args):
        if self.current_df is None or self.plot_param_var.get() == "-": return
        param = self.plot_param_var.get()
        dist_type = self.plot_dist_var.get()
        group_col = self.group_by_var.get()
        bins_val = self.bins_var.get()
        do_zoom = self.zoom_var.get()
        comp_run = self.compare_var.get()
        
        valid_df = self.current_df[self.current_df['sim_error'] == 'None']
        if param not in valid_df.columns: return
        
        data_col = valid_df[param].dropna()
        if not data_col.empty and self.current_stim:
            sim_typ = data_col.mean()
            sim_std = data_col.std() if len(data_col) > 1 else 0.0
            v_min, v_max = None, None
            pass_col = f"{param}_pass"
            for t in self.current_stim.tests:
                for v in t.value_lst:
                    if v.name == param:
                        v_min = getattr(v, 'vmin', getattr(v, 'min', None))
                        v_max = getattr(v, 'vmax', getattr(v, 'max', None))
            cpk_vals, z_vals = [], []
            if sim_std > 0:
                if v_min is not None:
                    cpk_vals.append(((sim_typ - v_min) / sim_std) / 3.0)
                    z_vals.append((sim_typ - v_min) / sim_std)
                if v_max is not None:
                    cpk_vals.append(((v_max - sim_typ) / sim_std) / 3.0)
                    z_vals.append((v_max - sim_typ) / sim_std)

            # fail-rate
            if pass_col in valid_df.columns:
                n_fail = int((valid_df[pass_col] == False).sum())
                n_tot  = len(valid_df[pass_col])
                fail_pct = n_fail / n_tot * 100 if n_tot else 0
                fail_txt  = f"Fail: {fail_pct:.1f}%"
                fail_color = "#2ecc71" if n_fail == 0 else "#e74c3c"
            else:
                fail_txt, fail_color = "Fail: —", "#888888"

            # mean / std
            def _eng(v):
                """Very small engineering formatter – avoids sci notation for typical EDA values."""
                if abs(v) >= 1e3:  return f"{v/1e3:.3g}k"
                if abs(v) >= 1:    return f"{v:.4g}"
                if abs(v) >= 1e-3: return f"{v*1e3:.3g}m"
                if abs(v) >= 1e-6: return f"{v*1e6:.3g}µ"
                return f"{v:.3g}"

            self.lbl_kpi_mean.configure(text=f"μ: {_eng(sim_typ)}")
            self.lbl_kpi_std.configure(text=f"std: {_eng(sim_std)}")
            self.lbl_kpi_fail.configure(text=fail_txt, text_color=fail_color)

            if cpk_vals:
                cpk, sigma_lvl = min(cpk_vals), min(z_vals)
                color = "#2ecc71" if cpk >= 1.33 else ("#f1c40f" if cpk >= 1.0 else "#e74c3c")
                self.lbl_kpi_cpk.configure(text=f"Cpk: {cpk:.2f}", text_color=color)
                self.lbl_kpi_sigma.configure(text=f"σ: {sigma_lvl:.2f}", text_color=color)
            else:
                self.lbl_kpi_cpk.configure(text="Cpk: —", text_color="white")
                self.lbl_kpi_sigma.configure(text="σ: —", text_color="white")
        
        PlotManager.draw_histogram(self.fig, self.ax, self.canvas, valid_df, self.current_stim, param, dist_type, group_col, bins_val, do_zoom, comp_run)

    def setup_adv_analytics_tab(self):
        self.tab_adv.grid_columnconfigure(0, weight=1)
        self.tab_adv.grid_rowconfigure(1, weight=1)
        
        control_frame = ctk.CTkFrame(self.tab_adv, fg_color="transparent", height=40)
        control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        control_frame.pack_propagate(False)
        
        _adv_base_modes = ["Scatter Plot", "Corner Yield Matrix", "Correlation Heatmap", "Sensitivity (Tornado)", "Fail Breakdown (Pie Chart)"]
        try:
            from chipify.plugin_loader import get_plot_plugins
            _adv_base_modes += [cls.name for cls in get_plot_plugins()]
        except Exception:
            pass
        self.adv_mode_var = ctk.StringVar(value="Fail Breakdown (Pie Chart)")
        self.adv_mode_selector = ctk.CTkSegmentedButton(
            control_frame,
            values=_adv_base_modes,
            variable=self.adv_mode_var, command=self.on_adv_mode_change
        )
        self.adv_mode_selector.pack(side=tk.LEFT, padx=(0, 30))
        
        self.adv_controls_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
        self.adv_controls_frame.pack(side=tk.LEFT, fill="x", expand=True)
        
        self.scatter_x_var = ctk.StringVar(value="-")
        self.scatter_y_var = ctk.StringVar(value="-")
        self.tornado_target_var = ctk.StringVar(value="-")
        
        self.lbl_x = ctk.CTkLabel(self.adv_controls_frame, text="X-Axis:")
        self.scatter_x_dropdown = ctk.CTkOptionMenu(self.adv_controls_frame, variable=self.scatter_x_var, command=self.update_adv_plots, dynamic_resizing=False)
        self.lbl_y = ctk.CTkLabel(self.adv_controls_frame, text="Y-Axis:")
        self.scatter_y_dropdown = ctk.CTkOptionMenu(self.adv_controls_frame, variable=self.scatter_y_var, command=self.update_adv_plots, dynamic_resizing=False)
        
        self.lbl_tornado = ctk.CTkLabel(self.adv_controls_frame, text="Target Measurement:")
        self.tornado_target_dropdown = ctk.CTkOptionMenu(self.adv_controls_frame, variable=self.tornado_target_var, command=self.update_adv_plots, dynamic_resizing=False)

        self.adv_fig = plt.figure(figsize=(8, 5))
        self.adv_fig.patch.set_facecolor(panel_color)
        self.adv_canvas = FigureCanvasTkAgg(self.adv_fig, master=self.tab_adv)
        self.adv_canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

        self.scatter_annot = self.adv_fig.add_subplot(111).annotate("", xy=(0,0), xytext=(15,15), textcoords="offset points", bbox=dict(boxstyle="round,pad=0.5", fc="#1c1c1c", ec="#3484F0", lw=1, alpha=0.9), color="white", arrowprops=dict(arrowstyle="-|>", color="#3484F0"))
        self.scatter_annot.set_visible(False)
        self.adv_canvas.mpl_connect("motion_notify_event", self.on_hover_scatter)

    def on_hover_scatter(self, event):
        if self.adv_mode_var.get() != "Scatter Plot": return
        if not hasattr(self, 'sc_plot') or not hasattr(self, 'scatter_df'): return
        if self.sc_plot is None: return
        
        vis = self.scatter_annot.get_visible()
        if event.inaxes == self.adv_fig.axes[0]:
            cont, ind = self.sc_plot.contains(event)
            if cont:
                idx = ind["ind"][0] 
                row = self.scatter_df.iloc[idx]
                run_id = row.name 
                x_col, y_col = self.scatter_x_var.get(), self.scatter_y_var.get()
                x_val, y_val = row[x_col], row[y_col]
                
                text_lines = [f"Run #{run_id}", "-"*15, f"{x_col}: {x_val:.4g}", f"{y_col}: {y_val:.4g}", "-"*15]
                if self.current_stim:
                    for p in self.current_stim.params.keys():
                        if p in row and self.scatter_df[p].nunique() > 1:
                            text_lines.append(f"{p}: {row[p]}")
                            
                self.scatter_annot.xy = (x_val, y_val)
                self.scatter_annot.set_text("\n".join(text_lines))
                # Mirror tooltip near edges so it does not get clipped.
                ax_bbox = self.adv_fig.axes[0].get_window_extent()
                x_off = -15 if event.x > (ax_bbox.x0 + ax_bbox.width * 0.70) else 15
                y_off = -15 if event.y > (ax_bbox.y0 + ax_bbox.height * 0.70) else 15
                self.scatter_annot.set_position((x_off, y_off))
                self.scatter_annot.set_ha("right" if x_off < 0 else "left")
                self.scatter_annot.set_va("top" if y_off < 0 else "bottom")
                self.scatter_annot.set_annotation_clip(False)
                self.scatter_annot.set_visible(True)
                self.adv_canvas.draw_idle()
            else:
                if vis:
                    self.scatter_annot.set_visible(False)
                    self.adv_canvas.draw_idle()

    # --- NEU: Dropdowns dynamisch filtern ---
    def on_adv_mode_change(self, mode):
        self.lbl_x.pack_forget()
        self.scatter_x_dropdown.pack_forget()
        self.lbl_y.pack_forget()
        self.scatter_y_dropdown.pack_forget()
        self.lbl_tornado.pack_forget()
        self.tornado_target_dropdown.pack_forget()
        
        if mode in ["Scatter Plot", "Corner Yield Matrix"]:
            self.lbl_x.pack(side=tk.LEFT, padx=(0, 5))
            self.scatter_x_dropdown.pack(side=tk.LEFT, padx=(0, 15))
            self.lbl_y.pack(side=tk.LEFT, padx=(0, 5))
            self.scatter_y_dropdown.pack(side=tk.LEFT, padx=(0, 15))
            
            # Dropdown options by mode:
            # - Corner Yield Matrix: only truly swept YAML params
            # - Scatter Plot: swept params + measurements + derived equations
            if mode == "Corner Yield Matrix":
                options = self.sweep_params if self.sweep_params else ["-"]
            else:
                meas_names = []
                if self.current_stim is not None:
                    for t in self.current_stim.tests:
                        for v in t.value_lst:
                            if v.name not in meas_names:
                                meas_names.append(v.name)

                derived_names = []
                if self.current_df is not None:
                    derived_names = [c for c in self._derived_cols if c in self.current_df.columns]

                options = []
                for name in self.sweep_params + meas_names + derived_names:
                    if name not in options:
                        options.append(name)
                if not options:
                    options = ["-"]
                
            self.scatter_x_dropdown.configure(values=options)
            self.scatter_y_dropdown.configure(values=options)
            
            if self.scatter_x_var.get() not in options:
                self.scatter_x_var.set(options[0] if options else "-")
            if self.scatter_y_var.get() not in options:
                self.scatter_y_var.set(options[1] if len(options)>1 else options[0] if options else "-")
                
        elif mode == "Sensitivity (Tornado)":
            self.lbl_tornado.pack(side=tk.LEFT, padx=(0, 5))
            self.tornado_target_dropdown.pack(side=tk.LEFT, padx=(0, 15))
            
        self.update_adv_plots()

    def update_adv_plots(self, *args):
        if self.current_df is None: return
        valid_df = self.current_df[self.current_df['sim_error'] == 'None']
        if valid_df.empty: return

        mode = self.adv_mode_var.get()
        x_col = self.scatter_x_var.get()
        y_col = self.scatter_y_var.get()
        target = self.tornado_target_var.get()
        
        self.sc_plot, self.scatter_df = PlotManager.draw_adv_plot(
            self.adv_fig, None,  # always clf + tight_layout; prevents axis-shrink ghosting
            self.adv_canvas, valid_df, self.current_stim, mode, x_col, y_col, target, bg_color=panel_color
        )
        
        if mode == "Scatter Plot":
            self.scatter_annot = self.adv_fig.axes[0].annotate("", xy=(0,0), xytext=(15,15), textcoords="offset points", bbox=dict(boxstyle="round,pad=0.4", fc="#1c1c1c", ec="#3484F0", lw=1, alpha=0.95), color="white", arrowprops=dict(arrowstyle="-|>", color="#3484F0"))
            self.scatter_annot.set_visible(False)

    # ==========================================
    # TRANSIENT TAB
    # ==========================================
    def setup_transient_tab(self):
        self.tab_tran.grid_columnconfigure(0, weight=1)
        self.tab_tran.grid_rowconfigure(1, weight=1)

        # ── Control row ──────────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(self.tab_tran, fg_color="transparent")
        ctrl.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        # Run-selection mode
        ctk.CTkLabel(ctrl, text="Runs:").pack(side=tk.LEFT, padx=(0, 4))
        self._tran_mode_var = ctk.StringVar(value="All Valid")
        self._tran_mode_btn = ctk.CTkSegmentedButton(
            ctrl,
            values=["All Valid", "Failing Only", "First N", "Custom IDs"],
            variable=self._tran_mode_var,
            command=self._on_tran_mode_change,
            width=320,
        )
        self._tran_mode_btn.pack(side=tk.LEFT, padx=(0, 10))

        # N / custom-id entry (visible for "First N" and "Custom IDs")
        self._tran_n_var = ctk.StringVar(value="50")
        self._tran_n_entry = ctk.CTkEntry(
            ctrl, textvariable=self._tran_n_var, width=90,
            placeholder_text="N or ids…"
        )

        # Refresh button
        ctk.CTkButton(
            ctrl, text="↺  Refresh", width=100,
            command=self.update_transient_plot,
            fg_color="#3484F0", hover_color="#1a6fc4",
        ).pack(side=tk.RIGHT, padx=(8, 0))

        # ── Body: signals selector (left) + plot (right) ─────────────────────
        body = ctk.CTkFrame(self.tab_tran, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # Signal selector panel
        sig_panel = ctk.CTkFrame(body, fg_color=panel_color, width=160, corner_radius=6)
        sig_panel.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        sig_panel.grid_propagate(False)
        sig_panel.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            sig_panel, text="Signals",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#3484F0"
        ).grid(row=0, column=0, padx=8, pady=(8, 4), sticky="w")

        # Native tk.Listbox – supports extended multi-select without extra deps
        list_frame = ctk.CTkFrame(sig_panel, fg_color="transparent")
        list_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self._tran_sig_lb = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            bg="#1a1a1a", fg="white",
            selectbackground="#3484F0", selectforeground="white",
            activestyle="none",
            highlightthickness=0, borderwidth=0,
            font=("Courier", 11),
        )
        self._tran_sig_lb.grid(row=0, column=0, sticky="nsew")

        lb_scroll = tk.Scrollbar(list_frame, orient="vertical",
                                 command=self._tran_sig_lb.yview)
        lb_scroll.grid(row=0, column=1, sticky="ns")
        self._tran_sig_lb.configure(yscrollcommand=lb_scroll.set)

        ctk.CTkButton(
            sig_panel, text="Select All", height=26,
            command=lambda: self._tran_sig_lb.select_set(0, tk.END),
            fg_color="transparent", border_width=1,
            text_color=("gray10", "#DCE4EE"),
        ).grid(row=2, column=0, padx=6, pady=(0, 6), sticky="ew")

        # Matplotlib canvas
        plt.style.use('dark_background')
        self.tran_fig = plt.figure(figsize=(8, 5))
        self.tran_fig.patch.set_facecolor(panel_color)
        self.tran_canvas = FigureCanvasTkAgg(self.tran_fig, master=body)
        self.tran_canvas.get_tk_widget().grid(row=0, column=1, sticky="nsew")

        # Hover state
        self._tran_line_map: dict = {}
        self._tran_annot = None
        self.tran_canvas.mpl_connect("motion_notify_event", self._on_tran_hover)

    def _on_tran_mode_change(self, mode):
        if mode in ("First N", "Custom IDs"):
            self._tran_n_entry.pack(side=tk.LEFT, padx=(0, 10))
        else:
            self._tran_n_entry.pack_forget()

    def _resolve_tran_dir(self) -> str:
        """
        Map the currently loaded run → its tran_data directory.

        Priority:
        1. df.attrs['tran_dir']     — freshly simulated run (in-process)
        2. run_meta sidecar         — history run with .meta.json
        3. Newest out/tran_data/*/  — fallback glob
        """
        # 1. In-memory attr (set by run_sim on a fresh result)
        if self.current_df is not None:
            td = self.current_df.attrs.get("tran_dir", "")
            if td and os.path.isdir(td):
                return td

        # 2a. Latest pointer file (written next to simulation_results.csv on each sim)
        pointer = os.path.join(settings.OUT_DIR, "tran_data", ".latest")
        if os.path.exists(pointer):
            try:
                with open(pointer, "r", encoding="utf-8") as _f:
                    td = _f.read().strip()
                if td and os.path.isdir(td):
                    return td
            except Exception:
                pass

        # 2b. History meta sidecar
        selection = self.history_dropdown.get() if hasattr(self, "history_dropdown") else ""
        if selection and selection not in ("No runs found", "Latest (simulation_results)"):
            csv_path = os.path.join(settings.OUT_DIR, "history", selection)
            from chipify import run_meta as _rm
            meta = _rm.read_meta(csv_path)
            td = meta.get("tran_dir", "")
            if td and os.path.isdir(td):
                return td

        # 3. Newest tran_data sub-directory
        tran_base = os.path.join(settings.OUT_DIR, "tran_data")
        if os.path.isdir(tran_base):
            subdirs = sorted(
                (d for d in glob.glob(os.path.join(tran_base, "*")) if os.path.isdir(d)),
                reverse=True,
            )
            if subdirs:
                return subdirs[0]

        return ""

    def _refresh_transient_signal_list(self):
        """Re-populate the signals listbox from Stimuli + active custom equations."""
        self._tran_sig_lb.delete(0, tk.END)
        seen: list = []

        if self.current_stim is not None:
            for test in self.current_stim.tests:
                for sig in getattr(test, "transient_signals", []):
                    if sig not in seen:
                        seen.append(sig)

        # Also expose active transient equations as derived waveform signals.
        for eq in app_config.load_config().get("transient_equations", []):
            name = eq.get("name", "").strip()
            if name and name not in seen:
                seen.append(name)

        for sig in seen:
            self._tran_sig_lb.insert(tk.END, sig)
        if seen:
            self._tran_sig_lb.select_set(0, tk.END)

    def update_transient_plot(self, *_args):
        """Build run_ids list, resolve signals, delegate to PlotManager."""
        if self.current_df is None:
            return

        tran_dir = self._resolve_tran_dir()
        if not tran_dir:
            self._tran_line_map = PlotManager.draw_transient_plot(
                self.tran_fig, self.tran_canvas, "", [], [],
                bg_color=panel_color,
            )
            self._tran_annot = None
            return

        # Collect selected signals from listbox
        selected_signals = [
            self._tran_sig_lb.get(i)
            for i in self._tran_sig_lb.curselection()
        ]
        if not selected_signals:
            self._tran_line_map = PlotManager.draw_transient_plot(
                self.tran_fig, self.tran_canvas, tran_dir, [], [],
                bg_color=panel_color,
            )
            self._tran_annot = None
            return

        # Derive run_id pool from selection mode
        df = self.current_df
        if 'run_id' not in df.columns:
            return
        mode = self._tran_mode_var.get()

        if mode == "All Valid":
            run_ids = list(df[df['sim_error'] == 'None']['run_id'].astype(str))
        elif mode == "Failing Only":
            if 'global_pass' in df.columns:
                run_ids = list(df[df['global_pass'] == False]['run_id'].astype(str))
            else:
                run_ids = []
        elif mode == "First N":
            try:
                n = int(self._tran_n_var.get())
            except ValueError:
                n = 50
            run_ids = list(df[df['sim_error'] == 'None']['run_id'].astype(str).head(n))
        else:  # Custom IDs
            raw = self._tran_n_var.get()
            run_ids = [r.strip().zfill(6) for r in raw.replace(",", " ").split() if r.strip()]

        # Hard cap
        _CAP = 500
        if len(run_ids) > _CAP:
            log.warning("Transient plot: capping %d run_ids to %d.", len(run_ids), _CAP)
            run_ids = run_ids[:_CAP]

        # Build pass_map for per-curve coloring
        pass_map: dict = {}
        if 'global_pass' in df.columns:
            for _, row in df[['run_id', 'global_pass']].dropna(subset=['run_id']).iterrows():
                pass_map[str(row['run_id']).zfill(6)] = bool(row['global_pass'])

        equations = app_config.load_config().get("transient_equations", [])
        self._tran_line_map = PlotManager.draw_transient_plot(
            self.tran_fig, self.tran_canvas, tran_dir,
            run_ids, selected_signals,
            pass_map=pass_map,
            bg_color=panel_color,
            equations=equations,
        )
        # Store original line properties for hover highlight/restore.
        self._tran_line_orig = {
            line: (line.get_linewidth(), line.get_alpha() or 1.0, line.get_zorder())
            for line in self._tran_line_map
        }
        self._tran_hover_line = None

        # Rebuild hover annotation on the fresh axis (fig.clf() destroyed the old one).
        if self.tran_fig.axes:
            self._tran_annot = self.tran_fig.axes[0].annotate(
                "", xy=(0, 0), xytext=(14, 14), textcoords="offset points",
                bbox=dict(boxstyle="round,pad=0.45", fc="#1c1c1c", ec="#3484F0",
                          lw=1, alpha=0.95),
                color="white",
                arrowprops=dict(arrowstyle="-|>", color="#3484F0"),
            )
            self._tran_annot.set_visible(False)
        else:
            self._tran_annot = None

        # Build combined DataFrame for further processing / export.
        try:
            self._tran_df = self._load_tran_df(tran_dir, run_ids, equations)
        except Exception as _e:
            log.warning("Could not build _tran_df: %s", _e)
            self._tran_df = pd.DataFrame()

    def _on_tran_hover(self, event):
        """Show a tooltip when the mouse is near a transient curve."""
        annot = self._tran_annot
        if annot is None or not self.tran_fig.axes:
            return
        if event.inaxes != self.tran_fig.axes[0]:
            if annot.get_visible():
                annot.set_visible(False)
                self.tran_canvas.draw_idle()
            return

        hit_line, hit_run_id, hit_sig = None, None, None
        for line, (run_id, sig) in self._tran_line_map.items():
            try:
                contains, _ = line.contains(event)
                if contains:
                    hit_line, hit_run_id, hit_sig = line, run_id, sig
                    break
            except Exception:
                continue

        if hit_run_id is None:
            # Restore previously highlighted line.
            if self._tran_hover_line is not None:
                orig = self._tran_line_orig.get(self._tran_hover_line)
                if orig:
                    self._tran_hover_line.set_linewidth(orig[0])
                    self._tran_hover_line.set_alpha(orig[1])
                    self._tran_hover_line.set_zorder(orig[2])
                self._tran_hover_line = None
            if annot.get_visible():
                annot.set_visible(False)
                self.tran_canvas.draw_idle()
            return

        # Highlight the hit line; restore the previous one.
        if hit_line != self._tran_hover_line:
            if self._tran_hover_line is not None:
                orig = self._tran_line_orig.get(self._tran_hover_line)
                if orig:
                    self._tran_hover_line.set_linewidth(orig[0])
                    self._tran_hover_line.set_alpha(orig[1])
                    self._tran_hover_line.set_zorder(orig[2])
            hit_line.set_linewidth(2.2)
            hit_line.set_alpha(0.95)
            hit_line.set_zorder(5)
            self._tran_hover_line = hit_line

        # Build tooltip text
        lines = [f"Run ID: {hit_run_id}", f"Signal: {hit_sig}"]
        df = self.current_df
        if df is not None and 'run_id' in df.columns:
            try:
                row = df[df['run_id'].astype(str).str.zfill(6) == hit_run_id]
                if not row.empty:
                    row = row.iloc[0]
                    status = "PASS" if bool(row.get('global_pass', True)) else "FAIL"
                    lines.append(f"Status: {status}")
                    if self.current_stim:
                        lines.append("─" * 16)
                        for p in self.current_stim.params.keys():
                            if p in row.index:
                                lines.append(f"{p}: {row[p]}")
            except Exception:
                pass

        # Position annotation at current mouse location
        ax = self.tran_fig.axes[0]
        ax_bbox = ax.get_window_extent()
        x_off = -14 if event.x > (ax_bbox.x0 + ax_bbox.width * 0.70) else 14
        y_off = -14 if event.y > (ax_bbox.y0 + ax_bbox.height * 0.70) else 14
        inv = ax.transData.inverted()
        x_data, y_data = inv.transform((event.x, event.y))
        annot.xy = (x_data, y_data)
        annot.set_text("\n".join(lines))
        annot.set_position((x_off, y_off))
        annot.set_ha("right" if x_off < 0 else "left")
        annot.set_va("top" if y_off < 0 else "bottom")
        annot.set_annotation_clip(False)
        annot.set_visible(True)
        self.tran_canvas.draw_idle()

    def apply_treeview_dark_style(self):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background=panel_color, foreground="white", rowheight=25, fieldbackground=panel_color, borderwidth=0)
        style.map('Treeview', background=[('selected', '#1f538d')])
        style.configure("Treeview.Heading", background="#565b5e", foreground="white", relief="flat")
        style.map("Treeview.Heading", background=[('active', '#3484F0')])
        self.tree.tag_configure('pass', background='#1a4d1a') 
        self.tree.tag_configure('fail', background='#4d1a1a') 
        self.tree.tag_configure('warn', background='#e67e22', foreground='black')

    # ==========================================
    # SIMULATION CORE
    # ==========================================
    def progress_callback_wrapper(self, current, total):
        if self.stop_event.is_set(): raise InterruptedError("Simulation canceled!")
        self.after(0, self._set_progress_ui, current, total)
        
    def _set_progress_ui(self, current, total):
        self.progress_bar.set(current / total)
        self.lbl_status.configure(text=f"Simulating... {current}/{total}", text_color="#3484F0")

    def start_simulation(self):
        selected = self.yaml_dropdown.get()
        if not selected or selected == "No files found": return
            
        yaml_path = os.path.join(settings.IN_DIR, selected)
        log.info("start_simulation: %s", selected)
        
        self.btn_start.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")
        self.btn_stop.configure(state="normal") 
        self.stop_event.clear() 
        self.last_sim_duration_sec = None
        
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Status: Initializing cores...", text_color="yellow")
        
        for item in self.tree.get_children(): self.tree.delete(item)
        for widget in self.wc_scroll.winfo_children(): widget.destroy()
        self.lbl_wc_empty = ctk.CTkLabel(self.wc_scroll, text="Simulating...", text_color="gray")
        self.lbl_wc_empty.pack(pady=50)
            
        threading.Thread(target=self.run_sim_thread, args=(yaml_path,), daemon=True).start()

    def stop_simulation(self):
        log.info("stop_simulation: user requested abort.")
        self.stop_event.set()
        simulator.abort_simulation()
        self.lbl_status.configure(text="Status: Canceling simulation...", text_color="orange")
        self.btn_stop.configure(state="disabled")

    def run_sim_thread(self, yaml_path):
        log.info("run_sim_thread started. Thread: %s", threading.current_thread().name)
        t0 = time.perf_counter()
        try:
            stim = util.Stimuli(yaml_path)
            df = simulator.run_sim(stim, progress_callback=self.progress_callback_wrapper)
            
            if df is not None:
                elapsed = max(0.0, time.perf_counter() - t0)
                self.last_sim_duration_sec = elapsed
                if len(df) > 0:
                    df["simulation_duration_s_total"] = np.nan
                    df.at[df.index[0], "simulation_duration_s_total"] = elapsed
                log.info("run_sim returned %d rows. Saving results...", len(df))
                csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
                df.to_csv(csv_out, index=False)

                # Write a pointer so the Transient tab can resolve tran_dir on reload.
                _tran_dir_val = df.attrs.get("tran_dir", "")
                if _tran_dir_val:
                    try:
                        _ptr = os.path.join(settings.OUT_DIR, "tran_data", ".latest")
                        os.makedirs(os.path.dirname(_ptr), exist_ok=True)
                        with open(_ptr, "w", encoding="utf-8") as _f:
                            _f.write(_tran_dir_val)
                    except Exception as _e:
                        log.warning("Could not write tran_dir pointer: %s", _e)
                
                try:
                    from chipify import run_meta
                    history_dir = os.path.join(settings.OUT_DIR, "history")
                    os.makedirs(history_dir, exist_ok=True)
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    history_file = os.path.join(history_dir, f"run_{timestamp}.csv")
                    df.to_csv(history_file, index=False)
                    # write companion metadata sidecar
                    total = len(df)
                    valid = int((df.get('sim_error', 'None') == 'None').sum()) if 'sim_error' in df.columns else total
                    gpass = int(df['global_pass'].sum()) if 'global_pass' in df.columns else None
                    gyield = (gpass / total * 100) if (gpass is not None and total > 0) else None
                    run_meta.write_meta(
                        history_file,
                        yaml_name=os.path.basename(yaml_path),
                        duration_s=elapsed,
                        total_runs=total,
                        valid_runs=valid,
                        global_yield=gyield,
                        tran_dir=df.attrs.get("tran_dir", ""),
                    )
                except Exception as e:
                    log.warning("Could not save history: %s", e)
                self.after(0, self.refresh_history)
                self.after(0, self.update_ui_results, df, stim, True)
                self.after(0, lambda: self.lbl_status.configure(text=f"Status: Completed in {elapsed:.1f}s", text_color="#2ecc71"))
            else:
                log.info("run_sim returned None (aborted or error).")

        except Exception as e:
            log.exception("run_sim_thread raised an exception: %s", e)
            self.after(0, self.show_error, str(e))

        finally:
            # Always re-enable the UI – even if the thread was interrupted,
            # hung in init, or raised an unexpected exception.
            log.info("run_sim_thread finished. Re-enabling UI.")
            self.after(0, set_btn_start_ready, self)

    def show_error(self, error_msg):
        self.lbl_status.configure(text="Status: Error / Aborted!", text_color="red")
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_refresh.configure(state="normal")
        
        for widget in self.wc_scroll.winfo_children(): widget.destroy()
        ctk.CTkLabel(self.wc_scroll, text=f"LOG:\n{error_msg}", text_color="red", justify="left").pack(anchor="w", padx=20, pady=20)

    def update_ui_results(self, df, stim, switch_tab=False):
        if 'sim_error' not in df.columns: df['sim_error'] = 'None'
        df['sim_error'] = df['sim_error'].fillna('None').astype(str)
        df.loc[df['sim_error'].str.lower() == 'nan', 'sim_error'] = 'None'
        
        self.current_df = df
        self.current_stim = stim

        # Apply saved custom equations so derived columns are available everywhere
        self._derived_cols = self._apply_custom_equations()

        total = len(self.current_df)
        crashes = len(self.current_df[self.current_df['sim_error'] != 'None'])
        valid_df = self.current_df[self.current_df['sim_error'] == 'None']
        
        tb_pass_cols = [c for c in self.current_df.columns if c.endswith('_overall_pass')]
        self.current_df['global_pass'] = True
        for col in tb_pass_cols:
            self.current_df['global_pass'] = self.current_df['global_pass'] & self.current_df[col]
            
        global_passed = int(self.current_df['global_pass'].sum())
        global_yield = (global_passed / total) * 100 if total > 0 else 0
        
        self.lbl_total.configure(text=f"Iterations: {total}")
        self.lbl_crashes.configure(text=f"Crashes: {crashes}")
        
        yield_color = "#2ecc71" if global_yield == 100 else "#f1c40f" if global_yield > 0 else "#e74c3c"
        self.lbl_yield.configure(text=f"Global Yield: {global_yield:.1f}%", text_color=yield_color)
            
        def fmt(val): return "-" if pd.isna(val) or val is None else f"{val:.4g}"

        failed_params = []
        meas_cols = [] 
        
        for item in self.tree.get_children(): self.tree.delete(item)

        for test in stim.tests:
            for val_obj in test.value_lst:
                p_name = val_obj.name
                if p_name in valid_df.columns:
                    meas_cols.append(p_name)
                    
                    data_col = valid_df[p_name].dropna()
                    sim_min = data_col.min() if not data_col.empty else np.nan
                    sim_max = data_col.max() if not data_col.empty else np.nan
                    sim_typ = data_col.mean() if not data_col.empty else np.nan
                    sim_std = data_col.std() if len(data_col) > 1 else 0.0
                    
                    v_min = getattr(val_obj, 'vmin', getattr(val_obj, 'min', None))
                    v_max = getattr(val_obj, 'vmax', getattr(val_obj, 'max', None))
                    
                    cpk_vals, z_vals = [], []
                    if sim_std > 0:
                        if v_min is not None:
                            cpk_vals.append(((sim_typ - v_min) / sim_std) / 3.0)
                            z_vals.append((sim_typ - v_min) / sim_std)
                        if v_max is not None:
                            cpk_vals.append(((v_max - sim_typ) / sim_std) / 3.0)
                            z_vals.append((v_max - sim_typ) / sim_std)
                            
                    if cpk_vals:
                        cpk, sigma_lvl = min(cpk_vals), min(z_vals)
                        cpk_str, sigma_str = f"{cpk:.2f}", f"{sigma_lvl:.2f}σ"
                    else:
                        if sim_std == 0.0 and (v_min is not None or v_max is not None):
                            if (v_min is None or sim_typ >= v_min) and (v_max is None or sim_typ <= v_max):
                                cpk_str, sigma_str = "INF", "INF"
                            else: cpk_str, sigma_str = "0.00", "0.00"
                        else: cpk_str, sigma_str = "-", "-"
                    
                    pass_col = f"{p_name}_pass"
                    if pass_col in valid_df.columns and valid_df[pass_col].all():
                        status, tags = "PASS", ('pass',)
                    else:
                        status, tags = "FAIL", ('fail',)
                        failed_params.append((test, val_obj))
                        
                    self.tree.insert("", tk.END, values=(p_name, fmt(sim_min), fmt(sim_typ), fmt(sim_max), fmt(v_min), fmt(v_max), cpk_str, sigma_str, status), tags=tags)
                    
        if not meas_cols and total > 0:
             self.tree.insert("", tk.END, values=("No matching params", "-", "-", "-", "-", "-", "-", "-", "WARN"), tags=('warn',))
                    
        # --- ZWISCHENSPEICHERN DER SPALTEN ---
        numeric_cols = valid_df.select_dtypes(include=[np.number]).columns.tolist()
        self.all_plot_cols = [c for c in numeric_cols if not c.endswith('_pass')]
        # Only treat parameters as sweep params when they are explicitly enumerated
        # in YAML with more than one value (fixed params like temp=27 are excluded).
        self.sweep_params = []
        for p_name, p_values in stim.params.items():
            if p_name not in valid_df.columns:
                continue
            try:
                is_enumerated = hasattr(p_values, "__len__") and not isinstance(p_values, str)
                if is_enumerated and len(p_values) > 1:
                    self.sweep_params.append(p_name)
            except Exception:
                continue
        
        self.group_by_dropdown.configure(values=["None"] + self.sweep_params)
        
        if self.group_by_var.get() not in ["None"] + self.sweep_params:
            self.group_by_var.set("None")
        self.on_group_by_change(self.group_by_var.get())
        
        # Merge measurement columns with any successfully derived columns
        valid_derived = [c for c in self._derived_cols if c in valid_df.columns]
        all_plot_meas = meas_cols + [c for c in valid_derived if c not in meas_cols]

        if all_plot_meas:
            self.plot_param_dropdown.configure(values=all_plot_meas)
            if self.plot_param_var.get() not in all_plot_meas:
                self.plot_param_var.set(all_plot_meas[0])
            self.update_plot()
            self.tornado_target_dropdown.configure(values=all_plot_meas)
            if self.tornado_target_var.get() not in all_plot_meas:
                self.tornado_target_var.set(all_plot_meas[0])
            
        # UI-Update für Dropdowns triggern
        self.on_adv_mode_change(self.adv_mode_var.get())
                    
        for widget in self.wc_scroll.winfo_children(): widget.destroy()
            
        if not meas_cols and total > 0:
            ctk.CTkLabel(self.wc_scroll, text="Loaded CSV does not match the current Datasheet specifications.", text_color="#e67e22", font=ctk.CTkFont(size=14)).pack(pady=50)
        elif not failed_params:
            ctk.CTkLabel(self.wc_scroll, text="All specifications met! No outliers found.", text_color="#2ecc71", font=ctk.CTkFont(size=16)).pack(pady=50)
        else:
            param_cols = list(stim.params.keys())
            for test, val_obj in failed_params:
                p_name, pass_col = val_obj.name, f"{val_obj.name}_pass"
                failed_rows = valid_df[valid_df[pass_col] == False]
                if failed_rows.empty: continue
                    
                min_fail, max_fail = failed_rows[p_name].min(), failed_rows[p_name].max()
                worst_val, worst_idx, violation = None, None, ""
                
                v_min = getattr(val_obj, 'vmin', getattr(val_obj, 'min', None))
                v_max = getattr(val_obj, 'vmax', getattr(val_obj, 'max', None))
                
                if v_min is not None and min_fail < v_min:
                    worst_val, worst_idx, violation = min_fail, failed_rows[p_name].idxmin(), f"< {fmt(v_min)}"
                elif v_max is not None and max_fail > v_max:
                    worst_val, worst_idx, violation = max_fail, failed_rows[p_name].idxmax(), f"> {fmt(v_max)}"
                    
                if worst_idx is not None:
                    worst_row = failed_rows.loc[worst_idx]
                    card = ctk.CTkFrame(self.wc_scroll, border_width=2, border_color="#e74c3c", corner_radius=8)
                    card.pack(fill="x", padx=10, pady=10)
                    header = ctk.CTkFrame(card, fg_color="#e74c3c", corner_radius=0)
                    header.pack(fill="x")
                    ctk.CTkLabel(header, text=f"FAIL: {p_name} = {fmt(worst_val)}", font=ctk.CTkFont(weight="bold", size=14), text_color="white").pack(anchor="w", padx=15, pady=5)
                    ctk.CTkLabel(card, text=f"Specification exceeded: {violation}", text_color="#ff9999").pack(anchor="w", padx=15, pady=(10, 5))
                    params_text = "\n".join([f"• {k}: {worst_row[k]}" for k in param_cols if k in worst_row])
                    ctk.CTkLabel(card, text=f"Triggering parameters:\n{params_text}", justify="left").pack(anchor="w", padx=15, pady=(0, 15))

        if switch_tab:
            self.tabs.set("Measurements") 
            self.lbl_current_run.configure(text=f"Viewing: Latest (simulation_results)")
            self.history_dropdown.set("Latest (simulation_results)")

        # Refresh transient tab when new data is loaded
        self._refresh_transient_signal_list()
        if self._resolve_tran_dir():
            self.update_transient_plot()

        self._notify_multiplot()

    def _notify_multiplot(self):
        """Trigger a live refresh of the Multi-Plot Dashboard if it is open."""
        if self.multiplot_window is None:
            return
        try:
            self.multiplot_window.refresh_all()
        except Exception:
            self.multiplot_window = None

def set_btn_start_ready(self):
    if not self.lbl_status.cget("text").startswith("Status: Completed in"):
        self.lbl_status.configure(text=f"Status: Ready", text_color="#2ecc71")
    self.btn_start.configure(state="normal")
    self.btn_stop.configure(state="disabled")
    self.btn_refresh.configure(state="normal")

def main():
    app_config.setup_logging()
    log.info("Silicrunch GUI starting up.")
    app = SimifyGUI()
    app.mainloop()
    log.info("Silicrunch GUI shut down.")

if __name__ == "__main__":
    main()