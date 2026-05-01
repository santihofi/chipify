import os
import sys
import glob
import shutil
import itertools
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse

import pandas as pd
import numpy as np
from tqdm import tqdm
from jinja2 import Template

import util

# --- PATH CONFIGURATION ---
IN_DIR = "../in/"
OUT_DIR = "../out/"
WORK_DIR = "../tmp/"
TB_DIR = "../tb/"

# Fast RAM drive for Docker I/O bypass
FAST_TMP = "/tmp/sim_work/"

# Ensure required output directories exist
os.makedirs(FAST_TMP, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)


def stage_files_to_ram():
    """Copies all PDK library files to the fast Linux RAM drive."""
    print("[*] Kopiere Bibliotheken in den Linux-RAM (/tmp/sim_work/)...")
    search_patterns = ["*.lib", "*.mod", "*.inc"]
    
    for pattern in search_patterns:
        for file_path in glob.glob(os.path.join(WORK_DIR, pattern)):
            filename = os.path.basename(file_path)
            dest_path = os.path.join(FAST_TMP, filename)
            
            if not os.path.exists(dest_path):
                try:
                    shutil.copy2(file_path, dest_path)
                except Exception as e:
                    print(f"[-] Warnung: Konnte {filename} nicht kopieren: {e}")

def run_xschem(xschem_file):
    """Generates the SPICE netlist from the Xschem schematic."""
    print(f"[*] Generiere SPICE-Netzliste aus {xschem_file}...")
    try:
        subprocess.run(
            ['xschem', '-n', '-s', '-q', '-x', '-o', FAST_TMP, xschem_file],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=WORK_DIR 
        )
    except subprocess.CalledProcessError as e:
        print("[-] Fehler beim Ausführen von Xschem!")
        print("Fehlermeldung:\n", e.stderr)
        sys.exit(1)

def run_ngspice(netlist, timeout_sec=10):
    """Runs a single Ngspice simulation on exactly 1 CPU core."""
    # Force Ngspice to run on a single thread, bypassing .spiceinit limits
    if ".control" in netlist:
        netlist = netlist.replace(".control", ".control\nset num_threads=1\n")
    else:
        netlist += "\n.control\nset num_threads=1\n.endc\n"

    custom_env = os.environ.copy()
    custom_env["OMP_NUM_THREADS"] = "1"
    
    pid = os.getpid()
    temp_spice_file = os.path.join(FAST_TMP, f"sim_{pid}.spice")
    temp_log_file = os.path.join(FAST_TMP, f"sim_{pid}.log")
    
    with open(temp_spice_file, 'w') as f:
        f.write(netlist)
        
    try:
        with open(temp_log_file, 'w') as log_file:
            subprocess.run(
                ["ngspice", "-b", "-r", os.devnull, temp_spice_file], 
                stdout=log_file,          
                stderr=subprocess.STDOUT, 
                text=True,
                check=True,
                timeout=timeout_sec,
                cwd=FAST_TMP,
                env=custom_env
            )
            
        output_line = ""
        with open(temp_log_file, 'r') as log_file:
            for line in log_file:
                if line.startswith("MY_DATA:"):
                    output_line = line.strip()
                    break 
                    
        return output_line, None
        
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT"
    except subprocess.CalledProcessError:
        err_msg = "CRASH"
        if os.path.exists(temp_log_file):
            with open(temp_log_file, 'r') as f:
                err_msg = "".join(f.readlines()[-5:]).strip()
        return None, f"CRASH: {err_msg}"

def simulate_single_case(args):
    """Worker function for multiprocessing."""
    params, tests = args
    sample = params.copy()
    sample['sim_error'] = "None"
    
    for test in tests:
        rendering = Template(test.template_str).render(**params)
        ngspice_output, error_msg = run_ngspice(rendering)
        
        # Error handling
        if error_msg:
            sample['sim_error'] = f"{test.tb_path}: {error_msg}"
            sample[f"{test.tb_path}_overall_pass"] = False
            for val_obj in test.value_lst:
                sample[val_obj.name] = float('nan')
                sample[f"{val_obj.name}_pass"] = False
            continue 
            
        # Success handling & parsing
        if ngspice_output and ngspice_output.startswith("MY_DATA:"):
            clean_line = ngspice_output.replace("MY_DATA:", "").strip()
            values = clean_line.split(' ')
            
            all_passed = True
            for i, val_str in enumerate(values):
                val_float = float(val_str)
                val_obj = test.value_lst[i]
                
                sample[val_obj.name] = val_float
                sample[f"{val_obj.name}_pass"] = val_obj.isPass(val_float)
                
                if not val_obj.isPass(val_float):
                    all_passed = False
                    
            sample[f"{test.tb_path}_overall_pass"] = all_passed
        else:
             sample['sim_error'] = f"{test.tb_path}: NO_MY_DATA_FOUND"
             sample[f"{test.tb_path}_overall_pass"] = False

    return sample

def generate_templates(stim):
    """Generates all required base netlists using Xschem."""
    for test in stim.tests:
        tb_path = os.path.join(TB_DIR, test.tb_path + ".sch")
        run_xschem(tb_path)
        
        spice_file = os.path.join(FAST_TMP, test.tb_path + ".spice")
        with open(spice_file, "r") as f:
            test.template_str = f.read()

def generate_cases(stim):
    """Creates a list of dictionaries containing all parameter permutations."""
    param_names = stim.params.keys()
    param_values = stim.params.values()
    return [dict(zip(param_names, combo)) for combo in itertools.product(*param_values)]

def run_sim(stim):
    """Main simulation loop orchestrating multiprocessing."""
    param_sets = generate_cases(stim)
    generate_templates(stim)
    stage_files_to_ram()
    
    worker_args = [(params, stim.tests) for params in param_sets]
    results = []
    
    try:
        available_cores = len(os.sched_getaffinity(0))
    except AttributeError:
        available_cores = os.cpu_count()
        
    num_cores = max(1, available_cores - 1)
    print(f"[*] Starte Multiprocessing mit {num_cores} ECHTEN Kernen für {len(param_sets)} Iterationen...")
    
    with ProcessPoolExecutor(max_workers=num_cores) as executor:
        futures = [executor.submit(simulate_single_case, arg) for arg in worker_args]
        
        for future in tqdm(as_completed(futures), total=len(param_sets)):
            results.append(future.result())
            
    df = pd.DataFrame(results)
    csv_out = os.path.join(OUT_DIR, "simulation_results.csv")
    df.to_csv(csv_out, index=False)
    print(f"[+] Fertig! Ergebnisse in {csv_out} gespeichert.")
    
    # NEU: Das stim-Objekt mit übergeben!
    print_summary(df, stim)
    
def print_summary(df, stim):
    print("\n" + "="*85)
    print(" ZUSAMMENFASSUNG DER SIMULATIONSERGEBNISSE")
    print("="*85)
    
    total = len(df)
    print(f"Gesamte Iterationen:  {total}")
    
    # 1. Check auf generelle Ngspice-Crashes
    crashes = len(df[df['sim_error'] != 'None'])
    if crashes > 0:
        print(f"Fehlgeschlagene Runs: {crashes} (Crashes / Timeouts / Parse-Errors)")
    else:
        print("Fehlgeschlagene Runs: 0 (Alle Ngspice-Instanzen erfolgreich)")
        
    print("\n--- Yield pro Testbench ---")
    tb_pass_cols = [c for c in df.columns if c.endswith('_overall_pass')]
    df['global_pass'] = True 
    
    for col in tb_pass_cols:
        tb_name = col.replace('_overall_pass', '')
        passed = int(df[col].sum())
        yield_pct = (passed / total) * 100
        print(f" {tb_name:<25}: {passed}/{total} bestanden ({yield_pct:.1f}%)")
        df['global_pass'] = df['global_pass'] & df[col]
        
    global_passed = int(df['global_pass'].sum())
    global_yield = (global_passed / total) * 100
    
    print("\n--- Globaler Yield ---")
    status_tag = "[PASS]" if global_yield == 100.0 else "[WARN]" if global_yield > 0 else "[FAIL]"
    print(f" {status_tag} TOTAL YIELD:       {global_passed}/{total} ({global_yield:.1f}%)")
    
    print("\n" + "-"*85)
    print(" MESSWERT-ANALYSE (Simulierte Werte vs. Spezifikation)")
    print("-" * 85)
    
    header = f" {'Parameter':<12} | {'Sim Min':<10} | {'Sim Typ':<10} | {'Sim Max':<10} | {'Spec Min':<10} | {'Spec Max':<10} | {'Status'}"
    print(header)
    print("-" * 85)
    
    valid_df = df[df['sim_error'] == 'None']
    
    def fmt(val):
        if pd.isna(val) or val is None: return "-"
        return f"{val:.4g}"
    
    # Liste für die Worst-Case Analyse speichern
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
                    status = "[PASS]"
                else:
                    status = "[FAIL]"
                    failed_params.append((test, val_obj)) # Für Worst-Case vormerken
                    
                row = f" {p_name:<12} | {fmt(sim_min):<10} | {fmt(sim_typ):<10} | {fmt(sim_max):<10} | {spec_min:<10} | {spec_max:<10} | {status}"
                print(row)
                
    # --- WORST-CASE ANALYSE ---
    if failed_params:
        print("\n" + "-"*85)
        print(" WORST-CASE ANALYSE (Extremste Ausreißer der fehlgeschlagenen Parameter)")
        print("-" * 85)
        
        # Alle Eingabeparameter (Corners, Temp, Seed etc.) auslesen
        param_cols = list(stim.params.keys())
        
        for test, val_obj in failed_params:
            p_name = val_obj.name
            pass_col = f"{p_name}_pass"
            
            # Nur die Zeilen betrachten, bei denen dieser Parameter durchgefallen ist
            failed_rows = valid_df[valid_df[pass_col] == False]
            
            if failed_rows.empty:
                continue
                
            min_fail = failed_rows[p_name].min()
            max_fail = failed_rows[p_name].max()
            
            worst_val = None
            worst_idx = None
            violation = ""
            
            # Prüfen, ob der Worst-Case nach unten (Min) oder nach oben (Max) ausgebrochen ist
            if val_obj.vmin is not None and min_fail < val_obj.vmin:
                worst_val = min_fail
                worst_idx = failed_rows[p_name].idxmin() # Zeilennummer des extremsten Minimums
                violation = f"< {fmt(val_obj.vmin)}"
            elif val_obj.vmax is not None and max_fail > val_obj.vmax:
                worst_val = max_fail
                worst_idx = failed_rows[p_name].idxmax() # Zeilennummer des extremsten Maximums
                violation = f"> {fmt(val_obj.vmax)}"
                
            if worst_idx is not None:
                worst_row = failed_rows.loc[worst_idx]
                
                # Parameter-String zusammenbauen (z.B. "temp=100, corner_mos=tt, seed=42")
                params_str = ", ".join([f"{k}={worst_row[k]}" for k in param_cols if k in worst_row])
                
                print(f" [FAIL] {p_name}: {fmt(worst_val)} (Spezifikation: {violation})")
                print(f"        -> Verursacht durch: {params_str}\n")
                
    print("="*85 + "\n")

def main():
    # 1. Den Parser initialisieren
    parser = argparse.ArgumentParser(
        description="Simify: High-Performance Mismatch Simulation Wrapper für Xschem und Ngspice.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # 2. Kommandozeilen-Argumente definieren
    parser.add_argument(
        "-c", "--config", 
        type=str, 
        default="datasheet.yaml", 
        help="Name der YAML-Konfigurationsdatei.\n(Wird automatisch im Ordner '../in/' gesucht).\nStandard: datasheet.yaml"
    )
    
    # 3. Argumente auslesen
    args = parser.parse_args()
    
    # 4. Pfad zusammenbauen und validieren
    yaml_path = os.path.join(IN_DIR, args.config)
    
    if not os.path.exists(yaml_path):
        print(f"[-] Fatal Error: Die Konfigurationsdatei '{yaml_path}' wurde nicht gefunden!")
        sys.exit(1)
        
    print(f"[*] Initialisiere Simify...")
    print(f"[*] Lade Konfiguration: {args.config}")
    
    # 5. Simulation starten
    stim = util.Stimuli(yaml_path)
    run_sim(stim)

if __name__ == "__main__":
    main()
