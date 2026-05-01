import customtkinter as ctk
from tkinter import ttk, messagebox
import tkinter as tk
import os
import glob
import threading
import pandas as pd

from simify import settings
from simify import simulator
from simify import util

# --- MODERN THEME SETUP ---
ctk.set_appearance_mode("dark")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

class SimifyGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("⚡ Simify EDA Dashboard")
        self.geometry("1100x750")
        
        # Grid Layout für die gesamte App
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.setup_left_panel()
        self.setup_right_panel()
        self.apply_treeview_dark_style()
        
    def setup_left_panel(self):
        self.left_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.left_frame.grid(row=0, column=0, sticky="nsew")
        self.left_frame.grid_rowconfigure(5, weight=1) # Spacer
        
        ctk.CTkLabel(self.left_frame, text="⚙️ Konfiguration", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        
        ctk.CTkLabel(self.left_frame, text="Wähle ein Datasheet:").grid(row=1, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.yaml_dropdown = ctk.CTkOptionMenu(self.left_frame, dynamic_resizing=False)
        self.yaml_dropdown.grid(row=2, column=0, padx=20, pady=(5, 20), sticky="ew")
        self.refresh_yamls()
        
        self.btn_refresh = ctk.CTkButton(self.left_frame, text="🔄 Liste aktualisieren", command=self.refresh_yamls, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"))
        self.btn_refresh.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")
        
        self.btn_start = ctk.CTkButton(self.left_frame, text="🚀 Simulation Starten", command=self.start_simulation)
        self.btn_start.grid(row=4, column=0, padx=20, pady=(20, 0), sticky="ew")
        
        # Fortschrittsbalken (Standardmäßig versteckt/leer)
        self.progress_bar = ctk.CTkProgressBar(self.left_frame)
        self.progress_bar.grid(row=6, column=0, padx=20, pady=(10, 0), sticky="ew")
        self.progress_bar.set(0)
        
        self.lbl_status = ctk.CTkLabel(self.left_frame, text="Status: Bereit", text_color="gray")
        self.lbl_status.grid(row=7, column=0, padx=20, pady=(5, 20), sticky="w")
        
    def setup_right_panel(self):
        self.right_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.right_frame.grid_columnconfigure(0, weight=1)
        self.right_frame.grid_rowconfigure(2, weight=1) # Tabelle bekommt den Hauptplatz
        
        ctk.CTkLabel(self.right_frame, text="📊 Auswertung", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, sticky="w", pady=(0, 15))
        
        # Metrics Cards
        self.metrics_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.metrics_frame.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        
        self.lbl_total = ctk.CTkLabel(self.metrics_frame, text="Iterationen: -", font=ctk.CTkFont(size=14))
        self.lbl_total.grid(row=0, column=0, padx=(0, 40))
        
        self.lbl_crashes = ctk.CTkLabel(self.metrics_frame, text="Crashes: -", font=ctk.CTkFont(size=14))
        self.lbl_crashes.grid(row=0, column=1, padx=(0, 40))
        
        self.lbl_yield = ctk.CTkLabel(self.metrics_frame, text="Global Yield: -", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_yield.grid(row=0, column=2)
        
        # Treeview Container (Standard Tkinter Treeview, aber dunkel gestylt)
        self.tree_frame = ctk.CTkFrame(self.right_frame)
        self.tree_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 20))
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
        ctk.CTkLabel(self.right_frame, text="❌ Worst-Case Analyse (Fails)", font=ctk.CTkFont(size=16, weight="bold")).grid(row=3, column=0, sticky="w", pady=(0, 5))
        self.worst_case_box = ctk.CTkTextbox(self.right_frame, height=150, font=ctk.CTkFont(family="Courier", size=12))
        self.worst_case_box.grid(row=4, column=0, sticky="ew")
        self.worst_case_box.insert("0.0", "Starte eine Simulation, um Ausreißer zu sehen...")
        self.worst_case_box.configure(state="disabled")

    def apply_treeview_dark_style(self):
        """Baut das hässliche Standard-Tkinter-Weiß in einen coolen Dark-Mode um"""
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", rowheight=25, fieldbackground="#2b2b2b", borderwidth=0)
        style.map('Treeview', background=[('selected', '#1f538d')])
        style.configure("Treeview.Heading", background="#565b5e", foreground="white", relief="flat")
        style.map("Treeview.Heading", background=[('active', '#3484F0')])
        
        # Dunkle Rot/Grün Farben für den Dark Mode
        self.tree.tag_configure('pass', background='#1a4d1a') # dunkles Grün
        self.tree.tag_configure('fail', background='#4d1a1a') # dunkles Rot

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
        """Wird aus dem Simulator-Thread aufgerufen"""
        # ui update sicher im haupt-thread ausführen
        self.after(0, self._set_progress_ui, current, total)
        
    def _set_progress_ui(self, current, total):
        progress = current / total
        self.progress_bar.set(progress)
        self.lbl_status.configure(text=f"Simuliere... {current}/{total}", text_color="#3484F0")

    def start_simulation(self):
        selected = self.yaml_dropdown.get()
        if not selected or selected == "Keine Dateien gefunden":
            messagebox.showwarning("Fehler", "Bitte wähle zuerst ein Datasheet aus!")
            return
            
        yaml_path = os.path.join(settings.IN_DIR, selected)
        
        # UI sperren
        self.btn_start.configure(state="disabled")
        self.btn_refresh.configure(state="disabled")
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Status: Initialisiere Kerne...", text_color="yellow")
        
        # Tabelle und Console leeren
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        self.worst_case_box.configure(state="normal")
        self.worst_case_box.delete("0.0", "end")
        self.worst_case_box.configure(state="disabled")
            
        threading.Thread(target=self.run_sim_thread, args=(yaml_path,), daemon=True).start()

    def run_sim_thread(self, yaml_path):
        try:
            stim = util.Stimuli(yaml_path)
            # Hier übergeben wir unsere update_progress Funktion als Callback an die Engine!
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
        total = len(df)
        crashes = len(df[df['sim_error'] != 'None'])
        
        tb_pass_cols = [c for c in df.columns if c.endswith('_overall_pass')]
        df['global_pass'] = True 
        for col in tb_pass_cols:
            df['global_pass'] = df['global_pass'] & df[col]
            
        global_passed = int(df['global_pass'].sum())
        global_yield = (global_passed / total) * 100
        
        self.lbl_total.configure(text=f"Iterationen: {total}")
        self.lbl_crashes.configure(text=f"Crashes: {crashes}")
        
        yield_color = "#2ecc71" if global_yield == 100 else "#f1c40f" if global_yield > 0 else "#e74c3c"
        self.lbl_yield.configure(text=f"Global Yield: {global_yield:.1f}%", text_color=yield_color)
            
        valid_df = df[df['sim_error'] == 'None']
        
        def fmt(val):
            if pd.isna(val) or val is None: return "-"
            return f"{val:.4g}"

        failed_params = []

        for test in stim.tests:
            for val_obj in test.value_lst:
                p_name = val_obj.name
                if p_name in valid_df.columns:
                    sim_min = valid_df[p_name].min()
                    sim_max = valid_df[p_name].max()
                    sim_typ = valid_df[p_name].mean()
                    
                    spec_min = fmt(val_obj.vmin)
                    spec_max = fmt(val_obj.vmax)
                    
                    pass_col = f"{p_name}_pass"
                    if pass_col in valid_df.columns and valid_df[pass_col].all():
                        status = "✅ PASS"
                        tags = ('pass',)
                    else:
                        status = "❌ FAIL"
                        tags = ('fail',)
                        failed_params.append((test, val_obj))
                        
                    self.tree.insert("", tk.END, values=(
                        p_name, fmt(sim_min), fmt(sim_typ), fmt(sim_max), 
                        spec_min, spec_max, status
                    ), tags=tags)
                    
        # --- WORST CASE ANALYSE IN DIE KONSOLE SCHREIBEN ---
        self.worst_case_box.configure(state="normal")
        if failed_params:
            param_cols = list(stim.params.keys())
            for test, val_obj in failed_params:
                p_name = val_obj.name
                pass_col = f"{p_name}_pass"
                
                failed_rows = valid_df[valid_df[pass_col] == False]
                if failed_rows.empty: continue
                    
                min_fail = failed_rows[p_name].min()
                max_fail = failed_rows[p_name].max()
                
                worst_val, worst_idx, violation = None, None, ""
                
                if val_obj.vmin is not None and min_fail < val_obj.vmin:
                    worst_val, worst_idx, violation = min_fail, failed_rows[p_name].idxmin(), f"< {fmt(val_obj.vmin)}"
                elif val_obj.vmax is not None and max_fail > val_obj.vmax:
                    worst_val, worst_idx, violation = max_fail, failed_rows[p_name].idxmax(), f"> {fmt(val_obj.vmax)}"
                    
                if worst_idx is not None:
                    worst_row = failed_rows.loc[worst_idx]
                    self.worst_case_box.insert("end", f"[FAIL] {p_name}: {fmt(worst_val)} (Spezi: {violation})\n")
                    for k in param_cols:
                        if k in worst_row:
                            self.worst_case_box.insert("end", f"       ├─ {k:<12} : {worst_row[k]}\n")
                    self.worst_case_box.insert("end", "\n")
        else:
            self.worst_case_box.insert("0.0", "✅ Alle Spezifikationen erfüllt! Keine Worst-Cases gefunden.")
            
        self.worst_case_box.configure(state="disabled")

        self.lbl_status.configure(text=f"Status: Fertig! Gespeichert in out/", text_color="#2ecc71")
        self.btn_start.configure(state="normal")
        self.btn_refresh.configure(state="normal")

def main():
    app = SimifyGUI()
    app.mainloop()

if __name__ == "__main__":
    main()