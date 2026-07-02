# Copyright (c) 2026 Santiago Hofwimmer
# simulator.py
import os
import re
import sys
import glob
import shutil
import tempfile
import itertools
import subprocess
import time
import logging
import datetime
from multiprocessing import get_context
from abc import ABC, abstractmethod

import pandas as pd
from tqdm import tqdm
from jinja2 import Template, StrictUndefined

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

def _staged_copy_is_stale(src: str, dest: str) -> bool:
    """True if *dest* is missing or differs from *src* (size or older mtime).

    ``shutil.copy2`` preserves mtime, so an up-to-date staged copy has the
    same size and an mtime within filesystem resolution of the source.
    """
    try:
        s = os.stat(src)
        d = os.stat(dest)
    except OSError:
        return True
    return s.st_size != d.st_size or s.st_mtime > d.st_mtime + 1.0


def stage_files_to_ram(engines=None) -> None:
    """Stage library/model files into FAST_TMP.

    Always copies the project's *.lib/*.mod/*.inc from WORK_DIR. Files are
    re-copied whenever the source changed — FAST_TMP isn't cleaned between
    runs, so a skip-if-exists policy would let a stale cached copy mask
    edits to model files. *engines* may be a single engine, an iterable of
    engines, or None; every engine exposing ``stage_extra_files()`` gets that
    hook run — used by VacaskSimulator to mirror OSDI compact-model objects so
    the netlist's ``load "*.osdi"`` directives resolve relative to FAST_TMP. A
    mixed-engine sweep therefore stages the extras for every engine it uses.
    """
    log.info("Staging library files to RAM disk: %s", settings.FAST_TMP)
    for pattern in ("*.lib", "*.mod", "*.inc"):
        for file_path in glob.glob(os.path.join(settings.WORK_DIR, pattern)):
            filename = os.path.basename(file_path)
            dest_path = os.path.join(settings.FAST_TMP, filename)
            if _staged_copy_is_stale(file_path, dest_path):
                try:
                    shutil.copy2(file_path, dest_path)
                    log.debug("Staged: %s", filename)
                except Exception as exc:
                    log.warning("Could not stage %s: %s", filename, exc)

    # Stage tb/xschemrc (project-local xschem rc, no leading dot) so xschem
    # picks up XSCHEM_LIBRARY_PATH etc. and can resolve the DUT during
    # netlisting. Overwrite each run — FAST_TMP isn't cleaned between runs,
    # so a stale cached copy would mask edits.
    xschemrc_src = os.path.join(settings.TB_DIR, "xschemrc")
    if os.path.isfile(xschemrc_src):
        xschemrc_dest = os.path.join(settings.FAST_TMP, "xschemrc")
        try:
            shutil.copy2(xschemrc_src, xschemrc_dest)
            log.info("Staged tb/xschemrc → %s", xschemrc_dest)
        except Exception as exc:
            log.warning("Could not stage tb/xschemrc: %s", exc)
    else:
        log.debug("No tb/xschemrc to stage (looked at %s)", xschemrc_src)

    if engines is None:
        staged: list = []
    elif isinstance(engines, BaseSimulator):
        staged = [engines]
    else:
        staged = list(engines)
    seen: set = set()
    for eng in staged:
        if eng is None or type(eng).__name__ in seen:
            continue
        seen.add(type(eng).__name__)
        if hasattr(eng, "stage_extra_files"):
            eng.stage_extra_files()


XSCHEM_DEFAULT_TIMEOUT_SEC = 60


def _read_log_tail(log_path: str, n_lines: int = 60) -> str:
    try:
        with open(log_path, "r") as lf:
            return "".join(lf.readlines()[-n_lines:]).strip()
    except OSError:
        return "<log unavailable>"


_XSCHEM_NETLIST_EXTS = (".spice", ".sim", ".spectre", ".scs", ".spc", ".sp", ".cdl", ".cir")


def _snapshot_dir(path: str) -> set:
    try:
        return set(os.listdir(path))
    except OSError:
        return set()


def _safe_rel(path: str) -> str:
    """``os.path.relpath`` that never raises.

    On Windows, relpath raises ValueError when *path* and the cwd are on
    different drives (e.g. temp on C:, project on D:); fall back to the
    absolute path rather than turning a log statement into a failure.
    """
    try:
        return os.path.relpath(path)
    except ValueError:
        return path


def run_xschem(
    xschem_file: str,
    netlist_mode: str = "spice",
    timeout_sec: int = XSCHEM_DEFAULT_TIMEOUT_SEC,
) -> None:
    """Generate a netlist from a schematic via Xschem in batch mode.

    netlist_mode:
      - "spice"   : ngspice-compatible netlist (final file: <stem>.spice)
      - "spectre" : Spectre-syntax netlist for VACASK (final file: <stem>.sim)

    Xschem's output extension depends on the build (often <stem>.spice
    regardless of netlist_type, sometimes .spectre or .scs). We snapshot the
    output dir before/after, take whatever new netlist xschem wrote, and
    rename it to the caller's expected name.
    """
    mode = (netlist_mode or "spice").strip().lower()
    if mode not in ("spice", "spectre"):
        raise ValueError(f"Unknown netlist_mode: {netlist_mode!r}")
    log.info("run_xschem: %s (mode=%s)", xschem_file, mode)

    stem = os.path.splitext(os.path.basename(xschem_file))[0]
    expected_ext = ".sim" if mode == "spectre" else ".spice"
    out_file = os.path.join(settings.FAST_TMP, stem + expected_ext)
    log_path = os.path.join(settings.FAST_TMP, stem + ".xschem.log")

    # `-n` alone doesn't always trigger the netlist write on every xschem
    # build (observed on 3.4.8RC: schematic loads, "Netlist mode: <default>"
    # is printed, then xschem exits rc=0 with no file). The explicit
    # `--spice` / `--spectre` format flag is what reliably both sets
    # netlist_type and triggers the action.
    # `-s` (simulate) is omitted: chipify runs the simulator itself.
    cmd = ['xschem', '-n']
    if mode == "spectre":
        cmd.append('--spectre')
    else:
        cmd.append('--spice')
    # -q (quit after batch) is mandatory — without it xschem stays open and
    # never returns. -x suppresses the X server attach.
    cmd += ['-q', '-x', '-o', settings.FAST_TMP, xschem_file]

    start_ts = time.time()

    process = None
    log.info("Xschem env: HOME=%s XSCHEM_SHAREDIR=%s PATH=%s cwd=%s",
             os.environ.get("HOME"), os.environ.get("XSCHEM_SHAREDIR"),
             os.environ.get("PATH", "")[:200], settings.PROJECT_ROOT)
    try:
        with open(log_path, "w") as log_fh:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=settings.PROJECT_ROOT,
            )
            # Send EOF immediately so xschem doesn't block on / get confused by
            # an inherited stdin handle (Qt GUI parents often hand the child a
            # closed or non-readable stdin). This is the portable replacement
            # for stdin=DEVNULL, which fails in containers without /dev/null.
            try:
                process.stdin.close()
            except Exception:
                pass
            log.info("Xschem PID=%d cmd=%s", process.pid, ' '.join(cmd))
            start = time.monotonic()
            timed_out = False
            while process.poll() is None:
                if _is_aborted():
                    process.kill()
                    raise InterruptedError("Aborted during Xschem netlist generation.")
                if time.monotonic() - start > timeout_sec:
                    process.kill()
                    try:
                        process.wait(timeout=5)
                    except Exception:
                        pass
                    timed_out = True
                    break
                time.sleep(0.2)

        if timed_out:
            tail = _read_log_tail(log_path)
            log.error(
                "Xschem timed out after %ds. cmd=%s\n--- xschem log tail (%s) ---\n%s\n--- end log tail ---",
                timeout_sec, ' '.join(cmd), log_path, tail,
            )
            raise RuntimeError(
                f"Xschem netlist generation timed out ({mode}, {timeout_sec}s). "
                f"See {log_path}. log_tail={tail}"
            )

        # Find anything xschem wrote: any netlist-extension file in FAST_TMP
        # or PROJECT_ROOT whose mtime is at/after start_ts. mtime-based
        # detection is more reliable than name-diff (catches overwrites of
        # files that already existed in the before-snapshot).
        def _modified_since(path: str, since: float) -> list:
            out = []
            try:
                entries = os.scandir(path)
            except OSError:
                return out
            with entries:
                for e in entries:
                    try:
                        if not e.is_file(follow_symlinks=False):
                            continue
                        if e.stat(follow_symlinks=False).st_mtime >= since - 1.0:
                            out.append(e.path)
                    except OSError:
                        continue
            return out

        # Scan both FAST_TMP (where -o points) and PROJECT_ROOT (cwd) just in
        # case xschem wrote relative to cwd despite the -o flag.
        scan_dirs = [settings.FAST_TMP, settings.PROJECT_ROOT]
        recent_files = []
        for d in scan_dirs:
            recent_files += _modified_since(d, start_ts)

        netlist_files = [p for p in recent_files
                         if any(p.lower().endswith(e) for e in _XSCHEM_NETLIST_EXTS)]
        preferred = [p for p in netlist_files
                     if os.path.splitext(os.path.basename(p))[0] == stem]
        chosen_path = (preferred[0] if preferred
                       else (netlist_files[0] if netlist_files else ""))

        log.info("xschem post-run scan: recent_files=%s netlist_files=%s chosen=%s",
                 [_safe_rel(p) for p in recent_files],
                 [_safe_rel(p) for p in netlist_files],
                 _safe_rel(chosen_path) if chosen_path else "<none>")

        if not chosen_path:
            tail = _read_log_tail(log_path)
            after = _snapshot_dir(settings.FAST_TMP)
            raise RuntimeError(
                f"Xschem ran (rc={process.returncode}) but wrote no netlist file. "
                f"recent_files={recent_files}. "
                f"FAST_TMP contents: {sorted(after)}. "
                f"See {log_path}. log_tail={tail}"
            )

        produced = chosen_path
        # Normalize whatever xschem wrote to the caller's expected filename.
        if produced != out_file:
            shutil.move(produced, out_file)
            log.info("Moved xschem output %s -> %s",
                     _safe_rel(produced), out_file)

        if process.returncode != 0:
            log.warning(
                "Xschem returned rc=%d but produced %s. Continuing.",
                process.returncode, out_file,
            )
        log.info("Xschem netlist generated OK (%s).", mode)
        try:
            os.remove(log_path)
        except OSError:
            pass
        return

    except InterruptedError:
        raise
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Xschem netlist generation failed ({mode}): {exc}") from exc
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
    def run(self, netlist: str, timeout_sec: int = 10, test=None,
            analysis_tab_paths: dict | None = None):
        """Execute one netlist and return (output_line, error_message).

        test                – the Test object for the current testbench (optional;
                              used by VacaskSimulator to evaluate measure
                              expressions and to know which analyses to extract).
        analysis_tab_paths  – ``{Analysis.kind: tab_path}`` mapping where the
                              engine should write per-analysis waveform data.
                              ngspice ignores this (paths are baked into the
                              rendered netlist via Jinja2); VacaskSimulator
                              uses it to dump signals from the .raw file.
        """
        raise NotImplementedError


def _inject_capture(netlist: str, injection: str) -> str:
    """Splice analysis-capture commands into the ngspice ``.control`` block.

    The capture (``setplot``/``wrdata`` …) must run after the testbench's own
    analysis but before the control block terminates. Many testbenches end their
    ``.control`` with ``quit`` (or ``exit``), which exits ngspice immediately — so
    inserting before ``.endc`` would place the capture *after* the quit, where it
    never runs (the silent Bode/AC "no data" bug). Insert before the first
    ``quit``/``exit`` inside the control block if present, else before ``.endc``.
    """
    ctrl_idx = netlist.find(".control")
    endc_idx = netlist.find(".endc")
    region = netlist[ctrl_idx:endc_idx] if (ctrl_idx != -1 and endc_idx != -1) else ""
    m = re.search(r"(?im)^[ \t]*(?:quit|exit)\b.*$", region)
    if m:
        pos = ctrl_idx + m.start()
        return netlist[:pos] + injection + "\n" + netlist[pos:]
    if endc_idx != -1:
        return netlist.replace(".endc", f"{injection}\n.endc", 1)
    return netlist + "\n" + injection + "\n"


class NgspiceSimulator(BaseSimulator):
    name = "ngspice"

    def generate_test_template(self, test) -> str:
        tb_path = _safe_tb_path(test.tb_path)
        run_xschem(tb_path)

        # run_xschem names its output after the schematic's basename, so a
        # nested tb_path like "sub/tb_x" still yields FAST_TMP/tb_x.spice.
        stem = os.path.splitext(os.path.basename(tb_path))[0]
        spice_file = os.path.join(settings.FAST_TMP, stem + ".spice")
        with open(spice_file, "r") as f:
            netlist = f.read()
            if ".control" in netlist:
                netlist = netlist.replace(".control", ".control\nset num_threads=1\n")
            else:
                netlist += "\n.control\nset num_threads=1\n.endc\n"

            # Chipify owns the MY_DATA: line now — strip any the testbench still
            # carries so we never emit two (the parser takes the first match,
            # which would silently win over ours). The testbench supplies the
            # let/meas vectors; chipify emits the echo from the datasheet.
            netlist = re.sub(r"(?im)^.*\bMY_DATA\b.*$\n?", "", netlist)

            # Build the .control injection: the scalar MY_DATA echo first (so
            # $&<name> resolves in the plot the testbench's own meas left
            # current), then the per-analysis wrdata/setplot capture (which
            # switches plots). _inject_capture splices this before the first
            # quit/exit (or .endc). The Jinja2 placeholders (tran_out_path /
            # dc_out_path / ac_out_path) are filled per worker call.
            inject_parts: list[str] = []

            # Scalar capture: echo MY_DATA:$&<name0> $&<name1> ... in value_lst
            # order. Each datasheet scalar key must name a vector the testbench
            # defines (via let/meas); the run() side parses these positionally,
            # so chipify now controls both ends and the order can't drift.
            value_lst = getattr(test, "value_lst", []) or []
            if value_lst:
                echoed = " ".join(f"$&{v.name}" for v in value_lst)
                inject_parts.append(f"echo MY_DATA:{echoed}")

            # setplot ensures wrdata pulls from the right vector store when
            # multiple analyses run in the same .control.
            analyses = getattr(test, "analyses", []) or []
            if analyses:
                inject_parts.append("\n".join(a.ngspice_inject() for a in analyses))

            if inject_parts:
                netlist = _inject_capture(netlist, "\n".join(inject_parts))

            return netlist

    def run(self, netlist: str, timeout_sec: int = 10, test=None,
            analysis_tab_paths: dict | None = None):
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


#: Engine names selectable per-testbench (datasheet ``engine:``) or globally
#: (``simulator_engine`` setting). Kept in sync with schema._SUPPORTED_ENGINES.
SUPPORTED_ENGINES = ("ngspice", "vacask")


def get_simulator_engine(simulator_name: str) -> BaseSimulator:
    key = (simulator_name or "ngspice").strip().lower()
    # Built here (not at module level) because VacaskSimulator is defined below.
    engines = {"ngspice": NgspiceSimulator, "vacask": VacaskSimulator}
    return engines.get(key, NgspiceSimulator)()


def resolve_engine_name(test, override: str | None = None,
                        cfg: dict | None = None) -> str:
    """Resolve the concrete engine name for *test* — most specific wins.

    Precedence: the testbench's own ``engine`` → the run *override* (CLI
    ``--simulator``) → the ``simulator_engine`` setting → ``ngspice``.
    """
    cfg = cfg if cfg is not None else {}
    name = (getattr(test, "engine", None) or override
            or cfg.get("simulator_engine") or "ngspice")
    return str(name).strip().lower()


def _read_run_log_tail(n: int = 25) -> str:
    """Return the tail of this worker's ngspice run log (best-effort, '' on failure).

    ``NgspiceSimulator.run`` writes the simulator's stdout/stderr to
    ``FAST_TMP/sim_<pid>.log`` for the current worker pid; right after ``run``
    returns it still holds that run's output. Used to explain why a declared
    analysis produced no output tab.
    """
    log_path = os.path.join(settings.FAST_TMP, f"sim_{os.getpid()}.log")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    return "".join(lines[-n:]).strip()


def _extract_ngspice_error(log_text: str) -> str:
    """Pull the most relevant single line from an ngspice log (best-effort).

    Prefers the first line mentioning an error / missing vector; otherwise the
    last non-empty line. Whitespace-collapsed and length-capped so it fits in a
    one-line result-row note / CSV cell.
    """
    lines = [ln.strip() for ln in log_text.splitlines() if ln.strip()]
    if not lines:
        return ""
    markers = ("error", "not available", "fatal", "can't", "cannot", "no such")
    pick = next((ln for ln in lines if any(m in ln.lower() for m in markers)), "")
    if not pick:
        pick = lines[-1]
    return " ".join(pick.split())[:200]


def _persist_analyses(analyses, analysis_tab_paths, analysis_dirs,
                      run_id, tb_safe, tb_path, sample):
    """Write each declared analysis's tab file into its per-run CSV.

    If an analysis was set up to capture (tab path + output dir both present) but
    produced no CSV — the tab is missing, or present-but-empty/unreadable so
    ``persist_to_csv`` writes nothing — record a one-line reason (including the
    ngspice error) on *sample* under ``<tb>__<kind>_capture``. Worker logging does
    not reach chipify.log (forkserver workers lack the file handler), so the
    result row is the reliable channel; ``run_sim`` surfaces these from the main
    process. This is what makes the silent Bode/AC "no data" case diagnosable.
    """
    for an in analyses:
        tab = analysis_tab_paths.get(an.kind, "")
        dest_dir = analysis_dirs.get(an.kind, "")
        if not (tab and dest_dir):
            continue

        reason = ""
        if not os.path.exists(tab):
            reason = (
                f"ngspice wrote no '{an.kind}1' tab to capture "
                f"(does the testbench run its .{an.kind} analysis?)"
            )
        else:
            dest_csv = os.path.join(dest_dir, f"run_{run_id}__{tb_safe}.csv")
            an.persist_to_csv(tab, dest_csv)
            if not os.path.exists(dest_csv):
                reason = (
                    f"ngspice wrote an empty/unreadable {an.kind} tab "
                    f"(capture vectors were empty)"
                )

        if reason:
            err = _extract_ngspice_error(_read_run_log_tail())
            note = f"{an.kind} produced no data - {reason}"
            if err:
                note += f" | ngspice: {err}"
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


# ── VACASK helpers ─────────────────────────────────────────────────────────────

def _resolve_vacask_bin(cfg: dict) -> "str | None":
    """Absolute path to the vacask binary, honoring the ``vacask_binary`` setting.

    An absolute configured path is used as-is (if it exists); otherwise the name
    is resolved on PATH. Returns None when nothing resolves.
    """
    name = (cfg.get("vacask_binary") or "vacask").strip()
    if os.path.isabs(name):
        return name if os.path.exists(name) else None
    return shutil.which(name)


def _ng2vc_search_paths(cfg: dict) -> list[str]:
    """Ordered candidate locations for the ng2vc converter script/binary.

    Beyond PATH and the vacask binary's own dir, this knows the VACASK install
    layout shipped in IIC-OSIC-TOOLS, where the binary lives in ``<prefix>/bin``
    but ng2vc sits under ``<prefix>/[…/]lib/vacask/python/ng2vc.py``.
    """
    cands: list[str] = []
    for name in ("ng2vc", "ng2vc.py"):
        p = shutil.which(name)
        if p:
            cands.append(p)

    vacask_bin = _resolve_vacask_bin(cfg)
    if vacask_bin:
        bindir = os.path.dirname(os.path.realpath(vacask_bin))
        prefix = os.path.dirname(bindir)          # <prefix>/bin/vacask → <prefix>
        cands += [
            os.path.join(bindir, "ng2vc.py"),
            os.path.join(bindir, "ng2vc"),
            # Observed VACASK / IIC-OSIC-TOOLS layout:
            #   <prefix>/vacask/lib/vacask/python/ng2vc.py
            os.path.join(prefix, "vacask", "lib", "vacask", "python", "ng2vc.py"),
            os.path.join(prefix, "lib", "vacask", "python", "ng2vc.py"),
        ]
    return cands


def _resolve_ng2vc(cfg: dict) -> "str | None":
    """Locate the ng2vc converter. The explicit ``ng2vc_binary`` setting wins;
    otherwise fall back to PATH / vacask-relative discovery (`_ng2vc_search_paths`).
    Returns the path (which the caller verifies exists) or None."""
    explicit = (cfg.get("ng2vc_binary") or "").strip()
    if explicit:
        return explicit
    return next((p for p in _ng2vc_search_paths(cfg) if os.path.exists(p)), None)


def _ng2vc_argv0(ng2vc_path: str) -> list[str]:
    """Launch prefix for ng2vc: Python scripts run under our interpreter (so the
    sibling ``ng2vclib`` package resolves via the script dir on sys.path); a
    native binary is executed directly."""
    return [sys.executable, ng2vc_path] if ng2vc_path.endswith(".py") else [ng2vc_path]


def _run_ng2vc(spice_file: str, sim_file: str) -> None:
    """Convert an ngspice netlist to VACASK .sim format using the ng2vc converter.

    Resolution order:
    1. ``pyopus.simulator.ng2vc.convert`` — only if that exact API exists; real
       errors are surfaced (logged), not silently swallowed.
    2. An ng2vc script/binary from the ``ng2vc_binary`` setting, PATH, or the
       VACASK install layout next to the vacask binary (`_resolve_ng2vc`).

    The external converter is invoked tolerantly: VACASK's ng2vc may take the
    output file as a second positional **or** write the netlist to stdout, so we
    try the output-arg form first and fall back to capturing stdout.
    """
    cfg = app_config.load_config()

    # 1. PyOPUS in-process converter — only when the API is actually present.
    try:
        from pyopus.simulator import ng2vc as _m  # type: ignore[import]
    except Exception:
        _m = None
    if _m is not None and hasattr(_m, "convert"):
        try:
            _m.convert(spice_file, sim_file)
            log.info("ng2vc conversion via PyOPUS OK: %s → %s", spice_file, sim_file)
            return
        except Exception as exc:  # noqa: BLE001 — diagnose, then fall back to the script
            log.warning("PyOPUS ng2vc.convert failed (%s); trying ng2vc script.", exc)

    # 2. External ng2vc script / binary.
    ng2vc_path = _resolve_ng2vc(cfg)
    if not ng2vc_path:
        raise RuntimeError(
            "ng2vc converter not found. Set 'ng2vc_binary' in settings to your "
            "ng2vc(.py) path (e.g. .../lib/vacask/python/ng2vc.py), add it to PATH, "
            "or install PyOPUS. Searched: "
            + ", ".join(_ng2vc_search_paths(cfg) or ["<nothing — vacask binary not found>"])
        )
    if not os.path.exists(ng2vc_path):
        raise RuntimeError(f"Configured ng2vc_binary does not exist: {ng2vc_path!r}")

    argv0 = _ng2vc_argv0(ng2vc_path)

    def _attempt(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(argv0 + args, capture_output=True, text=True, timeout=120)

    # Form A: ng2vc <in> <out>  (writes the .sim itself).
    res_a = _attempt([spice_file, sim_file])
    if res_a.returncode == 0 and os.path.isfile(sim_file) and os.path.getsize(sim_file) > 0:
        log.info("ng2vc conversion via script OK: %s → %s", ng2vc_path, sim_file)
        return

    # Form B: ng2vc <in>  (writes the netlist to stdout).
    res_b = _attempt([spice_file])
    if res_b.returncode == 0 and res_b.stdout.strip():
        with open(sim_file, "w", encoding="utf-8") as fh:
            fh.write(res_b.stdout)
        log.info("ng2vc conversion via script (stdout) OK: %s → %s", ng2vc_path, sim_file)
        return

    err = (res_a.stderr or "").strip() or (res_b.stderr or "").strip() or "(no stderr output)"
    # Show the TAIL of the traceback — a Python traceback's actual exception
    # message is on its last line, so head-truncation would hide the real cause.
    err_tail = "\n".join(err.splitlines()[-12:])[-1000:]
    raise RuntimeError(
        f"ng2vc conversion failed using {ng2vc_path} "
        f"(rc[in,out]={res_a.returncode}, rc[in→stdout]={res_b.returncode}):\n{err_tail}"
    )


_RE_SANITISE = re.compile(r"[^a-zA-Z0-9_]")


def _sanitise_key(name: str) -> str:
    """Turn a SPICE signal name like v(out) into a Python identifier v_out_."""
    return _RE_SANITISE.sub("_", name)


def _parse_raw_token(tok: str):
    """Parse one ASCII raw-file value token.

    Real values are plain floats; complex values are written as ``re,im``.
    Returns float, complex, or None if the token is not numeric.
    """
    if "," in tok:
        re_s, _, im_s = tok.partition(",")
        try:
            return complex(float(re_s), float(im_s))
        except ValueError:
            return None
    try:
        return float(tok)
    except ValueError:
        return None


def _parse_ascii_raw(raw_file: str) -> dict:
    """Parse a SPICE-format .raw file (binary or ASCII).

    Handles the format ngspice and vacask both write: an ASCII header
    (Title/Plotname/Flags/No. Variables/No. Points), a Variables section,
    then either ``Values:`` (ASCII) or ``Binary:`` followed by little-endian
    float64 data (or complex128 if Flags contains ``complex``).
    """
    import numpy as np

    var_names: list[str] = []
    n_vars = 0
    n_points = 0
    is_complex = False

    with open(raw_file, "rb") as fh:
        section: "str | None" = None
        while True:
            line = fh.readline()
            if not line:
                return {}
            ls = line.decode("utf-8", errors="replace").strip()
            lower = ls.lower()

            if lower.startswith("flags:"):
                is_complex = "complex" in lower
            elif lower.startswith("no. variables:"):
                try:
                    n_vars = int(ls.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
            elif lower.startswith("no. points:"):
                try:
                    n_points = int(ls.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
            elif lower == "variables:":
                section = "variables"
            elif lower == "values:":
                section = "ascii_values"
                break
            elif lower == "binary:":
                section = "binary"
                break
            elif section == "variables":
                # Variable lines: "<idx>\t<name>\t<type>"
                parts = ls.split()
                if len(parts) >= 2:
                    var_names.append(parts[1].lower())

        if section == "binary":
            if n_vars <= 0 or n_points <= 0 or not var_names:
                return {}
            dtype = np.dtype("<c16") if is_complex else np.dtype("<f8")
            count = n_vars * n_points
            blob = fh.read(count * dtype.itemsize)
            data = np.frombuffer(blob, dtype=dtype)
            if data.size != count:
                log.warning(
                    "Binary .raw truncated: expected %d values (%d vars x %d points), got %d.",
                    count, n_vars, n_points, data.size,
                )
                return {}
            data = data.reshape(n_points, n_vars)
            return {var_names[i]: data[:, i].copy()
                    for i in range(min(n_vars, len(var_names)))}

        if section == "ascii_values":
            if n_vars <= 0:
                return {}
            values: list = []
            for raw_line in fh:
                ls = raw_line.decode("utf-8", errors="replace").strip()
                for tok in ls.split():
                    num = _parse_raw_token(tok)
                    if num is not None:
                        values.append(num)

            # The SPICE ASCII format prefixes every point with its running
            # index ("0\t<v0>\n\t<v1>…"), giving n_vars+1 tokens per point.
            # Some writers omit the index; detect which layout we have, using
            # the declared point count when available and a 0,1,2,… index
            # heuristic otherwise.
            def _looks_indexed(stride: int) -> bool:
                idx_toks = values[::stride]
                return all(
                    isinstance(v, float) and v.is_integer() and int(v) == i
                    for i, v in enumerate(idx_toks)
                )

            n_tok = len(values)
            stride_idx = n_vars + 1
            if n_points > 0 and n_tok == n_points * stride_idx:
                indexed = True
            elif n_points > 0 and n_tok == n_points * n_vars:
                indexed = False
            elif n_tok % stride_idx == 0 and _looks_indexed(stride_idx):
                indexed = True
            elif n_tok % n_vars == 0:
                indexed = False
            else:
                log.warning(
                    "ASCII raw %s: %d value tokens do not align with %d variables.",
                    raw_file, n_tok, n_vars,
                )
                return {}

            stride = stride_idx if indexed else n_vars
            offset = 1 if indexed else 0
            rows: dict[str, list] = {nm: [] for nm in var_names}
            for start in range(0, n_tok - stride + 1, stride):
                row_vals = values[start + offset: start + stride]
                for i, nm in enumerate(var_names):
                    if i < len(row_vals):
                        rows[nm].append(row_vals[i])
            return {k: np.array(v) for k, v in rows.items() if v}

    return {}


def _classify_analysis_kind(xlabel: str, plotname: str = "") -> str:
    """Map a raw-file xlabel / plotname to one of our Analysis.kind values."""
    xl = (xlabel or "").lower()
    pn = (plotname or "").lower()
    if "freq" in xl or "ac" in pn:
        return "ac"
    if "time" in xl or "tran" in pn:
        return "transient"
    return "dc"


def _read_raw_file(raw_file: str) -> "dict | None":
    """Read a SPICE-format .raw → {analysis_kind: {signal_name_lower: np.ndarray}}.

    The bucket for each analysis kind also contains a sentinel ``"__x__"`` key
    holding the X-axis vector (time / frequency / sweep parameter) so callers
    don't need to know the X variable's name.

    Returns None if no analyses could be parsed at all. Empty dict on parse
    failure with no error.
    """
    # Preferred: PyOPUS rawfile reader (handles binary + ASCII)
    try:
        from pyopus.simulator.rawfile import RawFile  # type: ignore[import]
    except ImportError as exc:
        log.warning(
            "pyopus.simulator.rawfile import failed: %s. "
            "Vacask .raw files are typically binary (spectre format); install pyopus "
            "to parse them. Falling back to ASCII-only parser.",
            exc,
        )
    else:
        try:
            rf = RawFile(raw_file)
            buckets: dict[str, dict] = {}
            analyses = getattr(rf, "analyses", None) or [rf]
            for an in analyses:
                xvec = getattr(an, "xvec", None)
                xlabel = getattr(an, "xlabel", "") or ""
                plotname = (getattr(an, "name", "")
                            or getattr(an, "plotname", "")
                            or "")
                kind = _classify_analysis_kind(xlabel, plotname)
                bucket = buckets.setdefault(kind, {})
                if xvec is not None:
                    bucket["__x__"] = xvec
                    if xlabel:
                        bucket[xlabel.lower()] = xvec
                for sv in getattr(an, "yvec", []):
                    bucket[sv.name.lower()] = sv.data
            if buckets:
                return buckets
            log.warning("pyopus parsed %s but produced no signals.", raw_file)
        except Exception:
            log.warning("pyopus failed to parse %s; trying ASCII fallback.",
                        raw_file, exc_info=True)

    # Fallback: built-in SPICE-format parser (handles binary + ASCII).
    # The ASCII fallback can only see one analysis at a time; classify by
    # looking for time / frequency in the column names.
    try:
        parsed = _parse_ascii_raw(raw_file)
    except Exception:
        log.warning("Could not parse raw file %s.", raw_file, exc_info=True)
        return None
    if not parsed:
        log.warning("Raw file %s parsed to 0 signals — unknown format. "
                    "Expected ngspice/vacask SPICE rawfile (Title/Variables/Binary).",
                    raw_file)
        return None

    # Detect X-axis column and classify
    xlabel = ""
    for cand in ("time", "frequency", "freq"):
        if cand in parsed:
            xlabel = cand
            break
    if not xlabel:
        # First inserted column is the X axis for sweep analyses
        xlabel = next(iter(parsed), "")
    kind = _classify_analysis_kind(xlabel)
    bucket = dict(parsed)
    if xlabel and xlabel in bucket:
        bucket["__x__"] = bucket[xlabel]
    return {kind: bucket}


def _eval_measure_expr(expr: str, results: dict):
    """Evaluate a measure expression string against a dict of signal numpy arrays.

    Delegates to SafeEvaluator.evaluate_spice_measure which:
    - sanitises SPICE signal names (v(out) → v_out_) in both namespace and expr
    - restricts evaluation to a numpy-enabled asteval sandbox (no import/exec/open)
    - provides db(), last(), first() helpers
    """
    from chipify.expression import default_evaluator
    return default_evaluator.evaluate_spice_measure(expr, results)


def _vacask_write_analysis_tabs(buckets: dict, test, analysis_tab_paths: dict) -> None:
    """For every declared analysis on *test*, ask it to serialise its signals
    from the matching .raw bucket into the worker-private tab file path.

    *buckets* is the per-kind dict returned by ``_read_raw_file``.
    *analysis_tab_paths* is ``{kind: tab_path}`` from the worker driver.
    """
    if not buckets or not analysis_tab_paths:
        return
    for an in getattr(test, "analyses", []) or []:
        tab = analysis_tab_paths.get(an.kind, "")
        bucket = buckets.get(an.kind)
        if tab and bucket:
            try:
                an.write_tab_from_raw(bucket, tab)
            except Exception as exc:
                log.warning("write_tab_from_raw failed for %s: %s", an.kind, exc)


def _vacask_extract_results(raw_file: str, test, analysis_tab_paths: dict):
    """Read VACASK .raw output, extract scalars, return (MY_DATA line, error).

    Scalar extraction order (first match wins for each value):
    1. Named signal in the transient bucket matching the value name exactly —
       covers testbenches that use VACASK ``meas`` statements.
    2. Explicit ``measure:`` expression in datasheet.yaml — for computed metrics.
    3. Neither → nan with a warning.
    """
    import numpy as np

    if not os.path.exists(raw_file):
        return None, "NO_RAW_FILE"

    buckets = _read_raw_file(raw_file)
    if buckets is None:
        return None, "RAW_PARSE_ERROR"

    measure_exprs = getattr(test, "measure", {}) if test else {}
    value_lst = test.value_lst if test else []

    log.info("vacask .raw analyses: %s",
             {k: sorted(v.keys()) for k, v in buckets.items()})

    # Persist every declared analysis to its worker-private tab file.
    _vacask_write_analysis_tabs(buckets, test, analysis_tab_paths or {})

    # Scalar values are evaluated against the transient bucket only.
    # (matches the "Transient only" measure-source choice in the design.)
    scalar_bucket = buckets.get("transient") or next(iter(buckets.values()), {})

    # Transient-only testbench
    if not value_lst:
        return "", None

    available = sorted(scalar_bucket.keys())
    scalar_strs: list[str] = []
    n_resolved = 0
    for val_obj in value_lst:
        # 1. Direct .raw signal lookup by value name (works with VACASK meas
        #    statements and direct node-voltage reads). Try a handful of
        #    common naming variants because different raw formats label
        #    node voltages differently (spectre: "out", ngspice: "v(out)").
        name = val_obj.name.lower()
        candidates = (
            name,
            _sanitise_key(name),
            f"v({name})",
            _sanitise_key(f"v({name})"),
            f"i({name})",
            _sanitise_key(f"i({name})"),
        )
        raw_val = next(
            (scalar_bucket[c] for c in candidates if c in scalar_bucket),
            None,
        )
        if raw_val is not None:
            arr = np.asarray(raw_val, dtype=float)
            # Scalar meas result → use directly; vector → take last point
            scalar_strs.append(str(float(arr) if arr.ndim == 0 else float(arr.flat[-1])))
            n_resolved += 1
            continue

        # 2. Explicit measure: expression from YAML
        expr = measure_exprs.get(val_obj.name, "")
        if expr:
            try:
                val = _eval_measure_expr(expr, scalar_bucket)
                scalar_strs.append(str(float(val)))
                n_resolved += 1
                continue
            except Exception as exc:
                log.warning("Measure eval error for '%s': %s", val_obj.name, exc)
                return None, f"MEASURE_ERROR({val_obj.name}): {exc}"

        # 3. Nothing found — name it AND list what the .raw actually contains, so
        #    the naming mismatch is diagnosable (worker logs don't reach the file).
        log.warning(
            "No value found for '%s' in VACASK .raw. Available signals: %s. "
            "Add a 'meas' statement in the testbench or a 'measure:' block in the YAML.",
            val_obj.name, available,
        )
        scalar_strs.append("nan")

    # If not a single requested value resolved, the row was silently all-NaN
    # before. Surface it as an error that names the signals the .raw *does*
    # carry, so the right value/measure names are obvious from the result table.
    if n_resolved == 0:
        return None, (
            f"NO_MATCHING_SIGNALS: none of {[v.name for v in value_lst]} found "
            f"in VACASK .raw; available signals: {available[:40]}"
        )

    return "MY_DATA: " + " ".join(scalar_strs), None


# ── VACASK simulator engine ────────────────────────────────────────────────────

class VacaskSimulator(BaseSimulator):
    """Simulator engine that drives VACASK via subprocess, reads results via PyOPUS rawfile."""

    name = "vacask"

    def stage_extra_files(self) -> None:
        """Mirror the PDK's *.osdi compact-model objects into FAST_TMP.

        VACASK netlists generated by xschem reference OSDI files with relative
        paths, e.g. ``load "resistor.osdi"``. Since the simulator runs with
        cwd=FAST_TMP, the OSDI files must be present there. Symlink when
        possible, fall back to copy.
        """
        cfg = app_config.load_config()
        pdk_dir = cfg.get("vacask_pdk_dir") or "/foss/pdks/ihp-sg13g2/libs.tech/vacask"
        osdi_dir = os.path.join(pdk_dir, "osdi")
        if not os.path.isdir(osdi_dir):
            log.warning(
                "vacask osdi dir not found: %s — netlist 'load \"*.osdi\"' "
                "directives will fail. Set 'vacask_pdk_dir' in settings.",
                osdi_dir,
            )
            return

        staged = 0
        for filename in os.listdir(osdi_dir):
            if not filename.endswith(".osdi"):
                continue
            src = os.path.join(osdi_dir, filename)
            dest = os.path.join(settings.FAST_TMP, filename)
            if os.path.lexists(dest):
                continue
            try:
                os.symlink(src, dest)
            except OSError:
                try:
                    shutil.copy2(src, dest)
                except Exception as exc:
                    log.warning("Could not stage osdi %s: %s", filename, exc)
                    continue
            staged += 1
        log.info("Staged %d vacask .osdi files from %s into %s",
                 staged, osdi_dir, settings.FAST_TMP)

    def generate_test_template(self, test) -> str:
        cfg = app_config.load_config()
        source = cfg.get("vacask_netlist_source", "xschem")
        tb_path = _safe_tb_path(test.tb_path)
        # run_xschem names its output after the schematic's basename (nested
        # tb_path like "sub/tb_x" yields FAST_TMP/tb_x.<ext>).
        stem = os.path.splitext(os.path.basename(tb_path))[0]

        if source == "ng2vc":
            # Generate ngspice netlist via Xschem, then convert to VACASK syntax
            run_xschem(tb_path)
            spice_file = os.path.join(settings.FAST_TMP, stem + ".spice")
            sim_file = os.path.join(settings.FAST_TMP, stem + ".sim")
            _run_ng2vc(spice_file, sim_file)
        else:
            # User picked xschem: produce the Spectre netlist directly via xschem.
            # No silent fallback — switch the setting to "ng2vc" to opt into that path.
            sim_file = os.path.join(settings.FAST_TMP, stem + ".sim")
            run_xschem(tb_path, netlist_mode="spectre")

        with open(sim_file, "r", encoding="utf-8") as fh:
            netlist = fh.read()

        return netlist

    def run(self, netlist: str, timeout_sec: int = 10,
            test=None, analysis_tab_paths: dict | None = None) -> tuple:
        cfg = app_config.load_config()
        analysis_tab_paths = analysis_tab_paths or {}
        vacask_binary = cfg.get("vacask_binary") or "vacask"
        custom_env = os.environ.copy()
        custom_env["OMP_NUM_THREADS"] = "1"

        pid = os.getpid()
        # VACASK names its .raw output after the analysis (e.g. `analysis nmos
        # op` → nmos.raw), so concurrent workers running in the same dir would
        # clobber each other. Each invocation gets its own subdir, with the
        # parent FAST_TMP contents symlinked in so OSDI / model loads still
        # resolve relative to cwd.
        workdir = tempfile.mkdtemp(prefix=f"vc_{pid}_", dir=settings.FAST_TMP)
        temp_sim_file = os.path.join(workdir, "sim.sim")
        temp_log_file = os.path.join(workdir, "sim.log")
        temp_raw_file = ""  # resolved post-run by scanning workdir for *.raw

        # Make staged files (osdi, libs, models) visible inside the workdir.
        for fname in os.listdir(settings.FAST_TMP):
            if fname == os.path.basename(workdir):
                continue
            src = os.path.join(settings.FAST_TMP, fname)
            if not (os.path.isfile(src) or os.path.islink(src)):
                continue
            dest = os.path.join(workdir, fname)
            try:
                os.symlink(src, dest)
            except OSError:
                try:
                    shutil.copy2(src, dest)
                except OSError:
                    pass

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
                    cwd=workdir,
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

            # Vacask wrote its .raw somewhere in our private workdir. Take it.
            raw_candidates = sorted(
                f for f in os.listdir(workdir) if f.endswith(".raw")
            )
            if raw_candidates:
                temp_raw_file = os.path.join(workdir, raw_candidates[0])
                if len(raw_candidates) > 1:
                    log.warning("Multiple .raw files from vacask: %s — picked %s",
                                raw_candidates, raw_candidates[0])
            else:
                # No .raw produced even though vacask exited 0 — preserve the
                # log so the user can see what vacask actually did.
                self._preserve_vacask_log(temp_log_file, reason="no_raw")

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

            # When a MY_DATA: line is present we still need to write the per-
            # analysis tab files so the GUI sees the waveforms. Without it we
            # also need to extract scalars from the .raw — done in one call.
            if my_data_line:
                if analysis_tab_paths and os.path.exists(temp_raw_file):
                    buckets = _read_raw_file(temp_raw_file)
                    _vacask_write_analysis_tabs(buckets or {}, test,
                                                analysis_tab_paths)
                return my_data_line, None

            # ── Fallback: extract scalars from .raw file ──────────────────────
            # Used when the testbench saves named meas results or the YAML
            # defines explicit measure: expressions.
            return _vacask_extract_results(temp_raw_file, test, analysis_tab_paths)

        except subprocess.CalledProcessError:
            err_msg = "CRASH"
            saved_log = ""
            if os.path.exists(temp_log_file):
                with open(temp_log_file, "r") as lf:
                    err_msg = "".join(lf.readlines()[-5:]).strip()
                try:
                    os.makedirs(settings.OUT_DIR, exist_ok=True)
                    saved_log = os.path.join(
                        settings.OUT_DIR,
                        f"vacask_crash_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.log",
                    )
                    shutil.copy2(temp_log_file, saved_log)
                    log.error("vacask crash. Saved log: %s", saved_log)
                except Exception as copy_exc:
                    log.warning("Could not preserve vacask crash log: %s", copy_exc)
                    saved_log = ""
            suffix = f" (full log: {saved_log})" if saved_log else ""
            return None, f"CRASH: {err_msg}{suffix}"

        except Exception as exc:
            log.exception("VacaskSimulator.run unexpected error: %s", exc)
            return None, f"CRASH: {exc}"
        finally:
            if process is not None and process.poll() is None:
                process.kill()
            try:
                shutil.rmtree(workdir, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _preserve_vacask_log(temp_log_file: str, reason: str) -> str:
        """Copy a vacask log into OUT_DIR so it survives workdir cleanup."""
        if not os.path.exists(temp_log_file):
            return ""
        try:
            os.makedirs(settings.OUT_DIR, exist_ok=True)
            dest = os.path.join(
                settings.OUT_DIR,
                f"vacask_{reason}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.log",
            )
            shutil.copy2(temp_log_file, dest)
            log.warning("vacask produced no .raw — saved log: %s", dest)
            return dest
        except Exception as exc:
            log.warning("Could not preserve vacask log: %s", exc)
            return ""


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
    run on its own engine within the same case.
    """
    analysis_dirs = analysis_dirs or {}
    sample = params.copy()
    sample['sim_error'] = "None"
    sample['run_id'] = run_id

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
            tab = os.path.join(
                settings.FAST_TMP,
                f"sim_{pid}_{run_id}_{tb_safe}_{an.kind}.tab",
            )
            render_kwargs[an.jinja_var()] = tab
            analysis_tab_paths[an.kind] = tab

        rendering = Template(test.template_str, undefined=StrictUndefined).render(**render_kwargs)
        sim_output, error_msg = engine.run(
            rendering, test=test, analysis_tab_paths=analysis_tab_paths,
        )

        if error_msg:
            sample['sim_error'] = f"{test.tb_path}: {error_msg}"
            sample[f"{test.tb_path}_overall_pass"] = False
            for val_obj in test.value_lst:
                sample[val_obj.name] = float('nan')
                sample[f"{val_obj.name}_pass"] = False
            continue

        # Persist every analysis's tab file into its destination CSV (and surface
        # any analysis that ran but produced no output — see _persist_analyses).
        _persist_analyses(
            analyses, analysis_tab_paths, analysis_dirs,
            run_id, tb_safe, test.tb_path, sample,
        )

        # Transient-only testbench: no scalar measurements defined → skip MY_DATA.
        if not test.value_lst:
            sample[f"{test.tb_path}_overall_pass"] = True
            _eval_scalar_measures(test, sample, params)
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
    engine_cache: dict[str, BaseSimulator] = {}

    def _engine_for(test) -> BaseSimulator:
        name = (getattr(test, "engine", None) or "ngspice").strip().lower()
        if name not in engine_cache:
            engine_cache[name] = get_simulator_engine(name)
        return engine_cache[name]

    return [
        _simulate_single_case(params, tests, _engine_for, run_id, analysis_dirs)
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


def generate_templates(stim, templates_dir: str = "") -> None:
    """Populate ``test.template_str`` for every test in *stim*.

    Each testbench is rendered with **its own** engine (``test.engine``, resolved
    by run_sim), so a datasheet can mix engines. If a testbench's netlist can't
    be produced (e.g. its engine is unavailable), the failure is recorded on
    ``test.template_error`` and that testbench's runs fail individually — the rest
    of the sweep continues.

    If *templates_dir* is set, read pre-rendered xschem outputs from
    ``<templates_dir>/<safe_tb_path>.spice`` (``.sim`` for vacask) instead of
    invoking xschem locally — useful for re-running a sweep against netlists
    that were already generated.
    """
    engine_cache: dict[str, BaseSimulator] = {}

    def _engine_for(test) -> BaseSimulator:
        name = (getattr(test, "engine", None) or "ngspice").strip().lower()
        if name not in engine_cache:
            engine_cache[name] = get_simulator_engine(name)
        return engine_cache[name]

    for test in stim.tests:
        if _is_aborted():
            raise InterruptedError("Aborted before netlist generation.")
        test.template_error = None
        engine = _engine_for(test)
        ext = ".sim" if engine.name == "vacask" else ".spice"
        try:
            if templates_dir:
                safe = test.tb_path.replace("/", "__").replace("\\", "__")
                fp = os.path.join(templates_dir, safe + ext)
                with open(fp, "r", encoding="utf-8") as fh:
                    test.template_str = fh.read()
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
    for kind, d in (analysis_dirs or {}).items():
        if not d:
            continue
        targets = [os.path.join(settings.OUT_DIR, "analysis_data", kind, ".latest")]
        if kind == "transient":
            targets.append(os.path.join(settings.OUT_DIR, "tran_data", ".latest"))
        for ptr in targets:
            try:
                os.makedirs(os.path.dirname(ptr), exist_ok=True)
                with open(ptr, "w", encoding="utf-8") as fh:
                    fh.write(d)
            except Exception as exc:
                log.warning("Could not write %s pointer %s: %s", kind, ptr, exc)


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
                d = os.path.join(
                    settings.OUT_DIR, "analysis_data", kind, sim_timestamp,
                )
                os.makedirs(d, exist_ok=True)
                analysis_dirs[kind] = d
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
