# Copyright (c) 2026 Santiago Hofwimmer
import argparse
import os
import sys
import json

from chipify import util
from chipify import settings
from chipify import simulator
from chipify.analyzer import print_summary


def _json_summary(df, yaml_name: str, duration_s: float) -> dict:
    """Return a machine-readable summary dict for the completed run."""
    from chipify import data_loader as _dl
    s = _dl.result_summary(_dl.prepare_results(df))
    return {
        "yaml":       yaml_name,
        "total":      s.total,
        "crashes":    s.crashes,
        "valid":      s.valid,
        "passed":     s.passed,
        "yield":      round(s.yield_pct, 2),
        "duration_s": round(duration_s, 2),
    }


def _make_progress_stream_cb():
    """Return a progress_callback that emits 'PROGRESS: <done> <total>' to stdout.

    Enabled by --progress-stream so a parent process can tail stdout for these
    lines and drive its own progress bar.
    """
    def _cb(current: int, total: int) -> None:
        print(f"PROGRESS: {current} {total}", flush=True)
    return _cb


def _run_single(yaml_path: str, *, json_out: bool = False,
                simulator_override: str | None = None,
                templates_dir: str | None = None,
                progress_stream: bool = False,
                out_dir: str | None = None) -> dict | None:
    """Run simulation for one yaml file. Returns summary dict or None on failure.

    out_dir:
        Where to write simulation_results.csv and history/. Defaults to the
        global OUT_DIR; batch mode passes a per-datasheet subdirectory so
        consecutive runs don't overwrite each other.
    """
    import time
    print(f"[*] Loading configuration: {os.path.basename(yaml_path)}")
    out_dir = out_dir or settings.OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    stim = util.Stimuli(yaml_path)
    t0 = time.perf_counter()
    progress_cb = _make_progress_stream_cb() if progress_stream else None
    df = simulator.run_sim(
        stim,
        simulator=simulator_override,
        templates_dir=templates_dir or "",
        progress_callback=progress_cb,
    )
    duration_s = time.perf_counter() - t0

    if df is None:
        print(f"[-] Simulation returned no data for {yaml_path}")
        return None

    csv_out = os.path.join(out_dir, "simulation_results.csv")
    df.to_csv(csv_out, index=False)
    print(f"[+] Results saved to {csv_out}")

    analysis_dirs = df.attrs.get("analysis_dirs", {}) or {}
    simulator.write_analysis_pointers(analysis_dirs)

    # Save history copy + sidecar metadata
    try:
        import datetime
        from chipify import run_meta
        history_dir = os.path.join(out_dir, "history")
        os.makedirs(history_dir, exist_ok=True)
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        hist = os.path.join(history_dir, f"run_{ts}.csv")
        df.to_csv(hist, index=False)
        from chipify import data_loader as _dl
        s = _dl.result_summary(_dl.prepare_results(df))
        run_meta.write_meta(hist, yaml_name=os.path.basename(yaml_path),
                            duration_s=duration_s, total_runs=s.total,
                            valid_runs=s.valid, global_yield=round(s.yield_pct, 2),
                            tran_dir=analysis_dirs.get("transient", ""),
                            analysis_dirs=analysis_dirs)
    except Exception as exc:
        print(f"[!] Could not save history: {exc}")

    print_summary(df, stim)

    summary = _json_summary(df, os.path.basename(yaml_path), duration_s)
    if json_out:
        print(json.dumps(summary))
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Chipify: High-Performance Mismatch Simulation Wrapper for Xschem and Ngspice.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "-c", "--config",
        type=str,
        default="datasheet.yaml",
        help=(
            "Name of .yaml config file.\n"
            "(Searched in the input folder — 'datasheets/' by default,\n"
            "configurable via the in_dir key in settings.json.)\n"
            "Default: datasheet.yaml"
        ),
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
        help=(
            "After simulation, write a Markdown report to OUTPUT path.\n"
            "In --batch mode, OUTPUT is treated as a directory and one\n"
            "<datasheet>.md report is written per datasheet."
        ),
    )

    parser.add_argument(
        "--simulator",
        choices=["ngspice", "vacask"],
        default=None,
        help=(
            "Default engine for this run, overriding the simulator_engine setting\n"
            "(ngspice|vacask). Per-testbench 'engine:' keys in the datasheet still\n"
            "take precedence."
        ),
    )

    parser.add_argument(
        "--templates-dir",
        metavar="DIR",
        default=None,
        help=(
            "Skip xschem netlist generation and load pre-rendered Jinja2\n"
            "templates from DIR instead — useful for re-running a sweep\n"
            "against netlists that were already generated."
        ),
    )

    parser.add_argument(
        "--progress-stream",
        action="store_true",
        default=False,
        help=(
            "Emit 'PROGRESS: <done> <total>' lines to stdout for each batch\n"
            "completion, so a parent process can track progress; harmless\n"
            "otherwise."
        ),
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
            # Per-datasheet output subdirectory so consecutive runs don't
            # overwrite each other's simulation_results.csv.
            stem = os.path.splitext(os.path.basename(yaml_path))[0]
            run_out_dir = os.path.join(settings.OUT_DIR, stem)
            summary = _run_single(yaml_path, json_out=args.json,
                                  simulator_override=args.simulator,
                                  templates_dir=args.templates_dir,
                                  progress_stream=args.progress_stream,
                                  out_dir=run_out_dir)
            if summary is None:
                all_ok = False
                summary = {"yaml": os.path.basename(yaml_path), "error": "no data"}
            elif args.markdown:
                try:
                    from chipify import md_export
                    import pandas as pd
                    md_dir = args.markdown
                    os.makedirs(md_dir, exist_ok=True)
                    md_path = os.path.join(md_dir, f"{stem}.md")
                    df = pd.read_csv(os.path.join(run_out_dir, "simulation_results.csv"))
                    stim = util.Stimuli(yaml_path)
                    md_export.generate_md_report(df, stim, yaml_path, md_path)
                    print(f"[+] Markdown report saved to {md_path}")
                except Exception as exc:
                    print(f"[!] Markdown report failed for {stem}: {exc}")
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

    print("[*] Initialising Chipify...")
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
    """Starts the PySide6 (Qt) desktop GUI for chipify."""
    from chipify.gui_qt.app import main as _gui_main
    print("[*] Starting Chipify Desktop GUI...")
    _gui_main()


if __name__ == "__main__":
    main()
