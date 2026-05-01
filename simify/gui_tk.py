import customtkinter as ctk
from tkinter import ttk, messagebox
import tkinter as tk
import os
import glob
import threading
import pandas as pd
import numpy as np

# --- PLOTTING MODULE ---
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import scipy.stats as stats

from simify import settings
from simify import simulator
from simify import util

ctk.set_appearance_mode("dark")  
ctk.set_default_color_theme("blue")  

class SimifyGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("⚡ Simify EDA Dashboard")
        self.geometry("1100x800")
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Daten-Speicher für interaktive Plots
        self.current_df = None
        self.current_stim = None
        
        self.setup_left_panel()
        self.setup_right_panel()
        self.apply_treeview_dark_style()
        
    def setup_left_panel(self):
        self.left_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.left_frame.grid(row=0, column=0, sticky="nsew")
        self.left_frame.grid_rowconfigure(5, weight=1) 
        
        ctk.CTkLabel(self.left_frame, text="⚙️ Konfiguration", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        
        ctk.CTkLabel(self.left_frame, text="Wähle ein Datasheet:").grid(row=1, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.yaml_dropdown = ctk.CTkOptionMenu(self.left_frame, dynamic_resizing=False)
        self.yaml_dropdown.grid(row=2, column=0, padx=20, pady=(5, 20), sticky="ew")
        self.refresh_yamls()
        
        self.btn_refresh = ctk.CTkButton(self.left_frame, text="🔄 Liste aktualisieren", command=self.refresh_yamls, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"))
        self.btn_refresh.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")
        
        self.btn_start = ctk.CTkButton(self.left_frame, text="🚀 Simulation Starten", command=self.start_simulation)
        self.btn_start.grid(row=4, column=0, padx=20, pady=(20, 0), sticky="ew")
        
        self.progress_bar = ctk.CTkProgressBar(self.left_frame)
        self.progress_bar.grid(row=6, column=0, padx=20, pady=(10, 0), sticky="ew")
        self.progress_bar.set(0)
        
        self.lbl_status = ctk.CTkLabel(self.left_frame, text="Status: Bereit", text_color="gray")
        self.lbl_status.grid(row=7, column=0, padx=20, pady=(5, 20), sticky="w")
        
    def setup_right_panel(self):
        self.right_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.right_frame.grid_columnconfigure(0, weight=1)
        self.right_frame.grid_rowconfigure(2, weight=1) 
        
        ctk.CTkLabel(self.right_frame, text="📊 Auswertung", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, sticky="w", pady=(0, 15))
        
        # --- GLOBAL METRICS (Immer sichtbar) ---
        self.metrics_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.metrics_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        
        self.lbl_total = ctk.CTkLabel(self.metrics_frame, text="Iterationen: -", font=ctk.CTkFont(size=14))
        self.lbl_total.grid(row=0, column=0, padx=(0, 40))
        
        self.lbl_crashes = ctk.CTkLabel(self.metrics_frame, text="Crashes: -", font=ctk.CTkFont(size=14))
        self.lbl_crashes.grid(row=0, column=1, padx=(0, 40))
        
        self.lbl_yield = ctk.CTkLabel(self.metrics_frame, text="Global Yield: -", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_yield.grid(row=0, column=2)
        
        # --- TABVIEW ---
        self.tabs = ctk.CTkTabview(self.right_frame)
        self.tabs.grid(row=2, column=0, sticky="nsew")
        
        self.tab_table = self.tabs.add("📋 Tabelle & Fails")
        self.tab_hist = self.tabs.add("📈 Histogramme & Streuung")
        
        self.setup_table_tab()
        self.setup_histogram_tab()

    def setup_table_tab(self):
        self.tab_table.grid_columnconfigure(0, weight=1)
        self.tab_table.grid_rowconfigure(0, weight=1)
        
        # Treeview (Tabelle)
        self.tree_frame = ctk.CTkFrame(self.tab_table, fg_color="transparent")
        self.tree_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        self.tree_frame.grid_columnconfigure(0, weight=1)
        self.tree_frame.grid_rowconfigure(0, weight=1)
        
        columns = ("param", "sim_min", "sim_typ", "sim_max", "spec_min", "spec_max", "status")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings")
        
        self.tree.heading("param", text="Parameter")
        self.tree.heading("sim_min", text="Sim Min")
        self.tree.heading("sim_typ", text="Sim Typ")
        self.tree.heading("sim_max", text="Sim Max")
        self.tree.heading("spec_min", text="Spec Min")
        self.tree.heading("spec_max", text="Spec Max")
        self.tree.heading("status", text="Status")
        
        for col in columns:
            self.tree.column(col, width=100, anchor=tk.CENTER)
        self.tree.column("param", width=150, anchor=tk.W)
        
        scrollbar = ttk.Scrollbar(self.tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        
        self.tree.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        scrollbar.grid(row=0, column=1, sticky="ns")
        
        # Worst Case Console
        ctk.CTkLabel(self.tab_table, text="❌ Worst-Case Analyse", font=ctk.CTkFont(size=14, weight="bold")).grid(row=1, column=0, sticky="w", pady=(0, 5))
        self.worst_case_box = ctk.CTkTextbox(self.tab_table, height=120, font=ctk.CTkFont(family="Courier", size=12))
        self.worst_case_box.grid(row=2, column=0, sticky="ew")
        self.worst_case_box.insert("0.0", "Starte eine Simulation, um Ausreißer zu sehen...")
        self.worst_case_box.configure(state="disabled")

    def setup_histogram_tab(self):
        self.tab_hist.grid_columnconfigure(0, weight=1)
        self.tab_hist.grid_rowconfigure(1, weight=1)
        
        # Control Bar für Plots
        control_frame = ctk.CTkFrame(self.tab_hist, fg_color="transparent")
        control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        ctk.CTkLabel(control_frame, text="Parameter:").pack(side=tk.LEFT, padx=(0, 10))
        self.plot_param_var = ctk.StringVar(value="-")
        self.plot_param_dropdown = ctk.CTkOptionMenu(control_frame, variable=self.plot_param_var, command=self.update_plot)
        self.plot_param_dropdown.pack(side=tk.LEFT, padx=(0, 30))
        
        ctk.CTkLabel(control_frame, text="Fit-Kurve:").pack(side=tk.LEFT, padx=(0, 10))
        self.plot_dist_var = ctk.StringVar(value="Gauss (Normal)")
        self.plot_dist_dropdown = ctk.CTkOptionMenu(
            control_frame, 
            variable=self.plot_dist_var, 
            values=["Gauss (Normal)", "KDE (Geglättet)", "Uniform", "Keine"],
            command=self.update_plot
        )
        self.plot_dist_dropdown.pack(side=tk.LEFT)

        # Matplotlib Figure einrichten (Dark Mode Style)
        plt.style.use('dark_background')
        self.fig, self.ax = plt.subplots(figsize=(6, 4))
        self.fig.patch.set_facecolor('#2b2b2b') # CTk Background
        self.ax.set_facecolor('#2b2b2b')
        self.ax.grid(True, linestyle='--', alpha=0.3)
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.tab_hist)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

    def apply_treeview_dark_style(self):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", rowheight=25, fieldbackground="#2b2b2b", borderwidth=0)
        style.map('Treeview', background=[('selected', '#1f538d')])
        style.configure("Treeview.Heading", background="#565b5e", foreground="white", relief="flat")
        style.map("Treeview.Heading", background=[('active', '#3484F0')])
        self.tree.tag_configure('pass', background='#1a4d1a') 
        self.tree.tag_configure('fail', background='#4d1a1a') 

    def refresh_yamls(self):
        yaml_files = glob.glob(os.path.join(settings.IN_DIR, "*.yaml"))
        yaml_names = [os.path.basename(f) for f in yaml_files]
        if yaml_names:
            self.yaml_dropdown.configure(values=yaml_names)
            self.yaml_dropdown.set(yaml_names[0])
        else:
            self.yaml_dropdown.configure(values=["Keine Dateien gefunden"])
            self.yaml_dropdown.set("Keine Dateien gefunden")
            
    def update_progress(self, current, total):
        self.after(0, self._set_progress_ui, current, total)
        
    def _set_progress_ui(self, current, total):
        progress = current / total
        self.progress_bar.set(progress)
        self.lbl_status.configure(text=f"Simuliere... {current}/{total}", text_color="#3484F0")

    def start_simulation(self):
        selected = self.yaml_dropdown.get()
        if not selected or selected == "Keine Dateien gefunden": return
            
        yaml_path = os.path.join(settings.IN_DIR, selected)
        
        self.btn_start.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Status: Initialisiere Kerne...", text_color="yellow")
        
        for item in self.tree.get_children(): self.tree.delete(item)
        self.worst_case_box.configure(state="normal")
        self.worst_case_box.delete("0.0", "end")
        self.worst_case_box.configure(state="disabled")
            
        threading.Thread(target=self.run_sim_thread, args=(yaml_path,), daemon=True).start()

    def run_sim_thread(self, yaml_path):
        try:
            stim = util.Stimuli(yaml_path)
            df = simulator.run_sim(stim, progress_callback=self.update_progress)
            csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
            df.to_csv(csv_out, index=False)
            self.after(0, self.update_ui_results, df, stim)
        except Exception as e:
            self.after(0, self.show_error, str(e))

    def show_error(self, error_msg):
        self.lbl_status.configure(text="Status: Fehler aufgetreten!", text_color="red")
        self.btn_start.configure(state="normal")
        self.btn_refresh.configure(state="normal")
        self.worst_case_box.configure(state="normal")
        self.worst_case_box.insert("0.0", f"CRASH LOG:\n{error_msg}")
        self.worst_case_box.configure(state="disabled")

    def update_ui_results(self, df, stim):
        # Daten global speichern für Plot-Updates
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
        
        self.lbl_total.configure(text=f"Iterationen: {total}")
        self.lbl_crashes.configure(text=f"Crashes: {crashes}")
        
        yield_color = "#2ecc71" if global_yield == 100 else "#f1c40f" if global_yield > 0 else "#e74c3c"
        self.lbl_yield.configure(text=f"Global Yield: {global_yield:.1f}%", text_color=yield_color)
            
        def fmt(val):
            if pd.isna(val) or val is None: return "-"
            return f"{val:.4g}"

        failed_params = []
        plot_params = []

        for test in stim.tests:
            for val_obj in test.value_lst:
                p_name = val_obj.name
                if p_name in valid_df.columns:
                    plot_params.append(p_name)
                    sim_min, sim_max, sim_typ = valid_df[p_name].min(), valid_df[p_name].max(), valid_df[p_name].mean()
                    spec_min, spec_max = fmt(val_obj.vmin), fmt(val_obj.vmax)
                    
                    pass_col = f"{p_name}_pass"
                    if pass_col in valid_df.columns and valid_df[pass_col].all():
                        status, tags = "✅ PASS", ('pass',)
                    else:
                        status, tags = "❌ FAIL", ('fail',)
                        failed_params.append((test, val_obj))
                        
                    self.tree.insert("", tk.END, values=(p_name, fmt(sim_min), fmt(sim_typ), fmt(sim_max), spec_min, spec_max, status), tags=tags)
                    
        # Update Plot Dropdown
        if plot_params:
            self.plot_param_dropdown.configure(values=plot_params)
            self.plot_param_var.set(plot_params[0])
            self.update_plot()
                    
        self.worst_case_box.configure(state="normal")
        if failed_params:
            param_cols = list(stim.params.keys())
            for test, val_obj in failed_params:
                p_name, pass_col = val_obj.name, f"{val_obj.name}_pass"
                failed_rows = valid_df[valid_df[pass_col] == False]
                if failed_rows.empty: continue
                    
                min_fail, max_fail = failed_rows[p_name].min(), failed_rows[p_name].max()
                worst_val, worst_idx, violation = None, None, ""
                
                if val_obj.vmin is not None and min_fail < val_obj.vmin:
                    worst_val, worst_idx, violation = min_fail, failed_rows[p_name].idxmin(), f"< {fmt(val_obj.vmin)}"
                elif val_obj.vmax is not None and max_fail > val_obj.vmax:
                    worst_val, worst_idx, violation = max_fail, failed_rows[p_name].idxmax(), f"> {fmt(val_obj.vmax)}"
                    
                if worst_idx is not None:
                    worst_row = failed_rows.loc[worst_idx]
                    self.worst_case_box.insert("end", f"[FAIL] {p_name}: {fmt(worst_val)} (Spezi: {violation})\n")
                    for k in param_cols:
                        if k in worst_row: self.worst_case_box.insert("end", f"       ├─ {k:<12} : {worst_row[k]}\n")
                    self.worst_case_box.insert("end", "\n")
        else:
            self.worst_case_box.insert("0.0", "✅ Alle Spezifikationen erfüllt! Keine Worst-Cases gefunden.")
            
        self.worst_case_box.configure(state="disabled")
        self.lbl_status.configure(text=f"Status: Fertig! Gespeichert in out/", text_color="#2ecc71")
        self.btn_start.configure(state="normal")
        self.btn_refresh.configure(state="normal")

    def update_plot(self, *args):
        """Zeichnet das Matplotlib-Histogramm basierend auf den Dropdown-Optionen neu"""
        if self.current_df is None or self.plot_param_var.get() == "-": return
            
        param = self.plot_param_var.get()
        dist_type = self.plot_dist_var.get()
        
        # Nur valide Runs betrachten
        valid_df = self.current_df[self.current_df['sim_error'] == 'None']
        if param not in valid_df.columns: return
            
        data = valid_df[param].dropna()
        if len(data) == 0: return

        self.ax.clear()
        self.ax.grid(True, linestyle='--', alpha=0.3)
        self.ax.set_title(f"Verteilung für: {param}", color="white", pad=10)
        self.ax.set_xlabel("Simulierter Wert")
        self.ax.set_ylabel("Dichte")
        
        # Plot Histogram
        # density=True normiert die Y-Achse, damit die Fit-Kurven passen
        count, bins, ignored = self.ax.hist(data, bins='auto', density=True, color='#3484F0', alpha=0.7, edgecolor='white', linewidth=0.5)
        
        # Hole Specs für diesen Parameter, um rote Linien einzuzeichnen
        spec_min, spec_max = None, None
        if self.current_stim:
            for t in self.current_stim.tests:
                for v in t.value_lst:
                    if v.name == param:
                        spec_min, spec_max = v.vmin, v.vmax
                        
        if spec_min is not None:
            self.ax.axvline(spec_min, color='#e74c3c', linestyle='dashed', linewidth=2, label=f'Min Spec ({spec_min:.4g})')
        if spec_max is not None:
            self.ax.axvline(spec_max, color='#e74c3c', linestyle='dashed', linewidth=2, label=f'Max Spec ({spec_max:.4g})')

        # Fit Distributions
        x = np.linspace(min(data), max(data), 100)
        if dist_type == "Gauss (Normal)":
            mu, std = stats.norm.fit(data)
            p = stats.norm.pdf(x, mu, std)
            self.ax.plot(x, p, '#2ecc71', linewidth=2, label=f'Gauss Fit ($\mu={mu:.4g}, \sigma={std:.4g}$)')
            
        elif dist_type == "KDE (Geglättet)":
            try:
                kde = stats.gaussian_kde(data)
                self.ax.plot(x, kde(x), '#9b59b6', linewidth=2, label='Kernel Density')
            except np.linalg.LinAlgError:
                pass # Falls Varianz zu klein für KDE
                
        elif dist_type == "Uniform":
            loc, scale = stats.uniform.fit(data)
            p = stats.uniform.pdf(x, loc, scale)
            self.ax.plot(x, p, '#f1c40f', linewidth=2, label='Uniform Fit')

        if len(self.ax.get_legend_handles_labels()[1]) > 0:
            self.ax.legend(loc='best', facecolor='#2b2b2b', edgecolor='gray')

        self.fig.tight_layout()
        self.canvas.draw()

def main():
    app = SimifyGUI()
    app.mainloop()

if __name__ == "__main__":
    main()