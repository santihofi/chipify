# Copyright (c) 2026 Santiago Hofwimmer
"""analyzer.py – Console summary of simulation results.

Prints a human-readable run summary (total iterations, failed runs, and
per-testbench / global yield) for a completed results DataFrame. Used by the
CLI after a sweep.
"""
from chipify.uikit.services import measurements as _meas


def print_summary(df, stim):
    """Print a summary of *df* (yield, crashes, worst-case fails) to stdout."""
    print("\n" + "="*85)
    print(" SIMULATION RESULTS SUMMARY")
    print("="*85)

    # Work on a prepared copy — never mutate the caller's DataFrame.
    from chipify import data_loader as _dl
    df = _dl.prepare_results(df)
    summary = _dl.result_summary(df)

    total = summary.total
    print(f"Total iterations:  {total}")
    if total == 0:
        print("No simulation results to analyse.")
        print("="*85 + "\n")
        return

    crashes = summary.crashes
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

    global_passed = summary.passed
    global_yield = summary.yield_pct

    print("\n--- Global yield ---")
    status_tag = "[PASS]" if global_yield == 100.0 else "[WARN]" if global_yield > 0 else "[FAIL]"
    print(f" {status_tag} TOTAL YIELD:       {global_passed}/{total} ({global_yield:.1f}%)")

    print("\n" + "-"*85)
    print(" MEASUREMENT ANALYSIS (simulated values vs. specification)")
    print("-" * 85)

    header = (f" {'Parameter':<12} | {'Sim Min':<10} | {'Sim Typ':<10} | "
              f"{'Sim Max':<10} | {'Spec Min':<10} | {'Spec Max':<10} | {'Status'}")
    print(header)
    print("-" * 85)

    def fmt(val):
        return _meas.fmt_value(val)

    # One shared implementation of the row statistics (the GUI, the Markdown
    # and the PDF reports read the same helper), so the four surfaces can no
    # longer disagree about whether a run passed.
    rows = _meas.measurement_rows(df, stim)

    for r in rows:
        status = f"[{r.status}]"
        print(f" {r.name:<12} | {fmt(r.sim_min):<10} | {fmt(r.sim_typ):<10} | "
              f"{fmt(r.sim_max):<10} | {fmt(r.spec_min):<10} | "
              f"{fmt(r.spec_max):<10} | {status}")

    # --- Worst-case analysis ---
    worst = _meas.worst_cases(df, stim, total)
    if worst:
        print("\n" + "-"*85)
        print(" WORST-CASE ANALYSIS (most extreme outliers of the failing parameters)")
        print("-" * 85)
        for w in worst:
            print(f" [FAIL] {w.name}: {fmt(w.worst_val)} "
                  f"(specification: {w.violation})")
            print("        Triggering parameters:")
            for key, val in w.conditions.items():
                print(f"          |- {key:<15} : {val}")
            print("")

    # --- Simulation errors ---
    # Without this block a broken testbench was invisible here: its rows were
    # filtered out before the table was built, so it contributed nothing at all.
    errors = _meas.error_rows(df, stim)
    if errors:
        print("\n" + "-"*85)
        print(" SIMULATION ERRORS (measurements that could not be taken)")
        print("-" * 85)
        for e in errors:
            print(f" [{e.kind}] {e.tb_path}: {e.run_n}/{e.total_n} run(s)")
            print(f"        {e.message}")
            if e.conditions:
                conds = ", ".join(f"{k}={v}" for k, v in e.conditions.items())
                print(f"        first seen at: {conds}")
            if e.measurements:
                print(f"        affects: {', '.join(e.measurements)}")
            print("")

    print("="*85 + "\n")
