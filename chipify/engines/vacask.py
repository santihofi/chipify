# Copyright (c) 2026 Santiago Hofwimmer
"""
vacask.py – VACASK simulator engine.

Netlists come either directly from xschem (``spectre`` mode) or via the
ng2vc ngspice→VACASK converter; results are read from the SPICE-format
.raw file (:mod:`chipify.engines.rawfile`) or a ``MY_DATA:`` printf line,
matching the ngspice contract.
"""
from __future__ import annotations

import datetime
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from chipify import app_config, settings
from chipify.engines.abort import is_aborted
from chipify.engines.base import BaseSimulator
from chipify.engines.rawfile import read_raw_file as _read_raw_file
from chipify.engines.rawfile import sanitise_key as _sanitise_key
from chipify.engines.staging import staged_copy_is_stale
from chipify.engines.xschem import run_xschem, safe_tb_path

log = logging.getLogger("chipify.engines.vacask")


# ── ng2vc converter resolution ────────────────────────────────────────────────

def _resolve_vacask_bin(cfg: dict) -> "str | None":
    """Absolute path to the vacask binary, honoring the ``vacask_binary`` setting.

    An absolute configured path is used as-is (if it exists); otherwise the name
    is resolved on PATH. Returns None when nothing resolves.
    """
    name = (cfg.get("vacask_binary") or "vacask").strip()
    if Path(name).is_absolute():
        return name if Path(name).exists() else None
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
        # os.path.realpath (not Path.resolve) keeps the historical, test-pinned
        # normalisation of the discovered candidate strings.
        bindir = Path(os.path.realpath(vacask_bin)).parent
        prefix = bindir.parent                      # <prefix>/bin/vacask → <prefix>
        cands += [
            str(bindir / "ng2vc.py"),
            str(bindir / "ng2vc"),
            # Observed VACASK / IIC-OSIC-TOOLS layout:
            #   <prefix>/vacask/lib/vacask/python/ng2vc.py
            str(prefix / "vacask" / "lib" / "vacask" / "python" / "ng2vc.py"),
            str(prefix / "lib" / "vacask" / "python" / "ng2vc.py"),
        ]
    return cands


def _resolve_ng2vc(cfg: dict) -> "str | None":
    """Locate the ng2vc converter. The explicit ``ng2vc_binary`` setting wins;
    otherwise fall back to PATH / vacask-relative discovery (`_ng2vc_search_paths`).
    Returns the path (which the caller verifies exists) or None."""
    explicit = (cfg.get("ng2vc_binary") or "").strip()
    if explicit:
        return explicit
    return next((p for p in _ng2vc_search_paths(cfg) if Path(p).exists()), None)


def _ng2vc_argv0(ng2vc_path: str) -> list[str]:
    """Launch prefix for ng2vc: Python scripts run under our interpreter (so the
    sibling ``ng2vclib`` package resolves via the script dir on sys.path); a
    native binary is executed directly."""
    return [sys.executable, ng2vc_path] if ng2vc_path.endswith(".py") else [ng2vc_path]


def _run_ng2vc(spice_file: str | os.PathLike[str],
               sim_file: str | os.PathLike[str]) -> None:
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
    spice_file = Path(spice_file)
    sim_file = Path(sim_file)

    # 1. PyOPUS in-process converter — only when the API is actually present.
    try:
        from pyopus.simulator import ng2vc as _m  # type: ignore[import]
    except Exception:
        _m = None
    if _m is not None and hasattr(_m, "convert"):
        try:
            _m.convert(str(spice_file), str(sim_file))
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
    if not Path(ng2vc_path).exists():
        raise RuntimeError(f"Configured ng2vc_binary does not exist: {ng2vc_path!r}")

    argv0 = _ng2vc_argv0(ng2vc_path)

    def _attempt(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(argv0 + args, capture_output=True, text=True, timeout=120)

    # Form A: ng2vc <in> <out>  (writes the .sim itself).
    res_a = _attempt([str(spice_file), str(sim_file)])
    if res_a.returncode == 0 and sim_file.is_file() and sim_file.stat().st_size > 0:
        log.info("ng2vc conversion via script OK: %s → %s", ng2vc_path, sim_file)
        return

    # Form B: ng2vc <in>  (writes the netlist to stdout).
    res_b = _attempt([str(spice_file)])
    if res_b.returncode == 0 and res_b.stdout.strip():
        sim_file.write_text(res_b.stdout, encoding="utf-8")
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


# ── Result extraction from .raw ───────────────────────────────────────────────

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

    *buckets* is the per-kind dict returned by ``read_raw_file``.
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


def _vacask_extract_results(raw_file: str | os.PathLike[str], test,
                            analysis_tab_paths: dict):
    """Read VACASK .raw output, extract scalars, return (MY_DATA line, error).

    Scalar extraction order (first match wins for each value):
    1. Named signal in the transient bucket matching the value name exactly —
       covers testbenches that use VACASK ``meas`` statements.
    2. Explicit ``measure:`` expression in datasheet.yaml — for computed metrics.
    3. Neither → nan with a warning.
    """
    import numpy as np

    if not raw_file or not Path(raw_file).exists():
        return None, "NO_RAW_FILE"

    buckets = _read_raw_file(str(raw_file))
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
    netlist_ext = ".sim"

    def __init__(self) -> None:
        self._last_log_tail = ""

    def stage_extra_files(self) -> None:
        """Mirror the PDK's *.osdi compact-model objects into FAST_TMP.

        VACASK netlists generated by xschem reference OSDI files with relative
        paths, e.g. ``load "resistor.osdi"``. Since the simulator runs with
        cwd=FAST_TMP, the OSDI files must be present there. Symlink when
        possible, fall back to copy.
        """
        cfg = app_config.load_config()
        pdk_dir = cfg.get("vacask_pdk_dir") or "/foss/pdks/ihp-sg13g2/libs.tech/vacask"
        osdi_dir = Path(pdk_dir) / "osdi"
        if not osdi_dir.is_dir():
            log.warning(
                "vacask osdi dir not found: %s — netlist 'load \"*.osdi\"' "
                "directives will fail. Set 'vacask_pdk_dir' in settings.",
                osdi_dir,
            )
            return

        fast_tmp = Path(settings.FAST_TMP)
        staged = 0
        for src in osdi_dir.iterdir():
            if src.suffix != ".osdi":
                continue
            dest = fast_tmp / src.name
            if dest.is_symlink() or dest.exists():
                # A symlink always tracks its source; a real copy (symlink
                # fallback) can go stale when the PDK is updated — refresh it.
                if dest.is_symlink() or not staged_copy_is_stale(src, dest):
                    continue
                try:
                    dest.unlink()
                except OSError as exc:
                    log.warning("Could not refresh stale osdi %s: %s", src.name, exc)
                    continue
            try:
                os.symlink(src, dest)
            except OSError:
                try:
                    shutil.copy2(src, dest)
                except Exception as exc:
                    log.warning("Could not stage osdi %s: %s", src.name, exc)
                    continue
            staged += 1
        log.info("Staged %d vacask .osdi files from %s into %s",
                 staged, osdi_dir, fast_tmp)

    def generate_test_template(self, test) -> str:
        cfg = app_config.load_config()
        source = cfg.get("vacask_netlist_source", "xschem")
        tb_path = safe_tb_path(test.tb_path)
        # run_xschem names its output after the schematic's basename (nested
        # tb_path like "sub/tb_x" yields FAST_TMP/tb_x.<ext>).
        fast_tmp = Path(settings.FAST_TMP)
        stem = tb_path.stem
        sim_file = fast_tmp / (stem + ".sim")

        if source == "ng2vc":
            # Generate ngspice netlist via Xschem, then convert to VACASK syntax
            run_xschem(tb_path)
            spice_file = fast_tmp / (stem + ".spice")
            _run_ng2vc(spice_file, sim_file)
        else:
            # User picked xschem: produce the Spectre netlist directly via xschem.
            # No silent fallback — switch the setting to "ng2vc" to opt into that path.
            run_xschem(tb_path, netlist_mode="spectre")

        return sim_file.read_text(encoding="utf-8")

    def run(self, netlist: str, timeout_sec: float = 10,
            test=None, analysis_tab_paths: dict | None = None) -> tuple:
        cfg = app_config.load_config()
        analysis_tab_paths = analysis_tab_paths or {}
        vacask_binary = cfg.get("vacask_binary") or "vacask"
        custom_env = os.environ.copy()
        custom_env["OMP_NUM_THREADS"] = "1"

        pid = os.getpid()
        fast_tmp = Path(settings.FAST_TMP)
        # VACASK names its .raw output after the analysis (e.g. `analysis nmos
        # op` → nmos.raw), so concurrent workers running in the same dir would
        # clobber each other. Each invocation gets its own subdir, with the
        # parent FAST_TMP contents symlinked in so OSDI / model loads still
        # resolve relative to cwd.
        workdir = Path(tempfile.mkdtemp(prefix=f"vc_{pid}_", dir=str(fast_tmp)))
        temp_sim_file = workdir / "sim.sim"
        temp_log_file = workdir / "sim.log"
        temp_raw_file: Path | None = None  # resolved post-run by scanning workdir

        # Make staged files (osdi, libs, models) visible inside the workdir.
        for src in fast_tmp.iterdir():
            if src.name == workdir.name:
                continue
            if not (src.is_file() or src.is_symlink()):
                continue
            dest = workdir / src.name
            try:
                os.symlink(src, dest)
            except OSError:
                try:
                    shutil.copy2(src, dest)
                except OSError:
                    pass

        temp_sim_file.write_text(netlist, encoding="utf-8")

        process = None
        try:
            with open(temp_log_file, "w") as log_fh:
                process = subprocess.Popen(
                    [vacask_binary, str(temp_sim_file)],
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=workdir,
                    env=custom_env,
                )

                start_time = time.monotonic()
                while process.poll() is None:
                    if is_aborted():
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
                p for p in workdir.iterdir() if p.suffix == ".raw"
            )
            if raw_candidates:
                temp_raw_file = raw_candidates[0]
                if len(raw_candidates) > 1:
                    log.warning("Multiple .raw files from vacask: %s — picked %s",
                                [p.name for p in raw_candidates], temp_raw_file.name)
            else:
                # No .raw produced even though vacask exited 0 — preserve the
                # log so the user can see what vacask actually did.
                self._preserve_vacask_log(temp_log_file, reason="no_raw")

            # ── Primary path: scan log for MY_DATA: (same as NgspiceSimulator) ──
            # Testbenches can emit MY_DATA: via VACASK's printf command:
            #   printf "MY_DATA: %g %g\n" gain bw
            # This makes the testbench+YAML format identical to the ngspice path.
            my_data_line = ""
            if temp_log_file.exists():
                with open(temp_log_file, "r") as lf:
                    for line in lf:
                        if line.startswith("MY_DATA:"):
                            my_data_line = line.strip()
                            break

            # When a MY_DATA: line is present we still need to write the per-
            # analysis tab files so the GUI sees the waveforms. Without it we
            # also need to extract scalars from the .raw — done in one call.
            if my_data_line:
                if analysis_tab_paths and temp_raw_file is not None and temp_raw_file.exists():
                    buckets = _read_raw_file(str(temp_raw_file))
                    _vacask_write_analysis_tabs(buckets or {}, test,
                                                analysis_tab_paths)
                return my_data_line, None

            # ── Fallback: extract scalars from .raw file ──────────────────────
            # Used when the testbench saves named meas results or the YAML
            # defines explicit measure: expressions.
            return _vacask_extract_results(temp_raw_file or "", test, analysis_tab_paths)

        except subprocess.CalledProcessError:
            err_msg = "CRASH"
            saved_log = ""
            if temp_log_file.exists():
                with open(temp_log_file, "r") as lf:
                    err_msg = "".join(lf.readlines()[-5:]).strip()
                try:
                    out_dir = Path(settings.OUT_DIR)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    saved_log = str(out_dir / (
                        f"vacask_crash_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        f"_{os.getpid()}.log"
                    ))
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
            # Keep the log tail on the instance for post-run diagnostics
            # (run_log_tail) — the workdir is deleted right below.
            try:
                with open(temp_log_file, "r", encoding="utf-8",
                          errors="replace") as fh:
                    self._last_log_tail = "".join(fh.readlines()[-50:]).strip()
            except OSError:
                pass
            try:
                shutil.rmtree(workdir, ignore_errors=True)
            except Exception:
                pass

    def run_log_tail(self, n_lines: int = 25) -> str:
        """Tail of the most recent run's vacask log (stashed before the
        worker-private workdir is deleted)."""
        lines = self._last_log_tail.splitlines()
        return "\n".join(lines[-n_lines:]).strip()

    @staticmethod
    def _preserve_vacask_log(temp_log_file: str | os.PathLike[str], reason: str) -> str:
        """Copy a vacask log into OUT_DIR so it survives workdir cleanup."""
        temp_log_file = Path(temp_log_file)
        if not temp_log_file.exists():
            return ""
        try:
            out_dir = Path(settings.OUT_DIR)
            out_dir.mkdir(parents=True, exist_ok=True)
            dest = out_dir / (
                f"vacask_{reason}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                f"_{os.getpid()}.log"
            )
            shutil.copy2(temp_log_file, dest)
            log.warning("vacask produced no .raw — saved log: %s", dest)
            return str(dest)
        except Exception as exc:
            log.warning("Could not preserve vacask log: %s", exc)
            return ""
