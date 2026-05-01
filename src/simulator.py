# simulator.py
import os
import sys
import glob
import shutil
import itertools
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
from tqdm import tqdm
from jinja2 import Template

import settings

def stage_files_to_ram():
    print(f"[*] Kopiere Bibliotheken in den Linux-RAM ({settings.FAST_TMP})...")
    search_patterns = ["*.lib", "*.mod", "*.inc"]
    
    for pattern in search_patterns:
        for file_path in glob.glob(os.path.join(settings.WORK_DIR, pattern)):
            filename = os.path.basename(file_path)
            dest_path = os.path.join(settings.FAST_TMP, filename)
            
            if not os.path.exists(dest_path):
                try:
                    shutil.copy2(file_path, dest_path)
                except Exception as e:
                    print(f"[-] Warnung: Konnte {filename} nicht kopieren: {e}")

def run_xschem(xschem_file):
    print(f"[*] Generiere SPICE-Netzliste aus {xschem_file}...")
    try:
        subprocess.run(
            ['xschem', '-n', '-s', '-q', '-x', '-o', settings.FAST_TMP, xschem_file],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=settings.WORK_DIR 
        )
    except subprocess.CalledProcessError as e:
        print("[-] Fehler beim Ausführen von Xschem!")
        print("Fehlermeldung:\n", e.stderr)
        sys.exit(1)

def run_ngspice(netlist, timeout_sec=10):
    if ".control" in netlist:
        netlist = netlist.replace(".control", ".control\nset num_threads=1\n")
    else:
        netlist += "\n.control\nset num_threads=1\n.endc\n"

    custom_env = os.environ.copy()
    custom_env["OMP_NUM_THREADS"] = "1"
    
    pid = os.getpid()
    temp_spice_file = os.path.join(settings.FAST_TMP, f"sim_{pid}.spice")
    temp_log_file = os.path.join(settings.FAST_TMP, f"sim_{pid}.log")
    
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
                cwd=settings.FAST_TMP,
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
    params, tests = args
    sample = params.copy()
    sample['sim_error'] = "None"
    
    for test in tests:
        rendering = Template(test.template_str).render(**params)
        ngspice_output, error_msg = run_ngspice(rendering)
        
        if error_msg:
            sample['sim_error'] = f"{test.tb_path}: {error_msg}"
            sample[f"{test.tb_path}_overall_pass"] = False
            for val_obj in test.value_lst:
                sample[val_obj.name] = float('nan')
                sample[f"{val_obj.name}_pass"] = False
            continue 
            
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
    for test in stim.tests:
        tb_path = os.path.join(settings.TB_DIR, test.tb_path + ".sch")
        run_xschem(tb_path)
        
        spice_file = os.path.join(settings.FAST_TMP, test.tb_path + ".spice")
        with open(spice_file, "r") as f:
            test.template_str = f.read()

def generate_cases(stim):
    param_names = stim.params.keys()
    param_values = stim.params.values()
    return [dict(zip(param_names, combo)) for combo in itertools.product(*param_values)]

def run_sim(stim):
    """Executes the simulations and returns a Pandas DataFrame with the results."""
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
    return df