# simulator.py
import os
import re
import sys
import glob
import shutil
import itertools
import subprocess
import time
import logging
import datetime
from multiprocessing import get_context
from abc import ABC, abstractmethod

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


# ── Path helpers ──────────────────────────────────────────────────────────────

def _safe_tb_path(tb_name: str) -> str:
    """Return the absolute testbench .sch path, raising ValueError on traversal attempts."""
    base = os.path.normpath(settings.TB_DIR)
    full = os.path.normpath(os.path.join(settings.TB_DIR, tb_name + ".sch"))
    if not full.startswith(base + os.sep) and full != base:
        raise ValueError(
            f"Testbench path {tb_name!r} escapes TB_DIR ({settings.TB_DIR!r})."
        )
    return full


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
        log.exception("Unexpected error in run_xschem: %s", exc)
        sys.exit(1)
    finally:
        if process is not None and process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass


class BaseSimulator(ABC):
    """Abstract simulator engine interface for extensible backend support."""

    name = "base"

    @abstractmethod
    def generate_test_template(self, test) -> str:
        """Return a rendered-ready test template string."""
        raise NotImplementedError

    @abstractmethod
    def run(self, netlist: str, timeout_sec: int = 10, test=None, tran_out_path: str = ""):
        """Execute one netlist and return (output_line, error_message).

        test          – the Test object for the current testbench (optional; used by
                        VacaskSimulator to evaluate measure expressions).
        tran_out_path – path where the engine should write transient waveform data in
                        ngspice wrdata .tab column layout (optional; used by
                        VacaskSimulator to persist waveforms without a .control block).
        """
        raise NotImplementedError


class NgspiceSimulator(BaseSimulator):
    name = "ngspice"

    def generate_test_template(self, test) -> str:
        tb_path = _safe_tb_path(test.tb_path)
        run_xschem(tb_path)

        spice_file = os.path.join(settings.FAST_TMP, test.tb_path + ".spice")
        with open(spice_file, "r") as f:
            netlist = f.read()
            if ".control" in netlist:
                netlist = netlist.replace(".control", ".control\nset num_threads=1\n")
            else:
                netlist += "\n.control\nset num_threads=1\n.endc\n"

            # Inject wrdata command for transient signal capture.
            # {{ tran_out_path }} is a Jinja2 placeholder filled per worker call.
            if getattr(test, "transient_signals", []):
                signals_str = " ".join(test.transient_signals)
                wrdata_line = f"wrdata {{{{ tran_out_path }}}} {signals_str}"
                netlist = netlist.replace(".endc", f"{wrdata_line}\n.endc", 1)

            return netlist

    def run(self, netlist: str, timeout_sec: int = 10, test=None, tran_out_path: str = ""):
        custom_env = os.environ.copy()
        custom_env["OMP_NUM_THREADS"] = "1"

        pid = os.getpid()
        temp_spice_file = os.path.join(settings.FAST_TMP, f"sim_{pid}.spice")
        temp_log_file = os.path.join(settings.FAST_TMP, f"sim_{pid}.log")

        with open(temp_spice_file, "w") as f:
            f.write(netlist)

        process = None
        try:
            with open(temp_log_file, "w") as log_file:
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
            with open(temp_log_file, "r") as lf:
                for line in lf:
                    if line.startswith("MY_DATA:"):
                        output_line = line.strip()
                        break

            return output_line, None

        except subprocess.CalledProcessError:
            err_msg = "CRASH"
            if os.path.exists(temp_log_file):
                with open(temp_log_file, "r") as f:
                    err_msg = "".join(f.readlines()[-5:]).strip()
            return None, f"CRASH: {err_msg}"
        finally:
            if process is not None and process.poll() is None:
                process.kill()


def get_simulator_engine(simulator_name: str) -> BaseSimulator:
    key = (simulator_name or "ngspice").strip().lower()
    engines = {"ngspice": NgspiceSimulator, "vacask": VacaskSimulator}
    return engines.get(key, NgspiceSimulator)()


# ── VACASK helpers ─────────────────────────────────────────────────────────────

def _run_xschem_vacask(xschem_file: str) -> None:
    """Generate a VACASK .sim netlist via Xschem using Spectre-syntax netlist output.

    Uses ``--spectre`` (supported by all recent Xschem builds) which produces
    the Spectre-like syntax that VACASK expects.  The ``--simulator`` flag is
    intentionally avoided because many container builds do not support it.
    """
    log.info("run_xschem_vacask: %s", xschem_file)
    process = None
    sim_file = os.path.join(
        settings.FAST_TMP,
        os.path.splitext(os.path.basename(xschem_file))[0] + ".sim",
    )
    last_error = ""
    # Some xschem builds return rc=1 in batch mode despite writing a valid netlist.
    # Try both with and without -q, then accept success if the .sim file exists.
    command_variants = [
        ['xschem', '-n', '--spectre', '-q', '-x', '-o', settings.FAST_TMP, xschem_file],
        ['xschem', '-n', '--spectre', '-x', '-o', settings.FAST_TMP, xschem_file],
    ]
    try:
        for cmd in command_variants:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=settings.WORK_DIR,
            )
            while process.poll() is None:
                if _is_aborted():
                    process.kill()
                    raise InterruptedError("Aborted during Xschem VACASK netlist generation.")
                time.sleep(0.2)

            stdout = process.stdout.read() if process.stdout else ""
            stderr = process.stderr.read() if process.stderr else ""

            if process.returncode == 0 and os.path.exists(sim_file):
                log.info("Xschem VACASK netlist generated OK.")
                return

            if os.path.exists(sim_file):
                log.warning(
                    "Xschem returned rc=%d but produced %s. Continuing.",
                    process.returncode, sim_file,
                )
                return

            last_error = (
                f"cmd={' '.join(cmd)} rc={process.returncode} "
                f"stdout={stdout.strip()} stderr={stderr.strip()}"
            )

        raise RuntimeError(
            f"Xschem VACASK netlist generation failed. Last attempt: {last_error}"
        )
    except InterruptedError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Xschem VACASK netlist generation failed: {exc}") from exc
    finally:
        if process is not None and process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                pass


def _run_ng2vc(spice_file: str, sim_file: str) -> None:
    """Convert an ngspice netlist to VACASK .sim format using the ng2vc converter.

    Tries, in order:
    1. pyopus.simulator.ng2vc  (if PyOPUS is installed with ng2vc support)
    2. ng2vc / ng2vc.py on the system PATH or next to the vacask binary
    """
    # Try PyOPUS built-in converter
    try:
        from pyopus.simulator import ng2vc as _m  # type: ignore[import]
        if hasattr(_m, "convert"):
            _m.convert(spice_file, sim_file)
            log.info("ng2vc conversion via PyOPUS OK: %s → %s", spice_file, sim_file)
            return
    except Exception:
        pass

    # Locate ng2vc script next to the vacask binary or on PATH
    vacask_bin = shutil.which("vacask")
    candidates = [
        shutil.which("ng2vc"),
        os.path.join(os.path.dirname(vacask_bin), "ng2vc") if vacask_bin else None,
        os.path.join(os.path.dirname(vacask_bin), "ng2vc.py") if vacask_bin else None,
    ]
    ng2vc_path = next((p for p in candidates if p and os.path.exists(p)), None)
    if ng2vc_path is None:
        raise RuntimeError(
            "ng2vc converter not found. Install PyOPUS or ensure ng2vc / ng2vc.py "
            "is on the system PATH alongside the vacask binary."
        )

    result = subprocess.run(
        [sys.executable, ng2vc_path, spice_file, sim_file],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ng2vc conversion failed: {result.stderr.strip()}")
    log.info("ng2vc conversion via script OK: %s → %s", spice_file, sim_file)


_RE_SANITISE = re.compile(r"[^a-zA-Z0-9_]")


def _sanitise_key(name: str) -> str:
    """Turn a SPICE signal name like v(out) into a Python identifier v_out_."""
    return _RE_SANITISE.sub("_", name)


def _parse_ascii_raw(raw_file: str) -> dict:
    """Minimal parser for SPICE ASCII .raw files. Returns {signal_name_lower: np.ndarray}."""
    import numpy as np

    var_names: list[str] = []
    rows: dict[str, list] = {}
    n_vars = 0
    in_variables = False
    in_values = False
    pending: list[float] = []

    with open(raw_file, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            ls = line.strip()
            lower = ls.lower()
            if lower.startswith("no. variables:"):
                n_vars = int(ls.split(":")[-1].strip())
            elif lower.startswith("no. points:"):
                pass  # informational only
            elif lower == "variables:":
                in_variables, in_values = True, False
            elif lower in ("values:", "binary:"):
                in_variables, in_values = False, True
                for nm in var_names:
                    rows[nm] = []
                if lower == "binary:":
                    log.warning("Binary .raw format detected – ASCII parser cannot read it. "
                                "Install PyOPUS for binary raw support.")
                    return {}
            elif in_variables:
                parts = ls.split()
                if len(parts) >= 2:
                    var_names.append(parts[1].lower())
            elif in_values and n_vars > 0:
                for tok in ls.split():
                    try:
                        pending.append(float(tok))
                    except ValueError:
                        pass
                # Flush complete rows
                while len(pending) >= n_vars:
                    row_vals = pending[:n_vars]
                    pending = pending[n_vars:]
                    for i, nm in enumerate(var_names):
                        if i < len(row_vals):
                            rows[nm].append(row_vals[i])

    return {k: np.array(v) for k, v in rows.items()}


def _read_raw_file(raw_file: str) -> "dict | None":
    """Read a VACASK/SPICE .raw output file → {signal_name_lower: np.ndarray}."""
    # Preferred: PyOPUS rawfile reader (handles binary + ASCII)
    try:
        from pyopus.simulator.rawfile import RawFile  # type: ignore[import]
        rf = RawFile(raw_file)
        out: dict = {}
        analyses = getattr(rf, "analyses", None) or [rf]
        for an in analyses:
            xvec = getattr(an, "xvec", None)
            xlabel = getattr(an, "xlabel", "time") or "time"
            if xvec is not None:
                out[xlabel.lower()] = xvec
            for sv in getattr(an, "yvec", []):
                out[sv.name.lower()] = sv.data
        if out:
            return out
    except Exception:
        pass

    # Fallback: minimal ASCII raw parser
    try:
        return _parse_ascii_raw(raw_file)
    except Exception as exc:
        log.warning("Could not parse raw file %s: %s", raw_file, exc)
        return None


def _eval_measure_expr(expr: str, results: dict):
    """Evaluate a measure expression string against a dict of signal numpy arrays.

    Delegates to SafeEvaluator.evaluate_spice_measure which:
    - sanitises SPICE signal names (v(out) → v_out_) in both namespace and expr
    - restricts evaluation to a numpy-enabled asteval sandbox (no import/exec/open)
    - provides db(), last(), first() helpers
    """
    from chipify.expression import default_evaluator
    return default_evaluator.evaluate_spice_measure(expr, results)


def _write_transient_tab(results: dict, signals: list, out_path: str) -> None:
    """Write transient signal vectors to a .tab file readable by _persist_transient().

    Uses the single-time-column layout that _persist_transient() handles:
        time  sig0  sig1  …
    """
    import numpy as np

    x_key = next((k for k in ("time", "frequency") if k in results),
                 next(iter(results), None))
    if x_key is None:
        return
    x_vec = np.asarray(results[x_key], dtype=float)
    cols = [x_vec]
    for sig in signals:
        vec = results.get(sig.lower(),
               results.get(_sanitise_key(sig.lower()),
               np.zeros_like(x_vec)))
        cols.append(np.asarray(vec, dtype=float))

    n = min(len(c) for c in cols) if cols else 0
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            for i in range(n):
                fh.write("  ".join(f"{c[i]:.6e}" for c in cols) + "\n")
    except Exception as exc:
        log.warning("Could not write transient tab %s: %s", out_path, exc)


def _vacask_extract_results(raw_file: str, test, tran_out_path: str):
    """Read VACASK .raw output, extract scalars, return (MY_DATA line, error).

    Scalar extraction order (first match wins for each value):
    1. Named signal in .raw matching the value name exactly — covers testbenches
       that use VACASK ``meas`` statements (same YAML format as ngspice).
    2. Explicit ``measure:`` expression in datasheet.yaml — for computed metrics.
    3. Neither → nan with a warning.
    """
    import numpy as np

    if not os.path.exists(raw_file):
        return None, "NO_RAW_FILE"

    results = _read_raw_file(raw_file)
    if results is None:
        return None, "RAW_PARSE_ERROR"

    tran_signals = getattr(test, "transient_signals", []) if test else []
    measure_exprs = getattr(test, "measure", {}) if test else {}
    value_lst = test.value_lst if test else []

    # Persist transient waveforms so _persist_transient() can convert them to CSV
    x_present = any(k in results for k in ("time", "frequency"))
    if tran_signals and tran_out_path and x_present:
        _write_transient_tab(results, tran_signals, tran_out_path)

    # Transient-only testbench
    if not value_lst:
        return "", None

    scalar_strs: list[str] = []
    for val_obj in value_lst:
        # 1. Direct .raw signal lookup by value name (works with VACASK meas statements
        #    — no measure: block needed in YAML, same format as ngspice)
        raw_val = (results.get(val_obj.name.lower())
                   or results.get(_sanitise_key(val_obj.name.lower())))
        if raw_val is not None:
            arr = np.asarray(raw_val, dtype=float)
            # Scalar meas result → use directly; vector → take last point
            scalar_strs.append(str(float(arr) if arr.ndim == 0 else float(arr.flat[-1])))
            continue

        # 2. Explicit measure: expression from YAML
        expr = measure_exprs.get(val_obj.name, "")
        if expr:
            try:
                val = _eval_measure_expr(expr, results)
                scalar_strs.append(str(float(val)))
                continue
            except Exception as exc:
                log.warning("Measure eval error for '%s': %s", val_obj.name, exc)
                return None, f"MEASURE_ERROR({val_obj.name}): {exc}"

        # 3. Nothing found
        log.warning(
            "No value found for '%s' in VACASK .raw output. "
            "Add a 'meas' statement in the testbench or a 'measure:' block in the YAML.",
            val_obj.name,
        )
        scalar_strs.append("nan")

    return "MY_DATA: " + " ".join(scalar_strs), None


# ── VACASK simulator engine ────────────────────────────────────────────────────

class VacaskSimulator(BaseSimulator):
    """Simulator engine that drives VACASK via subprocess, reads results via PyOPUS rawfile."""

    name = "vacask"

    def generate_test_template(self, test) -> str:
        cfg = app_config.load_config()
        source = cfg.get("vacask_netlist_source", "xschem")
        tb_path = _safe_tb_path(test.tb_path)

        if source == "ng2vc":
            # Generate ngspice netlist via Xschem, then convert to VACASK syntax
            run_xschem(tb_path)
            spice_file = os.path.join(settings.FAST_TMP, test.tb_path + ".spice")
            sim_file = os.path.join(settings.FAST_TMP, test.tb_path + ".sim")
            _run_ng2vc(spice_file, sim_file)
        else:
            # Preferred path: Xschem Spectre netlist directly consumable by VACASK.
            # If this fails (xschem build quirks), fall back to ng2vc conversion.
            sim_file = os.path.join(settings.FAST_TMP, test.tb_path + ".sim")
            try:
                _run_xschem_vacask(tb_path)
            except Exception as exc:
                log.warning(
                    "Direct Xschem→VACASK netlist failed (%s). Falling back to ng2vc.",
                    exc,
                )
                run_xschem(tb_path)
                spice_file = os.path.join(settings.FAST_TMP, test.tb_path + ".spice")
                _run_ng2vc(spice_file, sim_file)

        with open(sim_file, "r", encoding="utf-8") as fh:
            netlist = fh.read()

        return netlist

    def run(self, netlist: str, timeout_sec: int = 10,
            test=None, tran_out_path: str = "") -> tuple:
        cfg = app_config.load_config()
        vacask_binary = cfg.get("vacask_binary") or "vacask"
        custom_env = os.environ.copy()
        custom_env["OMP_NUM_THREADS"] = "1"

        pid = os.getpid()
        temp_sim_file = os.path.join(settings.FAST_TMP, f"sim_{pid}_vc.sim")
        # VACASK writes <stem>.raw beside the input file by default
        temp_raw_file = os.path.join(settings.FAST_TMP, f"sim_{pid}_vc.raw")
        temp_log_file = os.path.join(settings.FAST_TMP, f"sim_{pid}_vc.log")

        with open(temp_sim_file, "w", encoding="utf-8") as fh:
            fh.write(netlist)

        process = None
        try:
            with open(temp_log_file, "w") as log_fh:
                process = subprocess.Popen(
                    [vacask_binary, temp_sim_file],
                    stdout=log_fh,
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

            # ── Primary path: scan log for MY_DATA: (same as NgspiceSimulator) ──
            # Testbenches can emit MY_DATA: via VACASK's printf command:
            #   printf "MY_DATA: %g %g\n" gain bw
            # This makes the testbench+YAML format identical to the ngspice path.
            my_data_line = ""
            if os.path.exists(temp_log_file):
                with open(temp_log_file, "r") as lf:
                    for line in lf:
                        if line.startswith("MY_DATA:"):
                            my_data_line = line.strip()
                            break

            tran_signals = getattr(test, "transient_signals", []) if test else []
            if tran_signals and tran_out_path and os.path.exists(temp_raw_file):
                results = _read_raw_file(temp_raw_file)
                if results:
                    x_present = any(k in results for k in ("time", "frequency"))
                    if x_present:
                        _write_transient_tab(results, tran_signals, tran_out_path)

            if my_data_line:
                return my_data_line, None

            # ── Fallback: extract scalars from .raw file ──────────────────────
            # Used when the testbench saves named meas results or the YAML
            # defines explicit measure: expressions.
            return _vacask_extract_results(temp_raw_file, test, tran_out_path)

        except subprocess.CalledProcessError:
            err_msg = "CRASH"
            if os.path.exists(temp_log_file):
                with open(temp_log_file, "r") as lf:
                    err_msg = "".join(lf.readlines()[-5:]).strip()
            return None, f"CRASH: {err_msg}"

        except Exception as exc:
            log.exception("VacaskSimulator.run unexpected error: %s", exc)
            return None, f"CRASH: {exc}"
        finally:
            if process is not None and process.poll() is None:
                process.kill()
            for f_path in (temp_sim_file, temp_raw_file, temp_log_file):
                try:
                    os.remove(f_path)
                except OSError:
                    pass


def _persist_transient(tab_path: str, signals: list, dest_csv: str) -> None:
    """
    Convert an ngspice wrdata .tab file into a clean time-indexed CSV.

    ngspice wrdata writes 2*N columns for N signals:
      time_0 sig0_0  time_1 sig1_0  ...   (paired columns)

    If the file has N+1 columns instead (single time column), that layout
    is handled as the fallback.
    """
    try:
        df = pd.read_csv(tab_path, sep=r"\s+", header=None, comment="*")
        if df.empty:
            return
        ncols = len(df.columns)
        n_sigs = len(signals)
        result = pd.DataFrame()
        if ncols >= 2 * n_sigs and n_sigs > 0:
            # Paired layout: col 0=time, col 1=sig0, col 2=time(dup), col 3=sig1 …
            result["time"] = df.iloc[:, 0]
            for i, sig in enumerate(signals):
                col_idx = 2 * i + 1
                if col_idx < ncols:
                    result[sig] = df.iloc[:, col_idx]
        else:
            # Single time column layout
            cols = min(ncols - 1, n_sigs)
            result["time"] = df.iloc[:, 0]
            for i in range(cols):
                result[signals[i]] = df.iloc[:, i + 1]
        os.makedirs(os.path.dirname(dest_csv), exist_ok=True)
        result.to_csv(dest_csv, index=False)
    except Exception as exc:
        log.warning("Could not persist transient data %s → %s: %s", tab_path, dest_csv, exc)
    finally:
        try:
            os.remove(tab_path)
        except OSError:
            pass


def _simulate_single_case_with_engine(params, tests, engine: BaseSimulator,
                                      run_id: str = "", tran_dir: str = ""):
    sample = params.copy()
    sample['sim_error'] = "None"
    sample['run_id'] = run_id

    for test in tests:
        tran_signals = getattr(test, "transient_signals", [])
        pid = os.getpid()
        tb_safe = test.tb_path.replace("/", "__").replace("\\", "__")

        render_kwargs = dict(params)
        if tran_signals and tran_dir:
            tran_out_path = os.path.join(
                settings.FAST_TMP, f"sim_{pid}_{run_id}_{tb_safe}.tab"
            )
            render_kwargs["tran_out_path"] = tran_out_path
        else:
            tran_out_path = ""

        rendering = Template(test.template_str).render(**render_kwargs)
        sim_output, error_msg = engine.run(rendering, test=test, tran_out_path=tran_out_path)

        if error_msg:
            sample['sim_error'] = f"{test.tb_path}: {error_msg}"
            sample[f"{test.tb_path}_overall_pass"] = False
            for val_obj in test.value_lst:
                sample[val_obj.name] = float('nan')
                sample[f"{val_obj.name}_pass"] = False
            continue

        # Persist transient waveform data when available.
        if tran_signals and tran_dir and tran_out_path and os.path.exists(tran_out_path):
            dest_csv = os.path.join(tran_dir, f"run_{run_id}__{tb_safe}.csv")
            _persist_transient(tran_out_path, tran_signals, dest_csv)

        # Transient-only testbench: no scalar measurements defined → skip MY_DATA.
        if not test.value_lst:
            sample[f"{test.tb_path}_overall_pass"] = True
            continue

        if sim_output and sim_output.startswith("MY_DATA:"):
            clean_line = sim_output.replace("MY_DATA:", "").strip()
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
                    sample['sim_error'] = f"{test.tb_path}: INVALID_OUTPUT({val_str})"
                    all_passed = False

            sample[f"{test.tb_path}_overall_pass"] = all_passed
        else:
            sample['sim_error'] = f"{test.tb_path}: NO_MY_DATA_FOUND"
            sample[f"{test.tb_path}_overall_pass"] = False

    return sample


def simulate_single_case(args):
    params, tests, simulator_name, run_id, tran_dir = args
    engine = get_simulator_engine(simulator_name)
    return _simulate_single_case_with_engine(params, tests, engine, run_id, tran_dir)


def simulate_case_batch(batch_args):
    """Worker helper: process a batch of cases to reduce IPC overhead."""
    param_id_batch, tests, simulator_name, tran_dir = batch_args
    engine = get_simulator_engine(simulator_name)
    return [
        _simulate_single_case_with_engine(params, tests, engine, run_id, tran_dir)
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


def generate_templates(stim, engine: BaseSimulator) -> None:
    for test in stim.tests:
        if _is_aborted():
            raise InterruptedError("Aborted before netlist generation.")
        test.template_str = engine.generate_test_template(test)


def generate_cases(stim) -> list:
    param_names = stim.params.keys()
    param_values = stim.params.values()
    return [dict(zip(param_names, combo)) for combo in itertools.product(*param_values)]


def _assemble_result_df(rows: list, tran_dir: str) -> pd.DataFrame:
    """Build a normalized results DataFrame (matches GUI / CSV load semantics)."""
    from chipify.gui.services import data_loader as _dl

    df = pd.DataFrame(rows)
    df = _dl.normalise_sim_error(df)
    df = _dl.compute_global_pass(df)
    if tran_dir:
        df.attrs["tran_dir"] = tran_dir
    return df


def run_sim(stim, progress_callback=None, simulator=None, chunk_callback=None):
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
        # CLI --simulator flag (simulator arg) takes precedence over settings.json
        simulator_name = (simulator or cfg.get("simulator_engine") or "ngspice").strip().lower()
        engine = get_simulator_engine(simulator_name)
        log.info("Selected simulator engine: %s", engine.name)

        if _is_aborted():
            raise InterruptedError("Aborted before template generation.")
        log.info("Phase 2/3: generating Xschem templates...")
        generate_templates(stim, engine)

        if _is_aborted():
            raise InterruptedError("Aborted before RAM staging.")
        log.info("Phase 3/3: staging files to RAM disk...")
        stage_files_to_ram()

        if _is_aborted():
            raise InterruptedError("Aborted before pool start.")

        # Assign a stable zero-padded run_id to every parameter case.
        run_ids = [f"{i:06d}" for i in range(len(param_sets))]

        # Create the per-simulation transient store directory.
        sim_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        has_tran = any(getattr(t, "transient_signals", []) for t in stim.tests)
        if has_tran:
            tran_dir = os.path.join(settings.OUT_DIR, "tran_data", sim_timestamp)
            os.makedirs(tran_dir, exist_ok=True)
            log.info("Transient store: %s", tran_dir)
        else:
            tran_dir = ""

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
        # transient files to tran_dir with the correct run_id in the filename.
        chunk_size = _resolve_chunk_size(cfg, total_tasks, num_cores)
        param_id_pairs = list(zip(param_sets, run_ids))
        param_id_batches = list(_chunk_args(param_id_pairs, chunk_size))
        pending = [
            pool.apply_async(simulate_case_batch, ((batch, stim.tests, engine.name, tran_dir),))
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
                                            chunk_row_buffer, tran_dir
                                        )
                                        chunk_callback(chunk_df)
                                    except Exception:
                                        pass
                                    chunk_row_buffer = []
                        except (WorkerLostError, Exception) as exc:
                            if isinstance(exc, InterruptedError):
                                raise
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
                chunk_df = _assemble_result_df(chunk_row_buffer, tran_dir)
                chunk_callback(chunk_df)
            except Exception:
                pass
            chunk_row_buffer = []

        pool.close()
        pool.join()
        log.info("Pool finished cleanly. %d results collected.", len(results))

        result_df = _assemble_result_df(results, tran_dir)
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
