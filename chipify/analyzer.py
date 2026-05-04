# analyzer.py
import pandas as pd

def print_summary(df, stim):
    print("\n" + "="*85)
    print(" ZUSAMMENFASSUNG DER SIMULATIONSERGEBNISSE")
    print("="*85)
    
    total = len(df)
    print(f"Gesamte Iterationen:  {total}")
    
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
                    failed_params.append((test, val_obj)) 
                    
                row = f" {p_name:<12} | {fmt(sim_min):<10} | {fmt(sim_typ):<10} | {fmt(sim_max):<10} | {spec_min:<10} | {spec_max:<10} | {status}"
                print(row)
                
    # --- WORST-CASE ANALYSE (Überarbeitet) ---
    if failed_params:
        print("\n" + "-"*85)
        print(" WORST-CASE ANALYSE (Extremste Ausreißer der fehlgeschlagenen Parameter)")
        print("-" * 85)
        
        param_cols = list(stim.params.keys())
        
        for test, val_obj in failed_params:
            p_name = val_obj.name
            pass_col = f"{p_name}_pass"
            
            failed_rows = valid_df[valid_df[pass_col] == False]
            if failed_rows.empty:
                continue
                
            min_fail = failed_rows[p_name].min()
            max_fail = failed_rows[p_name].max()
            
            worst_val = None
            worst_idx = None
            violation = ""
            
            if val_obj.vmin is not None and min_fail < val_obj.vmin:
                worst_val = min_fail
                worst_idx = failed_rows[p_name].idxmin() 
                violation = f"< {fmt(val_obj.vmin)}"
            elif val_obj.vmax is not None and max_fail > val_obj.vmax:
                worst_val = max_fail
                worst_idx = failed_rows[p_name].idxmax() 
                violation = f"> {fmt(val_obj.vmax)}"
                
            if worst_idx is not None:
                worst_row = failed_rows.loc[worst_idx]
                
                print(f" [FAIL] {p_name}: {fmt(worst_val)} (Spezifikation: {violation})")
                print("        Verursachende Parameter:")
                
                # NEU: Saubere Tabellen/Baum-Ansicht für die Parameter
                for k in param_cols:
                    if k in worst_row:
                        print(f"          ├─ {k:<15} : {worst_row[k]}")
                print("") # Leerzeile als Trenner zum nächsten Worst-Case
                
    print("="*85 + "\n")