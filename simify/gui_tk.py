import customtkinter as ctk
from tkinter import ttk, messagebox
import tkinter as tk
import os
import glob
import threading
import datetime
import pandas as pd
import numpy as np
import yaml

from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import scipy.stats as stats

from simify import settings
from simify import simulator
from simify import util

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

class SimifyGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Simify EDA Dashboard")
        self.geometry("1300x950")
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.current_df = None
        self.current_stim = None
        
        self.stop_event = threading.Event()
        
        # --- EDITOR STATE ---
        self.current_yaml_path = None
        self.current_yaml_data = {}
        self.raw_yaml_text = ""
        
        self.param_vars = [] 
        self.test_vars = []  
        self.param_key = 'params'
        self.test_key = 'tests'
        
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
        self.left_frame = ctk.CTkFrame(self, width=260, corner_radius=0)
        self.left_frame.grid(row=0, column=0, sticky="nsew")
        self.left_frame.grid_rowconfigure(10, weight=1) 
        self.left_frame.pack_propagate(False)
        
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
        self.btn_pdf.grid(row=8, column=0, padx=20, pady=(0, 20), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self.left_frame)
        self.progress_bar.grid(row=11, column=0, padx=20, pady=(10, 0), sticky="ew")
        self.progress_bar.set(0)
        
        self.lbl_status = ctk.CTkLabel(self.left_frame, text="Status: Ready", text_color="gray")
        self.lbl_status.grid(row=12, column=0, padx=20, pady=(5, 20), sticky="w")
        
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
        
        self.tabs = ctk.CTkTabview(self.right_frame)
        self.tabs.grid(row=2, column=0, sticky="nsew")
        
        self.tab_editor = self.tabs.add("Datasheet Editor") 
        self.tab_table = self.tabs.add("Measurements")
        self.tab_worst = self.tabs.add("Worst-Case Analysis")
        self.tab_hist = self.tabs.add("Histograms")
        self.tab_adv = self.tabs.add("Advanced Analytics") 
        
        self.setup_editor_tab()
        self.setup_table_tab()
        self.setup_worst_case_tab()
        self.setup_histogram_tab()
        self.setup_adv_analytics_tab() 

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
        os.makedirs(report_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path = os.path.join(report_dir, f"report_{timestamp}.pdf")

        self.lbl_status.configure(text="Status: Generating PDF Report...", text_color="yellow")
        self.update() 
        
        valid_df = self.current_df[self.current_df['sim_error'] == 'None']

        try:
            with PdfPages(pdf_path) as pdf:
                fig_text = plt.figure(figsize=(8.27, 11.69)) 
                fig_text.patch.set_facecolor('white')
                ax_text = fig_text.add_subplot(111)
                ax_text.axis('off')
                
                total = len(self.current_df)
                crashes = len(self.current_df[self.current_df['sim_error'] != 'None'])
                tb_pass_cols = [c for c in self.current_df.columns if c.endswith('_overall_pass')]
                tmp_df = self.current_df.copy()
                tmp_df['global_pass'] = True 
                for col in tb_pass_cols: tmp_df['global_pass'] = tmp_df['global_pass'] & tmp_df[col]
                global_yield = (int(tmp_df['global_pass'].sum()) / total) * 100 if total > 0 else 0
                
                title = f"Simify EDA Report - {os.path.basename(self.current_yaml_path)}"
                ax_text.text(0.5, 0.95, title, fontsize=18, weight='bold', ha='center', va='top', color='black')
                ax_text.text(0.5, 0.90, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fontsize=10, ha='center', va='top', color='gray')
                
                summary = (
                    f"Simulation Summary:\n"
                    f"-----------------------------\n"
                    f"Total Iterations: {total}\n"
                    f"Simulator Crashes: {crashes}\n"
                    f"Global Yield: {global_yield:.1f}%\n"
                )
                ax_text.text(0.1, 0.80, summary, fontsize=12, ha='left', va='top', family='monospace', color='black')
                pdf.savefig(fig_text)
                plt.close(fig_text)

                plot_cols = []
                for test in self.current_stim.tests:
                    for val_obj in test.value_lst:
                        if val_obj.name in valid_df.columns:
                            plot_cols.append((val_obj.name, getattr(val_obj, 'vmin', getattr(val_obj, 'min', None)), getattr(val_obj, 'vmax', getattr(val_obj, 'max', None))))
                
                for param, s_min, s_max in plot_cols:
                    data = valid_df[param].dropna()
                    if len(data) == 0: continue
                    
                    fig = plt.figure(figsize=(8, 5))
                    fig.patch.set_facecolor('white')
                    ax = fig.add_subplot(111)
                    ax.grid(True, linestyle='--', alpha=0.5, color='gray')
                    ax.set_title(f"Distribution: {param}", color='black', pad=10)
                    ax.set_xlabel("Simulated Value", color='black')
                    ax.set_ylabel("Density", color='black')
                    
                    ax.hist(data, bins='auto', density=True, color='#3498db', alpha=0.7, edgecolor='black', linewidth=0.5)
                    
                    if s_min is not None: ax.axvline(s_min, color='red', linestyle='dashed', linewidth=2, label=f'Min Spec ({s_min:.4g})')
                    if s_max is not None: ax.axvline(s_max, color='red', linestyle='dashed', linewidth=2, label=f'Max Spec ({s_max:.4g})')
                        
                    ax.tick_params(colors='black')
                    if len(ax.get_legend_handles_labels()[1]) > 0: ax.legend(loc='best', facecolor='white', edgecolor='gray')
                    
                    fig.tight_layout()
                    pdf.savefig(fig)
                    plt.close(fig)

                target = plot_cols[0][0] if plot_cols else None
                if target:
                    correlations = []
                    for p in list(self.current_stim.params.keys()):
                        if p in valid_df.columns and valid_df[p].nunique() > 1:
                            if pd.api.types.is_numeric_dtype(valid_df[p]):
                                corr = valid_df[p].corr(valid_df[target])
                            else:
                                factorized, _ = pd.factorize(valid_df[p])
                                corr = pd.Series(factorized).corr(valid_df[target])
                            if not np.isnan(corr):
                                correlations.append((p, corr))
                                
                    if correlations:
                        correlations.sort(key=lambda x: abs(x[1]))
                        labels = [x[0] for x in correlations]
                        values = [x[1] for x in correlations]
                        colors = ['#2ecc71' if v >= 0 else '#e74c3c' for v in values]
                        
                        fig = plt.figure(figsize=(8, 6))
                        fig.patch.set_facecolor('white')
                        ax = fig.add_subplot(111)
                        ax.barh(labels, values, color=colors, edgecolor='black', linewidth=0.5, alpha=0.8)
                        ax.axvline(0, color='black', linestyle='-', linewidth=1)
                        ax.set_xlabel("Correlation Impact (Sensitivity)", color='black')
                        ax.set_title(f"Sensitivity Analysis for: {target}", color='black', pad=15)
                        ax.tick_params(colors='black')
                        fig.tight_layout()
                        pdf.savefig(fig)
                        plt.close(fig)

            self.lbl_status.configure(text=f"Status: PDF saved to out/reports/", text_color="#2ecc71")
            messagebox.showinfo("Export Successful", f"Report saved as:\n{os.path.basename(pdf_path)}")
        except Exception as e:
            self.lbl_status.configure(text="Status: PDF Export Failed", text_color="red")
            messagebox.showerror("Export Error", f"Failed to generate PDF:\n{e}")

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
        ctk.CTkButton(param_header, text="+ Add Parameter", width=120, height=24, command=self.action_add_param).pack(side="right", padx=5)
        
        params_frame = ctk.CTkFrame(self.editor_scroll)
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
            ctk.CTkLabel(val_frame, text="Typ Spec", text_color="gray").grid(row=0, column=2, padx=5, pady=2, sticky="w")
            ctk.CTkLabel(val_frame, text="Max Spec", text_color="gray").grid(row=0, column=3, padx=5, pady=2, sticky="w")
            
            test_val_vars = []
            for v_idx, (v_name, v_data) in enumerate(tb_data.items()):
                if v_name == 'values': continue 
                if not isinstance(v_data, dict): v_data = {}
                v_name_var = ctk.StringVar(value=str(v_name))
                
                min_val = v_data.get('vmin', v_data.get('min', ''))
                typ_val = v_data.get('vtyp', v_data.get('typ', ''))
                max_val = v_data.get('vmax', v_data.get('max', ''))
                
                v_min = ctk.StringVar(value=str(min_val) if min_val is not None else '')
                v_typ = ctk.StringVar(value=str(typ_val) if typ_val is not None else '')
                v_max = ctk.StringVar(value=str(max_val) if max_val is not None else '')
                
                ctk.CTkEntry(val_frame, textvariable=v_name_var, width=150).grid(row=1+v_idx, column=0, padx=5, pady=2)
                ctk.CTkEntry(val_frame, textvariable=v_min, width=80).grid(row=1+v_idx, column=1, padx=5, pady=2)
                ctk.CTkEntry(val_frame, textvariable=v_typ, width=80).grid(row=1+v_idx, column=2, padx=5, pady=2)
                ctk.CTkEntry(val_frame, textvariable=v_max, width=80).grid(row=1+v_idx, column=3, padx=5, pady=2)
                ctk.CTkButton(val_frame, text="X", width=24, height=24, fg_color="transparent", border_width=1, command=lambda t=t_idx, v=v_name: self.action_del_value(t, v)).grid(row=1+v_idx, column=4, padx=5, pady=2)
                
                test_val_vars.append({'name': v_name_var, 'vmin': v_min, 'typ': v_typ, 'vmax': v_max})
                
            self.test_vars.append({'tb_name': tb_name_var, 'values': test_val_vars})
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
            for v_dict in t_dict['values']:
                name = v_dict['name'].get().strip()
                if not name: continue
                v_data = {}
                vmin_str = v_dict['vmin'].get().strip()
                vtyp_str = v_dict['typ'].get().strip()
                vmax_str = v_dict['vmax'].get().strip()
                
                if vmin_str and vmin_str.lower() != 'none': 
                    try: v_data['min'] = float(vmin_str)
                    except ValueError: v_data['min'] = vmin_str
                if vtyp_str and vtyp_str.lower() != 'none': 
                    try: v_data['typ'] = float(vtyp_str)
                    except ValueError: v_data['typ'] = vtyp_str
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
    # REST OF GUI
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
        
        columns = ("param", "sim_min", "sim_typ", "sim_max", "spec_min", "spec_typ", "spec_max", "status")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings")
        
        self.tree.heading("param", text="Parameter")
        self.tree.heading("sim_min", text="Sim Min")
        self.tree.heading("sim_typ", text="Sim Typ")
        self.tree.heading("sim_max", text="Sim Max")
        self.tree.heading("spec_min", text="Spec Min")
        self.tree.heading("spec_typ", text="Spec Typ")
        self.tree.heading("spec_max", text="Spec Max")
        self.tree.heading("status", text="Status")
        
        for col in columns: self.tree.column(col, width=90, anchor=tk.CENTER)
        self.tree.column("param", width=140, anchor=tk.W)
        
        scrollbar = ttk.Scrollbar(self.tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        
        self.tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        scrollbar.grid(row=0, column=1, sticky="ns")

    def setup_worst_case_tab(self):
        self.tab_worst.grid_columnconfigure(0, weight=1)
        self.tab_worst.grid_rowconfigure(0, weight=1)
        
        self.wc_scroll = ctk.CTkScrollableFrame(self.tab_worst, fg_color="transparent")
        self.wc_scroll.grid(row=0, column=0, sticky="nsew")
        self.lbl_wc_empty = ctk.CTkLabel(self.wc_scroll, text="Start a simulation to see outliers...", text_color="gray")
        self.lbl_wc_empty.pack(pady=50)

    def setup_histogram_tab(self):
        self.tab_hist.grid_columnconfigure(0, weight=1)
        self.tab_hist.grid_rowconfigure(1, weight=1)
        
        # --- UI LAYOUT REWORK: Two Rows for more space ---
        control_frame = ctk.CTkFrame(self.tab_hist, fg_color="transparent")
        control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        row1 = ctk.CTkFrame(control_frame, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        row2 = ctk.CTkFrame(control_frame, fg_color="transparent")
        row2.pack(fill="x", pady=2)
        
        # Row 1 Controls
        ctk.CTkLabel(row1, text="Meas:").pack(side=tk.LEFT, padx=(0, 5))
        self.plot_param_var = ctk.StringVar(value="-")
        self.plot_param_dropdown = ctk.CTkOptionMenu(row1, variable=self.plot_param_var, command=self.update_plot, dynamic_resizing=False, width=130)
        self.plot_param_dropdown.pack(side=tk.LEFT, padx=(0, 15))
        
        ctk.CTkLabel(row1, text="Group by:").pack(side=tk.LEFT, padx=(5, 5))
        self.group_by_var = ctk.StringVar(value="None")
        self.group_by_dropdown = ctk.CTkOptionMenu(row1, variable=self.group_by_var, command=self.update_plot, dynamic_resizing=False, width=130)
        self.group_by_dropdown.pack(side=tk.LEFT, padx=(0, 15))
        
        ctk.CTkLabel(row1, text="Fit Curve:").pack(side=tk.LEFT, padx=(5, 5))
        self.plot_dist_var = ctk.StringVar(value="Gauss (Normal)")
        self.plot_dist_dropdown = ctk.CTkOptionMenu(
            row1, 
            variable=self.plot_dist_var, 
            values=["Gauss (Normal)", "KDE (Smoothed)", "Uniform", "Log-Normal", "Exponential", "Chi-Squared", "None"],
            command=self.update_plot,
            dynamic_resizing=False,
            width=140
        )
        self.plot_dist_dropdown.pack(side=tk.LEFT)

        # Row 2 Controls
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
        self.zoom_checkbox.pack(side=tk.LEFT)

        plt.style.use('dark_background')
        self.fig, self.ax = plt.subplots(figsize=(6, 4))
        self.fig.patch.set_facecolor('#2b2b2b') 
        self.ax.set_facecolor('#2b2b2b')
        self.ax.grid(True, linestyle='--', alpha=0.3)
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.tab_hist)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

    def setup_adv_analytics_tab(self):
        self.tab_adv.grid_columnconfigure(0, weight=1)
        self.tab_adv.grid_rowconfigure(1, weight=1)
        
        control_frame = ctk.CTkFrame(self.tab_adv, fg_color="transparent", height=40)
        control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        control_frame.pack_propagate(False)
        
        self.adv_mode_var = ctk.StringVar(value="Fail Breakdown (Pie Chart)")
        self.adv_mode_selector = ctk.CTkSegmentedButton(
            control_frame, 
            values=["Scatter Plot", "Correlation Heatmap", "Sensitivity (Tornado)", "Fail Breakdown (Pie Chart)"], 
            variable=self.adv_mode_var, 
            command=self.on_adv_mode_change
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
        self.adv_fig.patch.set_facecolor('#2b2b2b')
        self.adv_canvas = FigureCanvasTkAgg(self.adv_fig, master=self.tab_adv)
        self.adv_canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

    def on_adv_mode_change(self, mode):
        self.lbl_x.pack_forget()
        self.scatter_x_dropdown.pack_forget()
        self.lbl_y.pack_forget()
        self.scatter_y_dropdown.pack_forget()
        self.lbl_tornado.pack_forget()
        self.tornado_target_dropdown.pack_forget()
        
        if mode == "Scatter Plot":
            self.lbl_x.pack(side=tk.LEFT, padx=(0, 5))
            self.scatter_x_dropdown.pack(side=tk.LEFT, padx=(0, 15))
            self.lbl_y.pack(side=tk.LEFT, padx=(0, 5))
            self.scatter_y_dropdown.pack(side=tk.LEFT, padx=(0, 15))
        elif mode == "Sensitivity (Tornado)":
            self.lbl_tornado.pack(side=tk.LEFT, padx=(0, 5))
            self.tornado_target_dropdown.pack(side=tk.LEFT, padx=(0, 15))
            
        self.update_adv_plots()

    def update_adv_plots(self, *args):
        if self.current_df is None: return
        valid_df = self.current_df[self.current_df['sim_error'] == 'None']
        if valid_df.empty: return

        mode = self.adv_mode_var.get()
        self.adv_fig.clf() 
        self.adv_ax = self.adv_fig.add_subplot(111)
        self.adv_ax.set_facecolor('#2b2b2b')

        if mode == "Scatter Plot":
            x_col = self.scatter_x_var.get()
            y_col = self.scatter_y_var.get()
            if x_col not in valid_df.columns or y_col not in valid_df.columns: return

            pass_mask = valid_df['global_pass'] == True

            if pass_mask.any():
                self.adv_ax.scatter(valid_df[pass_mask][x_col], valid_df[pass_mask][y_col], 
                                    c='#2ecc71', label='Pass', alpha=0.7, edgecolors='white', linewidths=0.5)
            if (~pass_mask).any():
                self.adv_ax.scatter(valid_df[~pass_mask][x_col], valid_df[~pass_mask][y_col], 
                                    c='#e74c3c', label='Fail', alpha=0.7, edgecolors='white', linewidths=0.5)

            self.adv_ax.set_xlabel(x_col, color='white')
            self.adv_ax.set_ylabel(y_col, color='white')
            self.adv_ax.set_title(f"Shmoo Plot: {y_col} vs {x_col}", color='white', pad=10)
            self.adv_ax.grid(True, linestyle='--', alpha=0.3)
            self.adv_ax.spines['top'].set_visible(False)
            self.adv_ax.spines['right'].set_visible(False)
            
            if len(self.adv_ax.get_legend_handles_labels()[1]) > 0:
                self.adv_ax.legend(facecolor='#2b2b2b', edgecolor='gray')

        elif mode == "Correlation Heatmap":
            numeric_cols = valid_df.select_dtypes(include=[np.number]).columns.tolist()
            plot_cols = [c for c in numeric_cols if not c.endswith('_pass')]
            active_cols = [c for c in plot_cols if valid_df[c].nunique() > 1]
            
            if len(active_cols) < 2:
                self.adv_ax.text(0.5, 0.5, "Not enough varying data for correlation map.", color='white', ha='center', va='center', transform=self.adv_ax.transAxes)
            else:
                corr = valid_df[active_cols].corr()
                cax = self.adv_ax.matshow(corr, cmap='coolwarm', vmin=-1, vmax=1)
                
                cbar = self.adv_fig.colorbar(cax, ax=self.adv_ax, fraction=0.046, pad=0.04)
                cbar.ax.yaxis.set_tick_params(color='white')
                cbar.outline.set_edgecolor('gray')
                plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')

                self.adv_ax.set_xticks(range(len(active_cols)))
                self.adv_ax.set_yticks(range(len(active_cols)))
                self.adv_ax.set_xticklabels(active_cols, rotation=45, ha='left', color='white', fontsize=9)
                self.adv_ax.set_yticklabels(active_cols, color='white', fontsize=9)
                self.adv_ax.xaxis.set_ticks_position('bottom')
                self.adv_ax.set_title("Parameter & Measurement Correlation Matrix", color='white', pad=20)
                
        elif mode == "Sensitivity (Tornado)":
            target = self.tornado_target_var.get()
            if target == "-" or target not in valid_df.columns or self.current_stim is None:
                self.adv_ax.text(0.5, 0.5, "Select a target measurement first.", color='white', ha='center', va='center')
                self.adv_fig.tight_layout()
                self.adv_canvas.draw()
                return

            params = list(self.current_stim.params.keys())
            correlations = []
            for p in params:
                if p not in valid_df.columns: continue
                if valid_df[p].nunique() <= 1: continue
                
                if pd.api.types.is_numeric_dtype(valid_df[p]):
                    corr = valid_df[p].corr(valid_df[target])
                else:
                    factorized, _ = pd.factorize(valid_df[p])
                    corr = pd.Series(factorized).corr(valid_df[target])
                    
                if not np.isnan(corr):
                    correlations.append((p, corr))
                    
            if not correlations:
                self.adv_ax.text(0.5, 0.5, "No varied parameters found.", color='white', ha='center', va='center')
                self.adv_fig.tight_layout()
                self.adv_canvas.draw()
                return
                
            correlations.sort(key=lambda x: abs(x[1]))
            labels = [x[0] for x in correlations]
            values = [x[1] for x in correlations]
            colors = ['#2ecc71' if v >= 0 else '#e74c3c' for v in values]
            
            self.adv_ax.barh(labels, values, color=colors, edgecolor='white', linewidth=0.5, alpha=0.8)
            self.adv_ax.axvline(0, color='gray', linestyle='-', linewidth=1)
            self.adv_ax.set_xlabel("Correlation Impact (Sensitivity)", color='white')
            self.adv_ax.set_title(f"Sensitivity Analysis: What impacts '{target}' the most?", color='white', pad=15)
            self.adv_ax.tick_params(colors='white')
            self.adv_ax.spines['top'].set_visible(False)
            self.adv_ax.spines['right'].set_visible(False)
            self.adv_ax.spines['left'].set_color('gray')
            self.adv_ax.spines['bottom'].set_color('gray')
            
        elif mode == "Fail Breakdown (Pie Chart)":
            pass_cols = [c for c in valid_df.columns if c.endswith('_pass') and not c.endswith('_overall_pass') and c != 'global_pass']
            fail_counts = {}
            for c in pass_cols:
                fails = (valid_df[c] == False).sum()
                if fails > 0:
                    clean_name = c.replace('_pass', '')
                    fail_counts[clean_name] = fails
                    
            if not fail_counts:
                self.adv_ax.text(0.5, 0.5, "100% Yield! No failures to analyze.", color='#2ecc71', ha='center', va='center', fontsize=14, weight='bold')
                self.adv_ax.axis('off')
                self.adv_fig.tight_layout()
                self.adv_canvas.draw()
                return

            labels = list(fail_counts.keys())
            sizes = list(fail_counts.values())
            colors = plt.cm.Pastel1(np.linspace(0, 1, len(labels)))
            explode = [0.1 if s == max(sizes) else 0 for s in sizes] 
            
            patches, texts, autotexts = self.adv_ax.pie(
                sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%', 
                startangle=140, textprops={'color': 'white', 'fontsize': 10}, wedgeprops={'edgecolor': 'gray', 'linewidth': 1}
            )
            
            for autotext in autotexts:
                autotext.set_color('black')
                autotext.set_weight('bold')
                
            self.adv_ax.set_title("Fail Breakdown: Which constraints caused the most failures?", color='white', pad=20)
            self.adv_ax.axis('equal') 

        self.adv_fig.tight_layout()
        self.adv_canvas.draw()

    def apply_treeview_dark_style(self):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", rowheight=25, fieldbackground="#2b2b2b", borderwidth=0)
        style.map('Treeview', background=[('selected', '#1f538d')])
        style.configure("Treeview.Heading", background="#565b5e", foreground="white", relief="flat")
        style.map("Treeview.Heading", background=[('active', '#3484F0')])
        self.tree.tag_configure('pass', background='#1a4d1a') 
        self.tree.tag_configure('fail', background='#4d1a1a') 
        self.tree.tag_configure('warn', background='#e67e22', foreground='black')

    def progress_callback_wrapper(self, current, total):
        if self.stop_event.is_set():
            raise InterruptedError("Simulation abgebrochen durch Benutzer")
        self.after(0, self._set_progress_ui, current, total)
        
    def _set_progress_ui(self, current, total):
        progress = current / total
        self.progress_bar.set(progress)
        self.lbl_status.configure(text=f"Simulating... {current}/{total}", text_color="#3484F0")

    def start_simulation(self):
        selected = self.yaml_dropdown.get()
        if not selected or selected == "No files found": return
            
        yaml_path = os.path.join(settings.IN_DIR, selected)
        
        self.btn_start.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")
        self.btn_stop.configure(state="normal") 
        self.stop_event.clear() 
        
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Status: Initializing cores...", text_color="yellow")
        
        for item in self.tree.get_children(): self.tree.delete(item)
        for widget in self.wc_scroll.winfo_children(): widget.destroy()
        self.lbl_wc_empty = ctk.CTkLabel(self.wc_scroll, text="Simulating...", text_color="gray")
        self.lbl_wc_empty.pack(pady=50)
            
        threading.Thread(target=self.run_sim_thread, args=(yaml_path,), daemon=True).start()

    def stop_simulation(self):
        self.stop_event.set()
        self.lbl_status.configure(text="Status: Canceling simulation...", text_color="orange")
        self.btn_stop.configure(state="disabled")

    def run_sim_thread(self, yaml_path):
        try:
            stim = util.Stimuli(yaml_path)
            df = simulator.run_sim(stim, progress_callback=self.progress_callback_wrapper)
            
            csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
            df.to_csv(csv_out, index=False)
            
            try:
                history_dir = os.path.join(settings.OUT_DIR, "history")
                os.makedirs(history_dir, exist_ok=True)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                history_file = os.path.join(history_dir, f"run_{timestamp}.csv")
                df.to_csv(history_file, index=False)
            except Exception as e:
                print(f"Konnte Run nicht in Historie speichern: {e}")
                
            self.after(0, self.refresh_history)
            self.after(0, self.update_ui_results, df, stim, True)
            
        except InterruptedError as e:
            self.after(0, self.show_error, str(e))
        except Exception as e:
            self.after(0, self.show_error, str(e))

    def show_error(self, error_msg):
        self.lbl_status.configure(text="Status: Error / Aborted!", text_color="red")
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_refresh.configure(state="normal")
        
        for widget in self.wc_scroll.winfo_children(): widget.destroy()
        ctk.CTkLabel(self.wc_scroll, text=f"LOG:\n{error_msg}", text_color="red", justify="left").pack(anchor="w", padx=20, pady=20)

    def update_ui_results(self, df, stim, switch_tab=False):
        if 'sim_error' not in df.columns:
            df['sim_error'] = 'None'
        df['sim_error'] = df['sim_error'].fillna('None').astype(str)
        df.loc[df['sim_error'].str.lower() == 'nan', 'sim_error'] = 'None'
        
        self.current_df = df
        self.current_stim = stim
        
        total = len(df)
        crashes = len(df[df['sim_error'] != 'None'])
        valid_df = df[df['sim_error'] == 'None']
        
        tb_pass_cols = [c for c in df.columns if c.endswith('_overall_pass')]
        df['global_pass'] = True 
        for col in tb_pass_cols: df['global_pass'] = df['global_pass'] & df[col]
            
        global_passed = int(df['global_pass'].sum())
        global_yield = (global_passed / total) * 100 if total > 0 else 0
        
        self.lbl_total.configure(text=f"Iterations: {total}")
        self.lbl_crashes.configure(text=f"Crashes: {crashes}")
        
        yield_color = "#2ecc71" if global_yield == 100 else "#f1c40f" if global_yield > 0 else "#e74c3c"
        self.lbl_yield.configure(text=f"Global Yield: {global_yield:.1f}%", text_color=yield_color)
            
        def fmt(val):
            if pd.isna(val) or val is None: return "-"
            return f"{val:.4g}"

        failed_params = []
        meas_cols = [] 
        
        for item in self.tree.get_children(): self.tree.delete(item)

        for test in stim.tests:
            for val_obj in test.value_lst:
                p_name = val_obj.name
                if p_name in valid_df.columns:
                    meas_cols.append(p_name)
                    sim_min, sim_max, sim_typ = valid_df[p_name].min(), valid_df[p_name].max(), valid_df[p_name].mean()
                    
                    spec_min = fmt(getattr(val_obj, 'vmin', getattr(val_obj, 'min', None)))
                    spec_typ = fmt(getattr(val_obj, 'typ', getattr(val_obj, 'vtyp', None)))
                    spec_max = fmt(getattr(val_obj, 'vmax', getattr(val_obj, 'max', None)))
                    
                    pass_col = f"{p_name}_pass"
                    if pass_col in valid_df.columns and valid_df[pass_col].all():
                        status, tags = "PASS", ('pass',)
                    else:
                        status, tags = "FAIL", ('fail',)
                        failed_params.append((test, val_obj))
                        
                    self.tree.insert("", tk.END, values=(p_name, fmt(sim_min), fmt(sim_typ), fmt(sim_max), spec_min, spec_typ, spec_max, status), tags=tags)
                    
        if not meas_cols and total > 0:
             self.tree.insert("", tk.END, values=("No matching params", "-", "-", "-", "-", "-", "-", "WARN"), tags=('warn',))
                    
        numeric_cols = valid_df.select_dtypes(include=[np.number]).columns.tolist()
        all_plot_cols = [c for c in numeric_cols if not c.endswith('_pass')]
        
        sweep_params = [p for p in list(stim.params.keys()) if p in valid_df.columns and valid_df[p].nunique() > 1]
        self.group_by_dropdown.configure(values=["None"] + sweep_params)
        if self.group_by_var.get() not in ["None"] + sweep_params:
            self.group_by_var.set("None")
        
        if meas_cols:
            self.plot_param_dropdown.configure(values=meas_cols)
            if self.plot_param_var.get() not in meas_cols:
                self.plot_param_var.set(meas_cols[0])
            self.update_plot()
            
            self.tornado_target_dropdown.configure(values=meas_cols)
            if self.tornado_target_var.get() not in meas_cols:
                self.tornado_target_var.set(meas_cols[0])
            
        if all_plot_cols:
            self.scatter_x_dropdown.configure(values=all_plot_cols)
            self.scatter_y_dropdown.configure(values=all_plot_cols)
            if self.scatter_x_var.get() not in all_plot_cols:
                self.scatter_x_var.set(all_plot_cols[0])
            if self.scatter_y_var.get() not in all_plot_cols:
                self.scatter_y_var.set(all_plot_cols[1] if len(all_plot_cols) > 1 else all_plot_cols[0])
            
        self.update_adv_plots()
                    
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
            
        self.lbl_status.configure(text=f"Status: Ready", text_color="#2ecc71")
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_refresh.configure(state="normal")

    def update_plot(self, *args):
        if self.current_df is None or self.plot_param_var.get() == "-": return
            
        param = self.plot_param_var.get()
        dist_type = self.plot_dist_var.get()
        group_col = self.group_by_var.get()
        bins_val = self.bins_var.get()
        do_zoom = self.zoom_var.get()
        
        valid_df = self.current_df[self.current_df['sim_error'] == 'None']
        if param not in valid_df.columns: return

        self.ax.clear()
        self.ax.grid(True, linestyle='--', alpha=0.3)
        title_suffix = f" grouped by {group_col}" if group_col != "None" else ""
        self.ax.set_title(f"Distribution of: {param}{title_suffix}", color="white", pad=10)
        self.ax.set_xlabel("Simulated Value")
        self.ax.set_ylabel("Density")
        
        b = 'auto' if bins_val == "Auto" else int(bins_val)
        data_min = float('inf')
        data_max = float('-inf')
        
        if group_col != "None" and group_col in valid_df.columns:
            unique_vals = valid_df[group_col].unique()
            groups = [(f"{group_col}={val}", valid_df[valid_df[group_col] == val][param].dropna()) for val in unique_vals]
        else:
            groups = [("Current Run", valid_df[param].dropna())]
            
        colors = plt.cm.tab10(np.linspace(0, 1, max(10, len(groups))))
        
        for i, (grp_name, grp_data) in enumerate(groups):
            if grp_data.empty: continue
            
            if min(grp_data) < data_min: data_min = min(grp_data)
            if max(grp_data) > data_max: data_max = max(grp_data)
            
            c = '#3484F0' if group_col == "None" else colors[i % 10]
            
            label_text = grp_name
            fit_x = None
            fit_y = None
            
            if len(grp_data) > 1 and dist_type != "None":
                x_fit = np.linspace(min(grp_data), max(grp_data), 100)
                try:
                    if dist_type == "Gauss (Normal)":
                        mu, std = stats.norm.fit(grp_data)
                        fit_y = stats.norm.pdf(x_fit, mu, std)
                        fit_x = x_fit
                        label_text += f" (μ={mu:.3g}, σ={std:.3g})"
                    elif dist_type == "KDE (Smoothed)":
                        kde = stats.gaussian_kde(grp_data)
                        fit_y = kde(x_fit)
                        fit_x = x_fit
                    elif dist_type == "Uniform":
                        loc, scale = stats.uniform.fit(grp_data)
                        fit_y = stats.uniform.pdf(x_fit, loc, scale)
                        fit_x = x_fit
                    elif dist_type == "Log-Normal":
                        shape, loc, scale = stats.lognorm.fit(grp_data)
                        fit_y = stats.lognorm.pdf(x_fit, shape, loc, scale)
                        fit_x = x_fit
                        label_text += f" (s={shape:.2g}, loc={loc:.2g}, scale={scale:.2g})"
                    elif dist_type == "Exponential":
                        loc, scale = stats.expon.fit(grp_data)
                        fit_y = stats.expon.pdf(x_fit, loc, scale)
                        fit_x = x_fit
                        label_text += f" (loc={loc:.2g}, scale={scale:.2g})"
                    elif dist_type == "Chi-Squared":
                        df_stat, loc, scale = stats.chi2.fit(grp_data)
                        fit_y = stats.chi2.pdf(x_fit, df_stat, loc, scale)
                        fit_x = x_fit
                        label_text += f" (df={df_stat:.2g}, loc={loc:.2g}, scale={scale:.2g})"
                except Exception:
                    pass

            self.ax.hist(grp_data, bins=b, density=True, color=c, alpha=0.5, edgecolor='white', linewidth=0.5, label=label_text)
            
            if fit_x is not None and fit_y is not None:
                self.ax.plot(fit_x, fit_y, color=c, linewidth=2)
        
        # --- A/B Comparison Overlay ---
        comp_run = self.compare_var.get()
        if comp_run != "None" and comp_run != "-" and group_col == "None": 
            try:
                c_path = os.path.join(settings.OUT_DIR, "history", comp_run) if "run_" in comp_run else os.path.join(settings.OUT_DIR, "simulation_results.csv")
                c_df = pd.read_csv(c_path)
                
                if 'sim_error' not in c_df.columns: c_df['sim_error'] = 'None'
                c_df['sim_error'] = c_df['sim_error'].fillna('None').astype(str)
                c_df.loc[c_df['sim_error'].str.lower() == 'nan', 'sim_error'] = 'None'
                
                c_valid = c_df[c_df['sim_error'] == 'None']
                if param in c_valid.columns:
                    c_data = c_valid[param].dropna()
                    if not c_data.empty:
                        if min(c_data) < data_min: data_min = min(c_data)
                        if max(c_data) > data_max: data_max = max(c_data)
                        self.ax.hist(c_data, bins=b, density=True, color='#e67e22', alpha=0.5, edgecolor='#d35400', linewidth=0.5, label=f"Ref: {comp_run.replace('.csv', '')}")
            except Exception as e:
                print(f"Could not overlay comparison run: {e}")

        # Specs Overlay
        spec_min, spec_max = None, None
        if self.current_stim:
            for t in self.current_stim.tests:
                for v in t.value_lst:
                    if v.name == param:
                        spec_min = getattr(v, 'vmin', getattr(v, 'min', None))
                        spec_max = getattr(v, 'vmax', getattr(v, 'max', None))
                        
        if spec_min is not None:
            self.ax.axvline(spec_min, color='#e74c3c', linestyle='dashed', linewidth=2, label=f'Min Spec ({spec_min:.4g})')
        if spec_max is not None:
            self.ax.axvline(spec_max, color='#e74c3c', linestyle='dashed', linewidth=2, label=f'Max Spec ({spec_max:.4g})')

        # Zoom to fit logic
        if do_zoom and data_min != float('inf') and data_max != float('-inf'):
            padding = (data_max - data_min) * 0.05
            if padding == 0: padding = 0.1 
            self.ax.set_xlim(data_min - padding, data_max + padding)

        if len(self.ax.get_legend_handles_labels()[1]) > 0:
            self.ax.legend(loc='best', facecolor='#2b2b2b', edgecolor='gray')

        self.fig.tight_layout()
        self.canvas.draw()

def main():
    app = SimifyGUI()
    app.mainloop()

if __name__ == "__main__":
    main()