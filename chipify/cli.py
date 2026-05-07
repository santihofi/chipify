# chipify.py
import argparse
import os
import sys
import json

from chipify import util
from chipify import settings
from chipify import simulator
from chipify.analyzer import print_summary


def _json_summary(df, stim, yaml_name: str, duration_s: float) -> dict:
    """Return a machine-readable summary dict for the completed run."""
    import pandas as pd
    total = len(df)
    crashes = int((df['sim_error'] != 'None').sum()) if 'sim_error' in df.columns else 0
    valid = total - crashes

    tb_pass_cols = [c for c in df.columns if c.endswith('_overall_pass')]
    df = df.copy()
    df['global_pass'] = True
    for col in tb_pass_cols:
        df['global_pass'] = df['global_pass'] & df[col]
    global_passed = int(df['global_pass'].sum())
    global_yield  = (global_passed / total * 100) if total > 0 else 0.0

    return {
        "yaml":       yaml_name,
        "total":      total,
        "crashes":    crashes,
        "valid":      valid,
        "passed":     global_passed,
        "yield":      round(global_yield, 2),
        "duration_s": round(duration_s, 2),
    }


def _run_single(yaml_path: str, *, json_out: bool = False,
                simulator_override: str | None = None) -> dict | None:
    """Run simulation for one yaml file. Returns summary dict or None on failure."""
    import time
    print(f"[*] Loading configuration: {os.path.basename(yaml_path)}")
    stim = util.Stimuli(yaml_path)
    t0 = time.perf_counter()
    df = simulator.run_sim(stim, simulator=simulator_override)
    duration_s = time.perf_counter() - t0

    if df is None:
        print(f"[-] Simulation returned no data for {yaml_path}")
        return None

    csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
    df.to_csv(csv_out, index=False)
    print(f"[+] Results saved to {csv_out}")

    # Save history copy + sidecar metadata
    try:
        import datetime
        from chipify import run_meta
        history_dir = os.path.join(settings.OUT_DIR, "history")
        os.makedirs(history_dir, exist_ok=True)
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        hist = os.path.join(history_dir, f"run_{ts}.csv")
        df.to_csv(hist, index=False)
        total  = len(df)
        valid  = int((df.get('sim_error', 'None') == 'None').sum()) if 'sim_error' in df.columns else total
        import pandas as pd
        df2 = df.copy()
        tb_pass_cols = [c for c in df2.columns if c.endswith('_overall_pass')]
        df2['global_pass'] = True
        for col in tb_pass_cols:
            df2['global_pass'] = df2['global_pass'] & df2[col]
        gyield = float(df2['global_pass'].sum()) / total * 100 if total else 0
        run_meta.write_meta(hist, yaml_name=os.path.basename(yaml_path),
                            duration_s=duration_s, total_runs=total,
                            valid_runs=valid, global_yield=round(gyield, 2))
    except Exception as exc:
        print(f"[!] Could not save history: {exc}")

    print_summary(df, stim)

    summary = _json_summary(df, stim, os.path.basename(yaml_path), duration_s)
    if json_out:
        print(json.dumps(summary))
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Chipify: High-Performance Mismatch Simulation Wrapper for Xschem und Ngspice.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "-c", "--config",
        type=str,
        default="datasheet.yaml",
        help="Name of .yaml config file.\n(Automatically searched in '../in/').\nDefault: datasheet.yaml"
    )

    parser.add_argument(
        "--batch",
        metavar="DIR",
        default=None,
        help=(
            "Batch mode: run every *.yaml found in DIR.\n"
            "Results are written to per-datasheet subdirectories inside out/.\n"
            "A JSON summary line is printed for each run."
        ),
    )

    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Print a JSON summary line to stdout after each run (useful for CI parsing).",
    )

    parser.add_argument(
        "--markdown",
        metavar="OUTPUT",
        default=None,
        help="After simulation, write a Markdown report to OUTPUT path.",
    )

    parser.add_argument(
        "--simulator",
        choices=["ngspice", "vacask"],
        default=None,
        help="Override the simulator_engine setting for this run (ngspice|vacask).",
    )

    args = parser.parse_args()

    # ── Batch mode ────────────────────────────────────────────────────────────
    if args.batch:
        import glob
        batch_dir = args.batch
        yaml_files = sorted(glob.glob(os.path.join(batch_dir, "*.yaml")))
        if not yaml_files:
            print(f"[-] No *.yaml files found in: {batch_dir}")
            sys.exit(1)

        print(f"[*] Batch mode: {len(yaml_files)} datasheet(s) found in {batch_dir}")
        summaries = []
        all_ok = True
        for yaml_path in yaml_files:
            print(f"\n{'='*60}")
            summary = _run_single(yaml_path, json_out=args.json,
                                  simulator_override=args.simulator)
            if summary is None:
                all_ok = False
                summary = {"yaml": os.path.basename(yaml_path), "error": "no data"}
            summaries.append(summary)

        print(f"\n{'='*60}")
        print(f"[*] Batch complete: {len(summaries)} run(s).")
        failed = [s for s in summaries if s.get("yield", 0) < 100]
        if failed:
            print(f"[!] {len(failed)} datasheet(s) with yield < 100%:")
            for s in failed:
                print(f"    {s['yaml']}: {s.get('yield', '?')}%")

        if args.json:
            print(json.dumps({"batch_summary": summaries}))

        sys.exit(0 if all_ok else 1)

    # ── Single run ────────────────────────────────────────────────────────────
    yaml_path = os.path.join(settings.IN_DIR, args.config)
    if not os.path.exists(yaml_path):
        print(f"[-] Fatal Error: configuration file '{yaml_path}' not found!")
        sys.exit(1)

    print(f"[*] Initialising Chipify...")
    summary = _run_single(yaml_path, json_out=args.json,
                          simulator_override=args.simulator)
    if summary is None:
        sys.exit(1)

    # Optional Markdown report
    if args.markdown:
        try:
            from chipify import md_export
            stim = util.Stimuli(yaml_path)
            import pandas as pd
            df = pd.read_csv(os.path.join(settings.OUT_DIR, "simulation_results.csv"))
            md_export.generate_md_report(df, stim, yaml_path, args.markdown)
            print(f"[+] Markdown report saved to {args.markdown}")
        except Exception as exc:
            print(f"[!] Markdown report failed: {exc}")


def run_gui():
    """Starts the tkinter-based desktop GUI for chipify."""
    from chipify.gui.main_window import main as _gui_main
    print("[*] Starting Chipify Desktop GUI...")
    _gui_main()


if __name__ == "__main__":
    main()
