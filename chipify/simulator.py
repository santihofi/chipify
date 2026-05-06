# simulator.py
import os
import sys
import glob
import shutil
import itertools
import subprocess
import time
import logging
from multiprocessing import get_context

try:
    from multiprocessing.pool import WorkerLostError
except ImportError:
    WorkerLostError = Exception  # Python < 3.12.2 compat

import pandas as pd
from tqdm import tqdm
from jinja2 import Template

from chipify import settings
from chipify import util
from chipify import app_config

log = logging.getLogger("chipify.simulator")

ABORT_FLAG_PATH = os.path.join(settings.FAST_TMP, "abort.flag")


# ── Abort helpers ─────────────────────────────────────────────────────────────

def _is_aborted() -> bool:
    return os.path.exists(ABORT_FLAG_PATH)


def clear_abort_flag() -> None:
    if os.path.exists(ABORT_FLAG_PATH):
        try:
            os.remove(ABORT_FLAG_PATH)
        except Exception:
            pass


def abort_simulation() -> None:
    log.info("abort_simulation() called – writing abort flag.")
    try:
        with open(ABORT_FLAG_PATH, "w", encoding="utf-8") as f:
            f.write("abort")
    except Exception as exc:
        log.error("Could not write abort flag: %s", exc)


# ── Init helpers ──────────────────────────────────────────────────────────────

def stage_files_to_ram() -> None:
    log.info("Staging library files to RAM disk: %s", settings.FAST_TMP)
    search_patterns = ["*.lib", "*.mod", "*.inc"]

    for pattern in search_patterns:
        for file_path in glob.glob(os.path.join(settings.WORK_DIR, pattern)):
            filename = os.path.basename(file_path)
            dest_path = os.path.join(settings.FAST_TMP, filename)

            if not os.path.exists(dest_path):
                try:
                    shutil.copy2(file_path, dest_path)
                    log.debug("Staged: %s", filename)
                except Exception as exc:
                    log.warning("Could not stage %s: %s", filename, exc)


def run_xschem(xschem_file: str) -> None:
    """Generate a SPICE netlist via Xschem. Respects abort flag."""
    log.info("run_xschem: %s", xschem_file)
    process = None
    try:
        process = subprocess.Popen(
            ['xschem', '-n', '-s', '-q', '-x', '-o', settings.FAST_TMP, xschem_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=settings.WORK_DIR,
        )
        log.debug("Xschem PID=%d", process.pid)

        while process.poll() is None:
            if _is_aborted():
                process.kill()
                log.info("Xschem killed due to abort flag (PID=%d).", process.pid)
                raise InterruptedError("Aborted during Xschem netlist generation.")
            time.sleep(0.2)

        if process.returncode != 0:
            stderr = process.stderr.read() if process.stderr else ""
            log.error("Xschem failed (rc=%d): %s", process.returncode, stderr)
            sys.exit(1)

        log.info("Xschem finished OK.")

    except InterruptedError:
        raise
    except Exception as exc:
        if process is not None and process.poll() is None:
            process.kill()
        log.exception("Unexpected error in run_xschem: %s", exc)
        sys.exit(1)


def run_ngspice(netlist: str, timeout_sec: int = 10):
    custom_env = os.environ.copy()
    custom_env["OMP_NUM_THREADS"] = "1"

    pid = os.getpid()
    temp_spice_file = os.path.join(settings.FAST_TMP, f"sim_{pid}.spice")
    temp_log_file   = os.path.join(settings.FAST_TMP, f"sim_{pid}.log")

    with open(temp_spice_file, 'w') as f:
        f.write(netlist)

    process = None
    try:
        with open(temp_log_file, 'w') as log_file:
            process = subprocess.Popen(
                ["ngspice", "-b", "-r", os.devnull, temp_spice_file],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=settings.FAST_TMP,
                env=custom_env,
            )

            start_time = time.monotonic()
            while process.poll() is None:
                if _is_aborted():
                    process.kill()
                    return None, "ABORTED"
                if (time.monotonic() - start_time) > timeout_sec:
                    process.kill()
                    return None, "TIMEOUT"
                time.sleep(0.1)

            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, process.args)

        output_line = ""
        with open(temp_log_file, 'r') as lf:
            for line in lf:
                if line.startswith("MY_DATA:"):
                    output_line = line.strip()
                    break

        return output_line, None

    except subprocess.CalledProcessError:
        err_msg = "CRASH"
        if os.path.exists(temp_log_file):
            with open(temp_log_file, 'r') as f:
                err_msg = "".join(f.readlines()[-5:]).strip()
        return None, f"CRASH: {err_msg}"
    finally:
        if process is not None and process.poll() is None:
            process.kill()


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
                val_obj = test.value_lst[i]
                try:
                    val_float = float(val_str)
                    sample[val_obj.name] = val_float
                    sample[f"{val_obj.name}_pass"] = val_obj.isPass(val_float)
                    if not val_obj.isPass(val_float):
                        all_passed = False
                except ValueError:
                    sample['sim_error'] = f"{test.tb_path}: INVALID_OUTPUT({val_str})"
                    all_passed = False

            sample[f"{test.tb_path}_overall_pass"] = all_passed
        else:
            sample['sim_error'] = f"{test.tb_path}: NO_MY_DATA_FOUND"
            sample[f"{test.tb_path}_overall_pass"] = False

    return sample


def simulate_case_batch(batch_args):
    """Worker helper: process a batch of cases to reduce IPC overhead."""
    return [simulate_single_case(arg) for arg in batch_args]


def _chunk_args(worker_args, chunk_size):
    for i in range(0, len(worker_args), chunk_size):
        yield worker_args[i:i + chunk_size]


def generate_templates(stim) -> None:
    for test in stim.tests:
        if _is_aborted():
            raise InterruptedError("Aborted before netlist generation.")
        tb_path = os.path.join(settings.TB_DIR, test.tb_path + ".sch")
        run_xschem(tb_path)

        spice_file = os.path.join(settings.FAST_TMP, test.tb_path + ".spice")
        with open(spice_file, "r") as f:
            netlist = f.read()
            if ".control" in netlist:
                netlist = netlist.replace(".control", ".control\nset num_threads=1\n")
            else:
                netlist += "\n.control\nset num_threads=1\n.endc\n"
            test.template_str = netlist


def generate_cases(stim) -> list:
    param_names = stim.params.keys()
    param_values = stim.params.values()
    return [dict(zip(param_names, combo)) for combo in itertools.product(*param_values)]


def run_sim(stim, progress_callback=None, simulator="ngspice"):
    """
    Main simulation entry point.

    Uses multiprocessing with a non-fork context to avoid deadlocks in GUI apps:
    - Linux:  'forkserver' (stable + faster startup than spawn)
    - others: 'spawn'
    """
    pool = None
    log.info("run_sim() started. Testbenches: %d", len(stim.tests))

    try:
        clear_abort_flag()

        # ── Init phase ────────────────────────────────────────────────────────
        log.info("Phase 1/3: generating parameter cases...")
        param_sets = generate_cases(stim)
        log.info("Total cases: %d", len(param_sets))

        if _is_aborted():
            raise InterruptedError("Aborted before template generation.")
        log.info("Phase 2/3: generating Xschem templates...")
        generate_templates(stim)

        if _is_aborted():
            raise InterruptedError("Aborted before RAM staging.")
        log.info("Phase 3/3: staging files to RAM disk...")
        stage_files_to_ram()

        if _is_aborted():
            raise InterruptedError("Aborted before pool start.")

        worker_args = [(params, stim.tests) for params in param_sets]
        results = []

        cfg = app_config.load_config()
        num_cores = cfg.get("num_cores") or util.get_num_cores()
        log.info("Spawning pool: %d workers, %d tasks.", num_cores, len(worker_args))

        total_tasks = len(worker_args)
        completed = 0

        # ── Pool execution ────────────────────────────────────────────────────
        # Avoid plain 'fork' in GUI/threaded parents; use forkserver/spawn.
        start_method = "forkserver" if sys.platform.startswith("linux") else "spawn"
        ctx = get_context(start_method)
        pool = ctx.Pool(processes=num_cores)
        log.debug("Pool created (%s, %d workers).", start_method, num_cores)

        # Batch tasks to reduce scheduler/IPC overhead while keeping polling.
        chunk_size = max(1, min(16, total_tasks // (num_cores * 8) if num_cores > 0 else 1))
        batches = list(_chunk_args(worker_args, chunk_size))
        pending = [pool.apply_async(simulate_case_batch, (batch,)) for batch in batches]
        log.debug("%d batch tasks submitted (chunk_size=%d).", len(pending), chunk_size)

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
                        except (WorkerLostError, Exception) as exc:
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

        pool.close()
        pool.join()
        log.info("Pool finished cleanly. %d results collected.", len(results))

        return pd.DataFrame(results)

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
