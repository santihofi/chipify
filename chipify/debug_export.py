"""debug_export.py – Export failing simulation runs for debugging.

Writes the failed runs of a results DataFrame to a CSV and generates a ready-to-run
SPICE deck for the worst-case failure, so it can be re-simulated in isolation.
"""
import os
import pandas as pd


def export_fails(df, stim, out_dir):
    """Write failed runs to ``failed_runs.csv`` and a worst-case SPICE deck in *out_dir*.

    Returns the number of failing runs found (0 if none / no ``global_pass`` column).
    """
    os.makedirs(out_dir, exist_ok=True)
    
    if 'global_pass' not in df.columns:
        return 0
        
    fails_df = df[df['global_pass'] == False]
    
    if fails_df.empty:
        return 0
        
    # 1. Alle Fails als kleine CSV wegspeichern
    csv_path = os.path.join(out_dir, "failed_runs.csv")
    fails_df.to_csv(csv_path, index=False)
    
    # 2. Eine fertige SPICE-Datei für den Allerschlimmsten Fail generieren
    spice_path = os.path.join(out_dir, "debug_worst_case.spice")
    with open(spice_path, 'w') as f:
        run_id = fails_df.index[0]
        f.write(f"* Auto-Generated Debug Params for worst failing run (ID: {run_id})\n")
        f.write("* Include this file in your Xschem testbench using a 'code' block!\n\n")
        
        row = fails_df.iloc[0]
        for p in stim.params.keys():
            if p in row:
                f.write(f".param {p}={row[p]}\n")
                
    return len(fails_df)