"""analyzer.py – Console summary of simulation results.

Prints a human-readable run summary (total iterations, failed runs, and
per-testbench / global yield) for a completed results DataFrame. Used by the
CLI after a sweep.
"""
import pandas as pd


def print_summary(df, stim):
    """Print a summary of *df* (yield, crashes, worst-case fails) to stdout."""
    print("\n" + "="*85)
    print(" SIMULATION RESULTS SUMMARY")
    print("="*85)

    # Work on a prepared copy — never mutate the caller's DataFrame.
    from chipify.gui.services import data_loader as _dl
    df = _dl.prepare_results(df)

    total = len(df)
    print(f"Total iterations:  {total}")
    if total == 0:
        print("No simulation results to analyse.")
        print("="*85 + "\n")
        return

    crashes = len(df[df['sim_error'] != 'None'])
    if crashes > 0:
        print(f"Failed runs:       {crashes} (crashes / timeouts / parse errors)")
    else:
        print("Failed runs:       0 (all simulator instances succeeded)")

    print("\n--- Yield per testbench ---")
    tb_pass_cols = [c for c in df.columns if c.endswith('_overall_pass')]

    for col in tb_pass_cols:
        tb_name = col.replace('_overall_pass', '')
        passed = int(df[col].sum())
        yield_pct = (passed / total) * 100
        print(f" {tb_name:<25}: {passed}/{total} passed ({yield_pct:.1f}%)")

    global_passed = int(df['global_pass'].sum())
    global_yield = (global_passed / total) * 100

    print("\n--- Global yield ---")
    status_tag = "[PASS]" if global_yield == 100.0 else "[WARN]" if global_yield > 0 else "[FAIL]"
    print(f" {status_tag} TOTAL YIELD:       {global_passed}/{total} ({global_yield:.1f}%)")

    print("\n" + "-"*85)
    print(" MEASUREMENT ANALYSIS (simulated values vs. specification)")
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

    # --- Worst-case analysis ---
    if failed_params:
        print("\n" + "-"*85)
        print(" WORST-CASE ANALYSIS (most extreme outliers of the failing parameters)")
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

            # A parameter can violate both bounds across different runs —
            # report the side with the larger absolute excess.
            candidates = []
            if val_obj.vmin is not None and min_fail < val_obj.vmin:
                candidates.append((
                    val_obj.vmin - min_fail, min_fail,
                    failed_rows[p_name].idxmin(), f"< {fmt(val_obj.vmin)}",
                ))
            if val_obj.vmax is not None and max_fail > val_obj.vmax:
                candidates.append((
                    max_fail - val_obj.vmax, max_fail,
                    failed_rows[p_name].idxmax(), f"> {fmt(val_obj.vmax)}",
                ))

            for _excess, worst_val, worst_idx, violation in sorted(
                    candidates, key=lambda c: c[0], reverse=True):
                worst_row = failed_rows.loc[worst_idx]

                print(f" [FAIL] {p_name}: {fmt(worst_val)} (specification: {violation})")
                print("        Triggering parameters:")
                for k in param_cols:
                    if k in worst_row:
                        print(f"          ├─ {k:<15} : {worst_row[k]}")
                print("")  # blank line between worst cases

    print("="*85 + "\n")
