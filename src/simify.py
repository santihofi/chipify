import re
import subprocess
import numpy as np
import util
from tqdm import tqdm
import itertools
from jinja2 import Template
import pandas as pd

#define path variables

IN_DIR = "../in/"
OUT_DIR = "../out/"
WORK_DIR = "../tmp/"
TB_DIR = "../tb/"

def run_xschem(WORK_DIR, XSCHEM_FILE):
    print(f"[*] Generiere SPICE-Netzliste aus {XSCHEM_FILE}...")
    try:
        # Xschem im Batch-Modus aufrufen
        subprocess.run(
            ['xschem', '-n', '-s', '-q', '-x', '-o', WORK_DIR, XSCHEM_FILE],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=WORK_DIR
        )
        print("[+] Netzliste erfolgreich generiert.")
    except subprocess.CalledProcessError as e:
        print("[-] Fehler beim Ausführen von Xschem!")
        print("Fehlermeldung:\n", e.stderr)
        sys.exit(1)
        
def run_ngspice(netlist):
    try:
        process_result = subprocess.run(
            ["ngspice", "-b", "-q"],      # -b für Batch, - für stdin
            input=netlist,       # Dein Jinja-String
            text=True,                   # Wichtig: Behandle Input/Output als Text (nicht Bytes)
            capture_output=True,         # Fange die Ausgabe (stdout) ein
            check=True                   # Wirft einen Fehler, wenn ngspice abstürzt
        )
        
        # Die Ergebnisse von ngspice stehen jetzt als reiner Text zur Verfügung
        ngspice_output = process_result.stdout
        #print("Simulation erfolgreich! Hier ist der Output:")
        #print(ngspice_output)
        return ngspice_output

        # Hier müsstest du jetzt den String 'ngspice_output' mit Python parsen (z.B. per Regex)
        
    except subprocess.CalledProcessError as e:
        #print("Fehler bei der ngspice-Simulation:")
        #print(e.stderr)
        return e.stderr
        
def generate_templates(stim):
    
    for test in stim.tests:
    
        run_xschem(WORK_DIR, TB_DIR + test.tb_path + ".sch")
        
        with open(WORK_DIR + test.tb_path + ".spice") as f:
            test.template = Template(f.read())
        
def generate_case(stim):
    
    param_names = stim.params.keys()
    param_values = stim.params.values()

    param_sets = [
        dict(zip(param_names, combo)) 
        for combo in itertools.product(*param_values)
        ]
 
    return param_sets

def run_sim(stim):
    
    result = []
    
    param_sets = generate_case(stim)
    generate_templates(stim)
    
    for i, params in tqdm(enumerate(param_sets)):
        sample = params
        for test in stim.tests:
            rendering = test.template.render(**params)
            ngspice_output = run_ngspice(rendering)
            for line in ngspice_output.split('\n'):
                line = line.strip()
                
                if line.startswith("MY_DATA:"):
                    clean_line = line.replace("MY_DATA:", "").strip()
                    values = clean_line.split(' ')
                    for i in range(len(values)):
                        sample[test.value_lst[i].name] = float(values[i])
                    break
                
        result.append(sample)
        
    df = pd.DataFrame(result)
    df.to_csv("simulation_results.csv", index=False)

def main():
    
    stim = util.Stimuli()
    stim.addEnumParam("temp", [-40, 27, 100])
    stim.addEnumParam("corner_mos", ["tt_mismatch"])
    stim.addEnumParam("corner_res", ["res_typ_mismatch"])
    stim.addEnumParam("corner_cap", ["cap_typ_mismatch"])
    stim.addEnumParam("seed", range(2))
    stim.addEnumParam("sigma", [1])
    stim.addEnumParam("vcm", [0.75])
    stim.addEnumParam("vincm", [0.75])
    stim.addEnumParam("vdd", [1.5])

    stim.addTest(util.Test("tb_mult_cell_op", [util.Value("ve", 0.7, 0.8, 0.75), util.Value("vd", -0.02, 0.02, 0)]))
    stim.addTest(util.Test("tb_mult_cell_gain", [util.Value("gain", 5, 50, 10), util.Value("bandwidth", 1e7, 1e8, 1e9)]))
    stim.addTest(util.Test("tb_cm_feedback_loop", [util.Value("phase_margin", 20, 30, 60)]))
    
    run_sim(stim)

if __name__=="__main__":
    main()

