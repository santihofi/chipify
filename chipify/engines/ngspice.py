# Copyright (c) 2026 Santiago Hofwimmer
"""
ngspice.py – Ngspice simulator engine.

Netlists come from xschem (``spice`` mode); scalar results ride a single
``MY_DATA:`` echo line injected into the ``.control`` block; waveform capture
is injected as ``setplot``/``wrdata`` lines whose output paths are Jinja2
placeholders filled per worker run (see analyses.Analysis.ngspice_inject).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path

from chipify import settings
from chipify.engines.abort import is_aborted
from chipify.engines.base import BaseSimulator
from chipify.engines.xschem import run_xschem, safe_tb_file, safe_tb_path

log = logging.getLogger("chipify.engines.ngspice")


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
    netlist_ext = ".spice"

    def generate_test_template(self, test) -> str:
        # Source the raw netlist: source="netlist" loads an existing deck at
        # tb/<tb_path>.spice directly; otherwise netlist the .sch via xschem.
        if getattr(test, "netlist_source", "xschem") == "netlist":
            netlist = safe_tb_file(
                test.tb_path + self.netlist_ext
            ).read_text(encoding="utf-8")
        else:
            tb_path = safe_tb_path(test.tb_path)
            run_xschem(tb_path)
            # run_xschem names its output after the schematic's basename, so a
            # nested tb_path like "sub/tb_x" still yields FAST_TMP/tb_x.spice.
            spice_file = Path(settings.FAST_TMP) / (tb_path.stem + ".spice")
            netlist = spice_file.read_text()

        return self._finalize_netlist(netlist, test)

    def _finalize_netlist(self, netlist: str, test) -> str:
        """Splice Chipify's managed capture into a raw ngspice netlist.

        Applied identically whether *netlist* came from xschem or was imported
        directly, so an imported plain deck reuses the datasheet's measurement
        contract. The testbench supplies the let/meas vectors named after the
        datasheet measurements; chipify owns the ``set num_threads``, the
        ``MY_DATA:`` echo, and the per-analysis wrdata/setplot lines.
        """
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

    def run(self, netlist: str, timeout_sec: float = 10, test=None,
            analysis_tab_paths: dict | None = None):
        custom_env = os.environ.copy()
        custom_env["OMP_NUM_THREADS"] = "1"

        pid = os.getpid()
        fast_tmp = Path(settings.FAST_TMP)
        temp_spice_file = fast_tmp / f"sim_{pid}.spice"
        temp_log_file = fast_tmp / f"sim_{pid}.log"

        with open(temp_spice_file, "w") as f:
            f.write(netlist)

        process = None
        try:
            with open(temp_log_file, "w") as log_file:
                process = subprocess.Popen(
                    ["ngspice", "-b", "-r", os.devnull, str(temp_spice_file)],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=fast_tmp,
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

            output_line = ""
            with open(temp_log_file, "r") as lf:
                for line in lf:
                    if line.startswith("MY_DATA:"):
                        output_line = line.strip()
                        break

            return output_line, None

        except subprocess.CalledProcessError:
            err_msg = "CRASH"
            if temp_log_file.exists():
                with open(temp_log_file, "r") as f:
                    err_msg = "".join(f.readlines()[-5:]).strip()
            return None, f"CRASH: {err_msg}"
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                # Reap the (possibly just-killed) child — without wait() it
                # lingers as a zombie until the worker process exits.
                try:
                    process.wait(timeout=5)
                except Exception:
                    pass

    def run_log_tail(self, n_lines: int = 25) -> str:
        """Tail of this worker's ngspice run log (best-effort, '' on failure).

        ``run`` writes the simulator's stdout/stderr to ``FAST_TMP/sim_<pid>.log``
        for the current worker pid; right after ``run`` returns it still holds
        that run's output. Used to explain why a declared analysis produced no
        output tab.
        """
        log_path = Path(settings.FAST_TMP) / f"sim_{os.getpid()}.log"
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            return ""
        return "".join(lines[-n_lines:]).strip()
