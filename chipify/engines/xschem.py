# Copyright (c) 2026 Santiago Hofwimmer
"""
xschem.py – Schematic → netlist generation via Xschem in batch mode.

Shared by every engine whose netlists come from xschem schematics
(:class:`~chipify.engines.ngspice.NgspiceSimulator` uses ``spice`` mode,
:class:`~chipify.engines.vacask.VacaskSimulator` uses ``spectre`` mode or the
ng2vc conversion path). A new engine whose simulator reads one of these two
syntaxes can call :func:`run_xschem` directly from its
``generate_test_template``.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from chipify import settings
from chipify.engines.abort import is_aborted

log = logging.getLogger("chipify.engines.xschem")

XSCHEM_DEFAULT_TIMEOUT_SEC = 60

_XSCHEM_NETLIST_EXTS = (".spice", ".sim", ".spectre", ".scs", ".spc", ".sp", ".cdl", ".cir")


def safe_tb_path(tb_name: str) -> Path:
    """Return the absolute testbench .sch path, raising ValueError on traversal attempts."""
    # os.path.normpath collapses '..' lexically without touching the filesystem;
    # pathlib has no equivalent, so the historical containment check is kept as-is.
    base = os.path.normpath(settings.TB_DIR)
    full = os.path.normpath(os.path.join(settings.TB_DIR, tb_name + ".sch"))
    if not full.startswith(base + os.sep) and full != base:
        raise ValueError(
            f"Testbench path {tb_name!r} escapes TB_DIR ({settings.TB_DIR!r})."
        )
    return Path(full)


def safe_tb_file(name: str) -> Path:
    """Resolve an imported-netlist path (under TB_DIR) to an existing file.

    Like :func:`safe_tb_path` but uses *name* verbatim (no forced ``.sch``), so a
    testbench's ``netlist:`` key can point at e.g. ``amp.spice``/``amp.sim``.
    Guards against path traversal out of TB_DIR and raises FileNotFoundError if
    the file is missing.
    """
    base = os.path.normpath(settings.TB_DIR)
    full = os.path.normpath(os.path.join(settings.TB_DIR, name))
    if not full.startswith(base + os.sep) and full != base:
        raise ValueError(
            f"Netlist path {name!r} escapes TB_DIR ({settings.TB_DIR!r})."
        )
    path = Path(full)
    if not path.is_file():
        raise FileNotFoundError(
            f"Imported netlist {name!r} not found at {full} "
            f"(expected under TB_DIR {settings.TB_DIR!r})."
        )
    return path


def _read_log_tail(log_path: Path, n_lines: int = 60) -> str:
    try:
        with open(log_path, "r") as lf:
            return "".join(lf.readlines()[-n_lines:]).strip()
    except OSError:
        return "<log unavailable>"


def _snapshot_dir(path: Path) -> set:
    try:
        return {p.name for p in Path(path).iterdir()}
    except OSError:
        return set()


def _safe_rel(path: Path) -> str:
    """``os.path.relpath`` that never raises.

    On Windows, relpath raises ValueError when *path* and the cwd are on
    different drives (e.g. temp on C:, project on D:); fall back to the
    absolute path rather than turning a log statement into a failure.
    """
    try:
        return os.path.relpath(path)
    except ValueError:
        return str(path)


def run_xschem(
    xschem_file: str | os.PathLike[str],
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
    xschem_file = Path(xschem_file)
    fast_tmp = Path(settings.FAST_TMP)
    project_root = Path(settings.PROJECT_ROOT)

    mode = (netlist_mode or "spice").strip().lower()
    if mode not in ("spice", "spectre"):
        raise ValueError(f"Unknown netlist_mode: {netlist_mode!r}")
    log.info("run_xschem: %s (mode=%s)", xschem_file, mode)

    stem = xschem_file.stem
    expected_ext = ".sim" if mode == "spectre" else ".spice"
    out_file = fast_tmp / (stem + expected_ext)
    log_path = fast_tmp / (stem + ".xschem.log")

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
    # never returns. -x suppresses the X server attach. Path args are
    # stringified so the cmd list stays ``' '.join``-able for logging.
    cmd += ['-q', '-x', '-o', str(fast_tmp), str(xschem_file)]

    start_ts = time.time()

    process = None
    log.info("Xschem env: HOME=%s XSCHEM_SHAREDIR=%s PATH=%s cwd=%s",
             os.environ.get("HOME"), os.environ.get("XSCHEM_SHAREDIR"),
             os.environ.get("PATH", "")[:200], project_root)
    try:
        with open(log_path, "w") as log_fh:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=project_root,
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
                if is_aborted():
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
        def _modified_since(path: Path, since: float) -> list[Path]:
            out: list[Path] = []
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
                            out.append(Path(e.path))
                    except OSError:
                        continue
            return out

        # Scan both FAST_TMP (where -o points) and PROJECT_ROOT (cwd) just in
        # case xschem wrote relative to cwd despite the -o flag.
        scan_dirs = [fast_tmp, project_root]
        recent_files: list[Path] = []
        for d in scan_dirs:
            recent_files += _modified_since(d, start_ts)

        netlist_files = [p for p in recent_files
                         if p.suffix.lower() in _XSCHEM_NETLIST_EXTS]
        # Only accept a netlist whose stem matches this schematic. The mtime
        # scan's 1s slack can include the *previous* testbench's netlist when
        # testbenches are generated back-to-back; adopting it here (when
        # xschem exits 0 without writing anything) would silently simulate
        # the wrong circuit. Non-matching files are only logged for diagnosis.
        preferred = [p for p in netlist_files if p.stem == stem]
        chosen_path: Path | None = preferred[0] if preferred else None

        log.info("xschem post-run scan: recent_files=%s netlist_files=%s chosen=%s",
                 [_safe_rel(p) for p in recent_files],
                 [_safe_rel(p) for p in netlist_files],
                 _safe_rel(chosen_path) if chosen_path else "<none>")

        if not chosen_path:
            tail = _read_log_tail(log_path)
            after = _snapshot_dir(fast_tmp)
            raise RuntimeError(
                f"Xschem ran (rc={process.returncode}) but wrote no netlist "
                f"named {stem!r}. "
                f"recent_files={[str(p) for p in recent_files]}. "
                f"FAST_TMP contents: {sorted(after)}. "
                f"See {log_path}. log_tail={tail}"
            )

        produced = chosen_path
        # Normalize whatever xschem wrote to the caller's expected filename.
        if produced != out_file:
            shutil.move(str(produced), str(out_file))
            log.info("Moved xschem output %s -> %s",
                     _safe_rel(produced), out_file)

        if process.returncode != 0:
            log.warning(
                "Xschem returned rc=%d but produced %s. Continuing.",
                process.returncode, out_file,
            )
        log.info("Xschem netlist generated OK (%s).", mode)
        try:
            log_path.unlink(missing_ok=True)
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
