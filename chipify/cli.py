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


def _emit_phase(name: str) -> None:
    """Print a 'PHASE: <name>' marker on stdout (no-op if not in stream mode).

    Phases (chronological): startup, load_config, templates, ram_stage,
    simulating, postprocess, results_write, history_write, complete.
    The local RemoteDispatcher uses these for the GUI status label.
    """
    print(f"PHASE: {name}", flush=True)


def _make_progress_stream_cb():
    """Return a progress_callback that emits 'PROGRESS: <done> <total>' to stdout.

    Used by --progress-stream when chipify-cli is invoked over SSH by
    RemoteDispatcher; the local side tails stdout for these lines to drive
    the GUI progress bar.
    """
    def _cb(current: int, total: int) -> None:
        print(f"PROGRESS: {current} {total}", flush=True)
    return _cb


def _run_single(yaml_path: str, *, json_out: bool = False,
                simulator_override: str | None = None,
                templates_dir: str | None = None,
                progress_stream: bool = False) -> dict | None:
    """Run simulation for one yaml file. Returns summary dict or None on failure."""
    import time
    if progress_stream:
        _emit_phase("load_config")
    print(f"[*] Loading configuration: {os.path.basename(yaml_path)}")
    stim = util.Stimuli(yaml_path)
    t0 = time.perf_counter()
    progress_cb = _make_progress_stream_cb() if progress_stream else None
    if progress_stream:
        _emit_phase("simulating")
    df = simulator.run_sim(
        stim,
        simulator=simulator_override,
        yaml_path=yaml_path,
        templates_dir=templates_dir or "",
        progress_callback=progress_cb,
    )
    duration_s = time.perf_counter() - t0

    if df is None:
        print(f"[-] Simulation returned no data for {yaml_path}")
        return None

    if progress_stream:
        _emit_phase("postprocess")
    csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
    df.to_csv(csv_out, index=False)
    if progress_stream:
        _emit_phase("results_write")
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
    if progress_stream:
        _emit_phase("complete")
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

    parser.add_argument(
        "--templates-dir",
        metavar="DIR",
        default=None,
        help=(
            "Skip xschem netlist generation and load pre-rendered Jinja2\n"
            "templates from DIR. Set by chipify on the remote host when\n"
            "RemoteDispatcher offloads a sweep — not for normal local use."
        ),
    )

    parser.add_argument(
        "--progress-stream",
        action="store_true",
        default=False,
        help=(
            "Emit 'PROGRESS: <done> <total>' and 'PHASE: <name>' lines to\n"
            "stdout. Used by RemoteDispatcher to drive the GUI progress\n"
            "bar + phase indicator over SSH; harmless otherwise."
        ),
    )

    parser.add_argument(
        "--preflight",
        action="store_true",
        default=False,
        help=(
            "Print a single JSON line describing this host's chipify /\n"
            "Python / ngspice / xschem / PDK / disk state, then exit.\n"
            "Used by the GUI's 'Test Connection' button."
        ),
    )

    args = parser.parse_args()

    if args.preflight:
        from chipify.preflight import emit_json
        sys.exit(emit_json())

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
                                  simulator_override=args.simulator,
                                  templates_dir=args.templates_dir,
                                  progress_stream=args.progress_stream)
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
                          simulator_override=args.simulator,
                          templates_dir=args.templates_dir,
                          progress_stream=args.progress_stream)
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
