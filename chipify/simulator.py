# Copyright (c) 2026 Santiago Hofwimmer
# simulator.py
"""
simulator.py – Sweep orchestration for Chipify.

This module owns the *engine-agnostic* half of a simulation run: parameter
case generation, per-testbench template generation, worker-pool execution,
per-analysis persistence, and result-DataFrame assembly.

Everything simulator-specific lives in :mod:`chipify.engines` — one
:class:`~chipify.engines.base.BaseSimulator` subclass per supported
simulator, resolved by name through the engine registry. Adding support for
another simulator therefore never requires touching this module (see
PLUGINS.md, "Simulator engine plugin").

For backward compatibility the engine API (``BaseSimulator``,
``NgspiceSimulator``, ``VacaskSimulator``, ``run_xschem``, abort helpers, …)
is re-exported here under its historical names.
"""
import os
import sys
import itertools
import time
import logging
import datetime
from pathlib import Path
from multiprocessing import get_context

import pandas as pd
from tqdm import tqdm
from jinja2 import Template, StrictUndefined

from chipify import settings
from chipify import util
from chipify import app_config

# ── Engine API (re-exported for backward compatibility) ──────────────────────
from chipify.engines import (  # noqa: F401
    DEFAULT_ENGINE,
    UnknownEngineError,
    engine_names,
    engine_selector,
    get_engine,
    netlist_extension,
    register_engine,
    resolve_engine_name,
)
from chipify.engines.abort import (  # noqa: F401
    ABORT_FLAG_PATH,
    abort_simulation,
    clear_abort_flag,
    is_aborted as _is_aborted,
)
from chipify.engines.base import (  # noqa: F401
    BaseSimulator,
    extract_error_line as _extract_ngspice_error,
)
from chipify.engines.ngspice import NgspiceSimulator, _inject_capture  # noqa: F401
from chipify.engines.rawfile import (  # noqa: F401
    parse_ascii_raw as _parse_ascii_raw,
    read_raw_file as _read_raw_file,
    sanitise_key as _sanitise_key,
)
from chipify.engines.staging import (  # noqa: F401
    stage_files_to_ram,
    staged_copy_is_stale as _staged_copy_is_stale,
)
from chipify.engines.vacask import (  # noqa: F401
    VacaskSimulator,
    _ng2vc_argv0,
    _ng2vc_search_paths,
    _resolve_ng2vc,
    _resolve_vacask_bin,
    _run_ng2vc,
    _vacask_extract_results,
    _vacask_write_analysis_tabs,
)
from chipify.engines.xschem import (  # noqa: F401
    XSCHEM_DEFAULT_TIMEOUT_SEC,
    run_xschem,
    safe_tb_path as _safe_tb_path,
)

log = logging.getLogger("chipify.simulator")

#: Built-in engine names (plugin engines come on top; see
#: ``chipify.engines.engine_names()`` for the full selectable list).
SUPPORTED_ENGINES = engine_names(include_plugins=False)


def get_simulator_engine(simulator_name: str) -> BaseSimulator:
    """Instantiate the engine registered under *simulator_name*.

    Unknown names fall back to ngspice **with a warning** — an unvalidated
    source (a typo'd ``simulator_engine`` in settings.json) must not crash a
    worker, but it must not silently run the wrong simulator either.
    """
    try:
        return get_engine(simulator_name)
    except UnknownEngineError:
        log.warning("Unknown simulator engine %r – falling back to %r. "
                    "Available: %s", simulator_name, DEFAULT_ENGINE,
                    ", ".join(engine_names()))
        return get_engine(DEFAULT_ENGINE)


# ── Per-run timeout ───────────────────────────────────────────────────────────

_DEFAULT_SIM_TIMEOUT_SEC = 10.0


def _resolve_sim_timeout(cfg: dict) -> float:
    """Per-simulation wall-clock limit from the ``sim_timeout_sec`` setting."""
    raw = cfg.get("sim_timeout_sec", _DEFAULT_SIM_TIMEOUT_SEC)
    try:
        val = float(raw)
    except (TypeError, ValueError):
        log.warning("Invalid sim_timeout_sec=%r, using %ss.",
                    raw, _DEFAULT_SIM_TIMEOUT_SEC)
        return _DEFAULT_SIM_TIMEOUT_SEC
    return val if val > 0 else _DEFAULT_SIM_TIMEOUT_SEC


# ── Analysis persistence (worker side) ────────────────────────────────────────

def _persist_analyses(analyses, analysis_tab_paths, analysis_dirs,
                      run_id, tb_safe, tb_path, sample, engine=None):
    """Write each declared analysis's tab file into its per-run CSV.

    If an analysis was set up to capture (tab path + output dir both present) but
    produced no CSV — the tab is missing, or present-but-empty/unreadable so
    ``persist_to_csv`` writes nothing — record a one-line reason (including the
    engine's own error line) on *sample* under ``<tb>__<kind>_capture``. Worker
    logging does not reach chipify.log (forkserver workers lack the file
    handler), so the result row is the reliable channel; ``run_sim`` surfaces
    these from the main process. This is what makes the silent Bode/AC
    "no data" case diagnosable.
    """
    eng_name = getattr(engine, "name", "") or "simulator"
    for an in analyses:
        tab = analysis_tab_paths.get(an.kind, "")
        dest_dir = analysis_dirs.get(an.kind, "")
        if not (tab and dest_dir):
            continue

        reason = ""
        if not Path(tab).exists():
            reason = (
                f"{eng_name} wrote no {an.kind} tab to capture "
                f"(does the testbench run its .{an.kind} analysis?)"
            )
        else:
            dest_csv = Path(dest_dir) / f"run_{run_id}__{tb_safe}.csv"
            an.persist_to_csv(tab, dest_csv)
            if not dest_csv.exists():
                reason = (
                    f"{eng_name} wrote an empty/unreadable {an.kind} tab "
                    f"(capture vectors were empty)"
                )

        if reason:
            err = ""
            if engine is not None:
                err = engine.extract_error(engine.run_log_tail())
            note = f"{an.kind} produced no data - {reason}"
            if err:
                note += f" | {eng_name}: {err}"
            sample[f"{tb_path}__{an.kind}_capture"] = note
            log.warning("%s: %s", tb_path, note)  # also surfaced from run_sim (main)


def _log_capture_failures(results: list) -> None:
    """Surface analysis-capture failures recorded on result rows (main process).

    Workers can't write to chipify.log under forkserver, so ``_persist_analyses``
    stashes the reason on each row under ``<tb>__<kind>_capture``. Here, in the
    main process, we log each distinct failure once so it actually reaches the
    log file (and it also persists as a column in simulation_results.csv).
    """
    counts: dict[tuple[str, str], int] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        for key, val in row.items():
            if (isinstance(key, str) and key.endswith("_capture")
                    and isinstance(val, str) and val):
                counts[(key, val)] = counts.get((key, val), 0) + 1
    for (key, val), count in counts.items():
        tb = key[: -len("_capture")].rstrip("_")
        log.warning("Analysis capture failed on %s (%d run(s)): %s", tb, count, val)


# ── Case evaluation (worker side) ─────────────────────────────────────────────

def _eval_scalar_measures(test, sample: dict, params: dict) -> None:
    """Evaluate datasheet ``measure:`` expressions against this run's scalars.

    Runs after MY_DATA parsing so a measure can reference the test's measured
    values (e.g. ``gbw: gain * bandwidth``) as well as numeric sweep
    parameters. This makes ``measure:`` work on the ngspice engine; on the
    VACASK raw path, names already computed from waveforms are left untouched
    (``name in sample`` check). A failed expression records NaN plus a
    one-line note under ``<tb>__measure_error`` — worker logging doesn't
    reach chipify.log (see _persist_analyses), so the row is the channel.
    """
    measures = getattr(test, "measure", {}) or {}
    if not measures:
        return
    from chipify.expression import default_evaluator

    namespace = {
        k: v for k, v in {**params, **sample}.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    for name, expr in measures.items():
        if name in sample:
            continue
        try:
            val = default_evaluator.evaluate_spice_measure(expr, namespace)
            sample[name] = float(val)
        except Exception as exc:
            sample[name] = float('nan')
            note = f"measure '{name}' = {expr!r} failed: {exc}"
            sample[f"{test.tb_path}__measure_error"] = " ".join(str(note).split())[:200]


def _fail_test(sample: dict, test, message: str) -> None:
    """Mark every measurement of *test* failed with *message* in *sample*."""
    sample['sim_error'] = message
    sample[f"{test.tb_path}_overall_pass"] = False
    for val_obj in test.value_lst:
        sample[val_obj.name] = float('nan')
        sample[f"{val_obj.name}_pass"] = False


def _simulate_single_case(params, tests, engine_for,
                          run_id: str = "",
                          analysis_dirs: dict | None = None):
    """Simulate one parameter case across *tests*.

    *engine_for* is a ``test -> BaseSimulator`` selector, so each testbench can
    run on its own engine within the same case. Every per-testbench failure
    (template rendering, engine crash, bad output) fails only that testbench's
    measurements — one bad testbench must never lose the whole case (or, worse,
    the whole worker batch).
    """
    analysis_dirs = analysis_dirs or {}
    sample = params.copy()
    sample['sim_error'] = "None"
    sample['run_id'] = run_id

    timeout_sec = _resolve_sim_timeout(app_config.load_config())

    for test in tests:
        # A testbench whose netlist couldn't be generated (e.g. its engine is
        # unavailable) fails only its own measurements; the rest of the case
        # still runs on their own engines.
        tmpl_err = getattr(test, "template_error", None)
        if tmpl_err or not getattr(test, "template_str", ""):
            _fail_test(sample, test, tmpl_err or f"{test.tb_path}: no netlist template")
            continue
        try:
            engine = engine_for(test)
        except Exception as exc:  # noqa: BLE001
            _fail_test(sample, test, f"{test.tb_path}: engine unavailable: {exc}")
            continue

        analyses = getattr(test, "analyses", []) or []
        pid = os.getpid()
        tb_safe = test.tb_path.replace("/", "__").replace("\\", "__")

        # One worker-private tab file per declared analysis. The Jinja
        # variable name (tran_out_path / dc_out_path / ac_out_path) tells the
        # rendered ngspice template where to wrdata; VacaskSimulator also
        # uses this mapping to dump signals from the .raw file.
        render_kwargs = dict(params)
        analysis_tab_paths: dict[str, str] = {}
        for an in analyses:
            if not analysis_dirs.get(an.kind):
                continue
            # Kept as str: this path is baked into the rendered netlist (ngspice
            # wrdata target) and travels through the engine as a plain path.
            tab = str(
                Path(settings.FAST_TMP)
                / f"sim_{pid}_{run_id}_{tb_safe}_{an.kind}.tab"
            )
            render_kwargs[an.jinja_var()] = tab
            analysis_tab_paths[an.kind] = tab

        # StrictUndefined raises on any placeholder the case's parameters
        # don't cover (e.g. a param-name typo in the testbench). That must
        # fail this testbench's row — an uncaught exception here would lose
        # the entire worker batch with only a main-process log line.
        try:
            rendering = Template(
                test.template_str, undefined=StrictUndefined,
            ).render(**render_kwargs)
        except Exception as exc:  # noqa: BLE001
            _fail_test(sample, test,
                       f"{test.tb_path}: TEMPLATE_RENDER_ERROR: {exc}")
            continue

        # Built-in engines report failures via error_msg; a plugin engine may
        # raise instead — contain it the same way.
        try:
            sim_output, error_msg = engine.run(
                rendering, timeout_sec=timeout_sec,
                test=test, analysis_tab_paths=analysis_tab_paths,
            )
        except Exception as exc:  # noqa: BLE001
            _fail_test(sample, test,
                       f"{test.tb_path}: [{engine.name}] ENGINE_ERROR: {exc}")
            continue

        if error_msg:
            _fail_test(sample, test, f"{test.tb_path}: {error_msg}")
            continue

        # Persist every analysis's tab file into its destination CSV (and surface
        # any analysis that ran but produced no output — see _persist_analyses).
        _persist_analyses(
            analyses, analysis_tab_paths, analysis_dirs,
            run_id, tb_safe, test.tb_path, sample, engine=engine,
        )

        # Transient-only testbench: no scalar measurements defined → skip MY_DATA.
        if not test.value_lst:
            sample[f"{test.tb_path}_overall_pass"] = True
            _eval_scalar_measures(test, sample, params)
            continue

        if sim_output and sim_output.startswith("MY_DATA:"):
            clean_line = sim_output[len("MY_DATA:"):].strip()
            values = [v for v in clean_line.split(' ') if v]

            all_passed = True
            for i, val_str in enumerate(values):
                if i >= len(test.value_lst):
                    break
                val_obj = test.value_lst[i]
                try:
                    val_float = float(val_str)
                    sample[val_obj.name] = val_float
                    sample[f"{val_obj.name}_pass"] = val_obj.isPass(val_float)
                    if not val_obj.isPass(val_float):
                        all_passed = False
                except ValueError:
                    # Unparsable token → that value is failed data, not a
                    # silently absent column.
                    sample['sim_error'] = f"{test.tb_path}: INVALID_OUTPUT({val_str})"
                    sample[val_obj.name] = float('nan')
                    sample[f"{val_obj.name}_pass"] = False
                    all_passed = False

            # Fewer values than declared measurements is an error, not a
            # silent gap — mark the missing ones failed so the row can't
            # masquerade as a clean run with absent columns.
            n_expected = len(test.value_lst)
            if len(values) < n_expected:
                sample['sim_error'] = (
                    f"{test.tb_path}: INVALID_OUTPUT("
                    f"expected {n_expected} values, got {len(values)})"
                )
                all_passed = False
                for val_obj in test.value_lst[len(values):]:
                    sample[val_obj.name] = float('nan')
                    sample[f"{val_obj.name}_pass"] = False

            sample[f"{test.tb_path}_overall_pass"] = all_passed
            _eval_scalar_measures(test, sample, params)
        else:
            sample['sim_error'] = f"{test.tb_path}: NO_MY_DATA_FOUND"
            sample[f"{test.tb_path}_overall_pass"] = False

    return sample


def _simulate_single_case_with_engine(params, tests, engine: BaseSimulator,
                                      run_id: str = "",
                                      analysis_dirs: dict | None = None):
    """Back-compat shim: run all *tests* with one explicit *engine*."""
    return _simulate_single_case(
        params, tests, lambda _t: engine, run_id, analysis_dirs,
    )


def simulate_case_batch(batch_args):
    """Worker helper: process a batch of cases to reduce IPC overhead.

    Each ``Test`` carries its resolved ``engine`` name (set by run_sim); engines
    are instantiated once per worker and reused across the batch, so a datasheet
    can mix engines across testbenches.
    """
    param_id_batch, tests, analysis_dirs = batch_args
    engine_for = engine_selector()

    return [
        _simulate_single_case(params, tests, engine_for, run_id, analysis_dirs)
        for params, run_id in param_id_batch
    ]


def _chunk_args(worker_args, chunk_size):
    for i in range(0, len(worker_args), chunk_size):
        yield worker_args[i:i + chunk_size]


def _resolve_chunk_size(cfg, total_tasks, num_cores):
    configured = str(cfg.get("chunk_size", "auto"))
    if configured == "auto":
        return max(1, min(16, total_tasks // (num_cores * 8) if num_cores > 0 else 1))
    try:
        parsed = int(configured)
        return max(1, parsed)
    except (TypeError, ValueError):
        log.warning("Unknown chunk_size=%r, falling back to auto.", configured)
        return max(1, min(16, total_tasks // (num_cores * 8) if num_cores > 0 else 1))


# ── Template generation (main process) ────────────────────────────────────────

def generate_templates(stim, templates_dir: str = "") -> None:
    """Populate ``test.template_str`` for every test in *stim*.

    Each testbench is rendered with **its own** engine (``test.engine``, resolved
    by run_sim), so a datasheet can mix engines. If a testbench's netlist can't
    be produced (e.g. its engine is unavailable), the failure is recorded on
    ``test.template_error`` and that testbench's runs fail individually — the rest
    of the sweep continues.

    If *templates_dir* is set, read pre-rendered xschem outputs from
    ``<templates_dir>/<safe_tb_path><engine.netlist_ext>`` instead of invoking
    xschem locally — useful for re-running a sweep against netlists that were
    already generated.
    """
    engine_for = engine_selector()

    for test in stim.tests:
        if _is_aborted():
            raise InterruptedError("Aborted before netlist generation.")
        test.template_error = None
        try:
            engine = engine_for(test)
        except Exception as exc:  # noqa: BLE001
            test.template_str = ""
            test.template_error = f"{test.tb_path}: engine unavailable: {exc}"
            log.warning("Engine resolution failed for %s: %s", test.tb_path, exc)
            continue
        ext = engine.netlist_ext
        try:
            if templates_dir:
                safe = test.tb_path.replace("/", "__").replace("\\", "__")
                fp = Path(templates_dir) / (safe + ext)
                test.template_str = fp.read_text(encoding="utf-8")
            else:
                test.template_str = engine.generate_test_template(test)
        except InterruptedError:
            raise
        except Exception as exc:  # noqa: BLE001
            test.template_str = ""
            test.template_error = (
                f"{test.tb_path}: [{engine.name}] netlist generation failed: {exc}"
            )
            log.warning("Template generation failed for %s [%s]: %s",
                        test.tb_path, engine.name, exc)


def generate_cases(stim) -> list:
    param_names = stim.params.keys()
    param_values = stim.params.values()
    return [dict(zip(param_names, combo)) for combo in itertools.product(*param_values)]


# ── Result assembly ───────────────────────────────────────────────────────────

def _assemble_result_df(rows: list, analysis_dirs: dict) -> pd.DataFrame:
    """Build a normalized results DataFrame (matches GUI / CSV load semantics).

    The per-analysis directories are stored under ``df.attrs["analysis_dirs"]``
    so the GUI can locate transient / DC / AC CSVs by kind. ``df.attrs["tran_dir"]``
    is also set for backward compatibility with consumers that only know about
    transient.
    """
    from chipify import data_loader as _dl

    df = pd.DataFrame(rows)
    df = _dl.normalise_sim_error(df)
    df = _dl.compute_global_pass(df)
    if analysis_dirs:
        df.attrs["analysis_dirs"] = dict(analysis_dirs)
        if analysis_dirs.get("transient"):
            df.attrs["tran_dir"] = analysis_dirs["transient"]
    return df


def write_analysis_pointers(analysis_dirs: dict) -> None:
    """Record each kind's latest data directory in ``analysis_data/<kind>/.latest``.

    The GUI's analysis-dir resolution reads these pointer files after a
    restart; the legacy ``tran_data/.latest`` pointer is also kept for
    transient so older consumers keep working.
    """
    out_dir = Path(settings.OUT_DIR)
    for kind, d in (analysis_dirs or {}).items():
        if not d:
            continue
        targets = [out_dir / "analysis_data" / kind / ".latest"]
        if kind == "transient":
            targets.append(out_dir / "tran_data" / ".latest")
        for ptr in targets:
            try:
                ptr.parent.mkdir(parents=True, exist_ok=True)
                ptr.write_text(str(d), encoding="utf-8")
            except Exception as exc:
                log.warning("Could not write %s pointer %s: %s", kind, ptr, exc)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_sim(stim, progress_callback=None, simulator=None, chunk_callback=None,
            templates_dir: str = ""):
    """
    Main simulation entry point.

    Uses multiprocessing with a non-fork context to avoid deadlocks in GUI apps:
    - Linux:  'forkserver' (stable + faster startup than spawn)
    - others: 'spawn'

    Parameters
    ----------
    chunk_callback:
        If ``None`` (default CLI path), no per-batch DataFrame assembly runs.
        If set, called with incremental row batches according to
        ``live_plot_emit_stride`` in settings — omit passing this when live
        plotting is disabled so the sweep stays at baseline CPU cost.
    templates_dir:
        When set, skip xschem and load pre-rendered Jinja2 templates from
        this directory (see ``--templates-dir``) instead of regenerating them.
    """
    pool = None
    log.info("run_sim() started. Testbenches: %d", len(stim.tests))

    try:
        clear_abort_flag()

        # ── Init phase ────────────────────────────────────────────────────────
        log.info("Phase 1/3: generating parameter cases...")
        param_sets = generate_cases(stim)
        log.info("Total cases: %d", len(param_sets))
        cfg = app_config.load_config()
        # Resolve each testbench's engine: its own ``engine:`` wins, else the CLI
        # --simulator override, else the simulator_engine setting, else ngspice.
        # Write the concrete name back onto the (picklable) Test so workers and
        # template generation pick the right engine per testbench.
        for test in stim.tests:
            test.engine = resolve_engine_name(test, simulator, cfg)
        engines_in_use = sorted({t.engine for t in stim.tests})
        engine_instances = [get_simulator_engine(n) for n in engines_in_use]
        log.info("Simulator engine(s) in use: %s", ", ".join(engines_in_use))

        if _is_aborted():
            raise InterruptedError("Aborted before template generation.")
        log.info("Phase 2/3: generating Xschem templates...")
        generate_templates(stim, templates_dir=templates_dir)

        if _is_aborted():
            raise InterruptedError("Aborted before RAM staging.")
        log.info("Phase 3/3: staging files to RAM disk...")
        stage_files_to_ram(engine_instances)

        if _is_aborted():
            raise InterruptedError("Aborted before pool start.")

        # Assign a stable zero-padded run_id to every parameter case.
        run_ids = [f"{i:06d}" for i in range(len(param_sets))]

        # Create one per-analysis directory under analysis_data/<kind>/<ts>/.
        # Only kinds actually used by at least one test get a directory.
        sim_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        analysis_dirs: dict[str, str] = {}
        for kind in ("transient", "dc", "ac"):
            if any(
                any(a.kind == kind for a in getattr(t, "analyses", []) or [])
                for t in stim.tests
            ):
                d = Path(settings.OUT_DIR) / "analysis_data" / kind / sim_timestamp
                d.mkdir(parents=True, exist_ok=True)
                # Stored as str: rides df.attrs and is JSON-serialised into the
                # run's .meta.json sidecar.
                analysis_dirs[kind] = str(d)
                log.info("%s store: %s", kind, d)

        results = []
        num_cores = cfg.get("num_cores") or util.get_num_cores()
        log.info("Spawning pool: %d workers, %d tasks.", num_cores, len(param_sets))

        total_tasks = len(param_sets)
        completed = 0

        # ── Pool execution ────────────────────────────────────────────────────
        # Avoid plain 'fork' in GUI/threaded parents; use forkserver/spawn.
        configured_method = cfg.get("process_start_method", "auto")
        if configured_method == "auto":
            start_method = "forkserver" if sys.platform.startswith("linux") else "spawn"
        elif configured_method in {"forkserver", "spawn"}:
            start_method = configured_method
        else:
            log.warning("Unknown process_start_method=%r, falling back to auto.", configured_method)
            start_method = "forkserver" if sys.platform.startswith("linux") else "spawn"
        ctx = get_context(start_method)
        pool = ctx.Pool(processes=num_cores)
        log.debug("Pool created (%s, %d workers).", start_method, num_cores)

        # Batch tasks to reduce scheduler/IPC overhead while keeping polling.
        # Each batch item is a (params, run_id) pair so workers can persist
        # per-analysis CSVs with the correct run_id in the filename.
        chunk_size = _resolve_chunk_size(cfg, total_tasks, num_cores)
        param_id_pairs = list(zip(param_sets, run_ids))
        param_id_batches = list(_chunk_args(param_id_pairs, chunk_size))
        pending = [
            pool.apply_async(
                simulate_case_batch,
                ((batch, stim.tests, analysis_dirs),),
            )
            for batch in param_id_batches
        ]
        log.debug("%d batch tasks submitted (chunk_size=%d).", len(pending), chunk_size)

        chunk_emit_stride = max(1, app_config.get_live_plot_emit_stride()) if chunk_callback else 1
        chunk_batch_counter = 0
        chunk_row_buffer: list = []

        with tqdm(total=total_tasks) as pbar:
            while pending:
                if _is_aborted():
                    log.info("Abort flag detected – terminating pool.")
                    raise InterruptedError("Abort flag detected during run.")

                still_pending = []
                for ar in pending:
                    if ar.ready():
                        try:
                            batch_results = ar.get(timeout=0)
                            results.extend(batch_results)
                            completed += len(batch_results)
                            if chunk_callback and batch_results:
                                chunk_row_buffer.extend(batch_results)
                                chunk_batch_counter += 1
                                sweep_complete = len(results) >= total_tasks
                                emit_now = sweep_complete or (
                                    chunk_batch_counter % chunk_emit_stride == 0
                                )
                                if emit_now and chunk_row_buffer:
                                    try:
                                        chunk_df = _assemble_result_df(
                                            chunk_row_buffer, analysis_dirs
                                        )
                                        chunk_callback(chunk_df)
                                    except Exception:
                                        log.debug("chunk_callback failed.", exc_info=True)
                                    chunk_row_buffer = []
                        except InterruptedError:
                            raise
                        except Exception as exc:  # incl. WorkerLostError
                            log.error("Worker error (result skipped): %s", exc)
                            completed += chunk_size
                        completed = min(total_tasks, completed)
                        pbar.update(min(total_tasks - pbar.n, max(0, completed - pbar.n)))
                        if progress_callback:
                            progress_callback(completed, total_tasks)
                    else:
                        still_pending.append(ar)

                pending = still_pending
                if pending:
                    time.sleep(0.05)

        # Flush any live rows left in stride buffer (should usually be empty).
        if chunk_callback and chunk_row_buffer:
            try:
                chunk_df = _assemble_result_df(chunk_row_buffer, analysis_dirs)
                chunk_callback(chunk_df)
            except Exception:
                log.debug("chunk_callback failed on final flush.", exc_info=True)
            chunk_row_buffer = []

        pool.close()
        pool.join()
        log.info("Pool finished cleanly. %d results collected.", len(results))

        # Surface analysis-capture failures recorded by workers (worker logging
        # doesn't reach chipify.log under forkserver, so the reason rides the row).
        _log_capture_failures(results)

        result_df = _assemble_result_df(results, analysis_dirs)
        return result_df

    except InterruptedError:
        log.info("Simulation interrupted by user.")
        if pool is not None:
            pool.terminate()
            pool.join()
            log.info("Pool terminated.")
        return None

    except Exception as exc:
        log.exception("Unexpected error during simulation: %s", exc)
        if pool is not None:
            pool.terminate()
            pool.join()
            log.info("Pool terminated after error.")
        return None

    finally:
        clear_abort_flag()
        log.info("run_sim() exited.")
