import customtkinter as ctk
from tkinter import ttk, messagebox
import tkinter as tk
import os
import glob
import threading
import pandas as pd
import numpy as np
import yaml

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
        self.title("Simify EDA Dashboard")
        self.geometry("1200x900")
        
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.current_df = None
        self.current_stim = None
        
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
        self.tabs.set("Datasheet Editor")
        
    def setup_left_panel(self):
        self.left_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.left_frame.grid(row=0, column=0, sticky="nsew")
        self.left_frame.grid_rowconfigure(5, weight=1) 
        
        ctk.CTkLabel(self.left_frame, text="Configuration", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        
        ctk.CTkLabel(self.left_frame, text="Current Datasheet:").grid(row=1, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.yaml_dropdown = ctk.CTkOptionMenu(self.left_frame, dynamic_resizing=False, command=self.on_yaml_select)
        self.yaml_dropdown.grid(row=2, column=0, padx=20, pady=(5, 20), sticky="ew")
        
        self.btn_refresh = ctk.CTkButton(self.left_frame, text="Refresh List", command=self.refresh_yamls, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"))
        self.btn_refresh.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")
        
        self.btn_start = ctk.CTkButton(self.left_frame, text="Start Simulation", command=self.start_simulation)
        self.btn_start.grid(row=4, column=0, padx=20, pady=(20, 0), sticky="ew")
        
        self.progress_bar = ctk.CTkProgressBar(self.left_frame)
        self.progress_bar.grid(row=6, column=0, padx=20, pady=(10, 0), sticky="ew")
        self.progress_bar.set(0)
        
        self.lbl_status = ctk.CTkLabel(self.left_frame, text="Status: Ready", text_color="gray")
        self.lbl_status.grid(row=7, column=0, padx=20, pady=(5, 20), sticky="w")
        
    def setup_right_panel(self):
        self.right_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.right_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.right_frame.grid_columnconfigure(0, weight=1)
        self.right_frame.grid_rowconfigure(2, weight=1) 
        
        ctk.CTkLabel(self.right_frame, text="Dashboard", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, sticky="w", pady=(0, 15))
        
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
                            if isinstance(v, dict):
                                tb_data.update(v)
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
        for widget in self.editor_scroll.winfo_children():
            widget.destroy()
            
        self.param_vars = []
        self.test_vars = []
        
        self.param_key, params_dict = self.get_params_dict()
        self.test_key, tests_dict = self.get_tests_dict()
        
        # --- 1. PARAMETER SECTION ---
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
            
            if not isinstance(p_val, list):
                val_str = self.gui_repr_param(p_val)
            else:
                val_str = ", ".join(self.gui_repr_param(x) for x in p_val)
                
            val_var = ctk.StringVar(value=val_str)
            
            ctk.CTkEntry(params_frame, textvariable=key_var, width=150).grid(row=r, column=0, padx=10, pady=5, sticky="w")
            ctk.CTkEntry(params_frame, textvariable=val_var).grid(row=r, column=1, padx=10, pady=5, sticky="ew")
            ctk.CTkButton(params_frame, text="🗑️", width=30, fg_color="#e74c3c", hover_color="#c0392b", command=lambda idx=r: self.action_del_param(idx)).grid(row=r, column=2, padx=10, pady=5)
            
            self.param_vars.append({'key': key_var, 'val': val_var})
            r += 1
            
        if r == 0:
            ctk.CTkLabel(params_frame, text="No parameters defined.", text_color="gray").grid(row=0, column=0, padx=10, pady=10)

        # --- 2. TESTS SECTION ---
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
                    try: 
                        parsed_list.append(float(x) if '.' in x else int(x))
                    except ValueError: 
                        parsed_list.append(x)
                        
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
    # REST OF GUI & ADVANCED ANALYTICS
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
        
        control_frame = ctk.CTkFrame(self.tab_hist, fg_color="transparent")
        control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        ctk.CTkLabel(control_frame, text="Measurement:").pack(side=tk.LEFT, padx=(0, 10))
        self.plot_param_var = ctk.StringVar(value="-")
        self.plot_param_dropdown = ctk.CTkOptionMenu(control_frame, variable=self.plot_param_var, command=self.update_plot)
        self.plot_param_dropdown.pack(side=tk.LEFT, padx=(0, 30))
        
        ctk.CTkLabel(control_frame, text="Fit Curve:").pack(side=tk.LEFT, padx=(0, 10))
        self.plot_dist_var = ctk.StringVar(value="Gauss (Normal)")
        self.plot_dist_dropdown = ctk.CTkOptionMenu(
            control_frame, 
            variable=self.plot_dist_var, 
            values=["Gauss (Normal)", "KDE (Smoothed)", "Uniform", "None"],
            command=self.update_plot
        )
        self.plot_dist_dropdown.pack(side=tk.LEFT)

        plt.style.use('dark_background')
        self.fig, self.ax = plt.subplots(figsize=(6, 4))
        self.fig.patch.set_facecolor('#2b2b2b') 
        self.ax.set_facecolor('#2b2b2b')
        self.ax.grid(True, linestyle='--', alpha=0.3)
        self.ax.spines['top'].set_visible(False)
        self.ax.spines['right'].set_visible(False)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.tab_hist)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")

    # --- ADVANCED ANALYTICS TAB ---
    def setup_adv_analytics_tab(self):
        self.tab_adv.grid_columnconfigure(0, weight=1)
        self.tab_adv.grid_rowconfigure(1, weight=1)
        
        control_frame = ctk.CTkFrame(self.tab_adv, fg_color="transparent")
        control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
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
        self.scatter_x_dropdown = ctk.CTkOptionMenu(self.adv_controls_frame, variable=self.scatter_x_var, command=self.update_adv_plots)
        self.lbl_y = ctk.CTkLabel(self.adv_controls_frame, text="Y-Axis:")
        self.scatter_y_dropdown = ctk.CTkOptionMenu(self.adv_controls_frame, variable=self.scatter_y_var, command=self.update_adv_plots)
        
        self.lbl_tornado = ctk.CTkLabel(self.adv_controls_frame, text="Target Measurement:")
        self.tornado_target_dropdown = ctk.CTkOptionMenu(self.adv_controls_frame, variable=self.tornado_target_var, command=self.update_adv_plots)

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
            
            if len(plot_cols) < 2:
                self.adv_ax.text(0.5, 0.5, "Not enough numeric data for correlation map.", 
                                 color='white', ha='center', va='center', transform=self.adv_ax.transAxes)
            else:
                corr = valid_df[plot_cols].corr()
                cax = self.adv_ax.matshow(corr, cmap='coolwarm', vmin=-1, vmax=1)
                
                cbar = self.adv_fig.colorbar(cax, ax=self.adv_ax, fraction=0.046, pad=0.04)
                cbar.ax.yaxis.set_tick_params(color='white')
                cbar.outline.set_edgecolor('gray')
                plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')

                self.adv_ax.set_xticks(range(len(plot_cols)))
                self.adv_ax.set_yticks(range(len(plot_cols)))
                self.adv_ax.set_xticklabels(plot_cols, rotation=45, ha='left', color='white', fontsize=9)
                self.adv_ax.set_yticklabels(plot_cols, color='white', fontsize=9)
                
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
            # Extract all pass/fail columns for individual measurements
            pass_cols = [c for c in valid_df.columns if c.endswith('_pass') and not c.endswith('_overall_pass') and c != 'global_pass']
            
            fail_counts = {}
            for c in pass_cols:
                # Count how many times this specific constraint failed (where value is False/0)
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
            explode = [0.1 if s == max(sizes) else 0 for s in sizes] # Highlight top offender
            
            patches, texts, autotexts = self.adv_ax.pie(
                sizes, 
                explode=explode, 
                labels=labels, 
                colors=colors, 
                autopct='%1.1f%%', 
                startangle=140,
                textprops={'color': 'white', 'fontsize': 10},
                wedgeprops={'edgecolor': 'gray', 'linewidth': 1}
            )
            
            for autotext in autotexts:
                autotext.set_color('black')
                autotext.set_weight('bold')
                
            self.adv_ax.set_title("Fail Breakdown: Which constraints caused the most failures?", color='white', pad=20)
            self.adv_ax.axis('equal') 

        self.adv_fig.tight_layout()
        self.adv_canvas.draw()
    # --------------------------------

    def apply_treeview_dark_style(self):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", rowheight=25, fieldbackground="#2b2b2b", borderwidth=0)
        style.map('Treeview', background=[('selected', '#1f538d')])
        style.configure("Treeview.Heading", background="#565b5e", foreground="white", relief="flat")
        style.map("Treeview.Heading", background=[('active', '#3484F0')])
        self.tree.tag_configure('pass', background='#1a4d1a') 
        self.tree.tag_configure('fail', background='#4d1a1a') 

    def update_progress(self, current, total):
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
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Status: Initializing cores...", text_color="yellow")
        
        for item in self.tree.get_children(): self.tree.delete(item)
        
        for widget in self.wc_scroll.winfo_children(): widget.destroy()
        self.lbl_wc_empty = ctk.CTkLabel(self.wc_scroll, text="Simulating...", text_color="gray")
        self.lbl_wc_empty.pack(pady=50)
            
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
        self.lbl_status.configure(text="Status: Error occurred!", text_color="red")
        self.btn_start.configure(state="normal")
        self.btn_refresh.configure(state="normal")
        
        for widget in self.wc_scroll.winfo_children(): widget.destroy()
        ctk.CTkLabel(self.wc_scroll, text=f"CRASH LOG:\n{error_msg}", text_color="red", justify="left").pack(anchor="w", padx=20, pady=20)

    def update_ui_results(self, df, stim):
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
                    
        numeric_cols = valid_df.select_dtypes(include=[np.number]).columns.tolist()
        all_plot_cols = [c for c in numeric_cols if not c.endswith('_pass')]
        
        if meas_cols:
            self.plot_param_dropdown.configure(values=meas_cols)
            self.plot_param_var.set(meas_cols[0])
            self.update_plot()
            
            self.tornado_target_dropdown.configure(values=meas_cols)
            self.tornado_target_var.set(meas_cols[0])
            
        if all_plot_cols:
            self.scatter_x_dropdown.configure(values=all_plot_cols)
            self.scatter_y_dropdown.configure(values=all_plot_cols)
            self.scatter_x_var.set(all_plot_cols[0])
            self.scatter_y_var.set(all_plot_cols[1] if len(all_plot_cols) > 1 else all_plot_cols[0])
            
        self.update_adv_plots()
                    
        for widget in self.wc_scroll.winfo_children(): widget.destroy()
            
        if not failed_params:
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

        self.tabs.set("Measurements") 
        self.lbl_status.configure(text=f"Status: Done! Saved to out/", text_color="#2ecc71")
        self.btn_start.configure(state="normal")
        self.btn_refresh.configure(state="normal")

    def update_plot(self, *args):
        if self.current_df is None or self.plot_param_var.get() == "-": return
            
        param = self.plot_param_var.get()
        dist_type = self.plot_dist_var.get()
        
        valid_df = self.current_df[self.current_df['sim_error'] == 'None']
        if param not in valid_df.columns: return
            
        data = valid_df[param].dropna()
        if len(data) == 0: return

        self.ax.clear()
        self.ax.grid(True, linestyle='--', alpha=0.3)
        self.ax.set_title(f"Distribution of: {param}", color="white", pad=10)
        self.ax.set_xlabel("Simulated Value")
        self.ax.set_ylabel("Density")
        
        count, bins, ignored = self.ax.hist(data, bins='auto', density=True, color='#3484F0', alpha=0.7, edgecolor='white', linewidth=0.5)
        
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

        x = np.linspace(min(data), max(data), 100)
        if dist_type == "Gauss (Normal)":
            mu, std = stats.norm.fit(data)
            p = stats.norm.pdf(x, mu, std)
            self.ax.plot(x, p, '#2ecc71', linewidth=2, label=f'Gauss Fit ($\\mu={mu:.4g}, \\sigma={std:.4g}$)')
            
        elif dist_type == "KDE (Smoothed)":
            try:
                kde = stats.gaussian_kde(data)
                self.ax.plot(x, kde(x), '#9b59b6', linewidth=2, label='Kernel Density')
            except np.linalg.LinAlgError:
                pass 
                
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