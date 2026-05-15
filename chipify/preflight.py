"""
preflight.py – Structured environment probe for the chipify-cli host.

Used in two ways:

1. ``chipify-cli --preflight`` (invoked over SSH by RemoteDispatcher) prints
   one JSON line to stdout describing the remote's Python, EDA tooling, PDK
   and disk situation. The GUI displays this as a rich "Test Connection"
   result.

2. Locally on the client, only as a helper to render the JSON returned by
   the remote into a human-readable summary string.

No EDA tools are required for this to run – every check is wrapped so a
missing binary becomes a warning, not a crash. Output is intentionally
stable JSON so old GUI versions can keep parsing newer servers.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from typing import Any

PREFLIGHT_PROTOCOL_VERSION = 1


def _probe_version(
    cmd: list[str], pattern: str | None = None, timeout: float = 4.0
) -> str:
    """Return a short version string for *cmd*, or '' on any failure.

    *pattern* is an optional regex applied to combined stdout+stderr;
    if it matches, group(1) is returned. Otherwise the first non-empty
    output line is returned.
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""
    blob = (proc.stdout or "") + (proc.stderr or "")
    blob = blob.strip()
    if not blob:
        return ""
    if pattern:
        m = re.search(pattern, blob)
        if m:
            return m.group(1).strip()
    for line in blob.splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return ""


def _chipify_version() -> str:
    try:
        from importlib.metadata import version as _v
        return _v("chipify")
    except Exception:
        pass
    # Fall back to setup.py-style version probing without importing the GUI.
    try:
        from chipify import __version__  # type: ignore[attr-defined]
        return str(__version__)
    except Exception:
        return ""


def _ram_gb() -> float | None:
    """Total physical RAM in GB (Linux /proc/meminfo only — good enough)."""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024 * 1024), 1)
    except OSError:
        pass
    return None


def _disk_free_gb(path: str) -> float | None:
    try:
        st = shutil.disk_usage(path)
        return round(st.free / 1e9, 1)
    except OSError:
        return None


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        return os.access(path, os.W_OK)
    except OSError:
        return False


def _list_pdks(pdk_root: str) -> list[str]:
    if not pdk_root or not os.path.isdir(pdk_root):
        return []
    try:
        return sorted(
            d for d in os.listdir(pdk_root)
            if os.path.isdir(os.path.join(pdk_root, d))
            and not d.startswith(".")
        )
    except OSError:
        return []


def collect(work_dir: str | None = None) -> dict[str, Any]:
    """Return a JSON-serialisable preflight report.

    Parameters
    ----------
    work_dir:
        Path to the directory chipify will write its work tree into on this
        host. Defaults to ``chipify.settings.WORK_DIR`` if available, else
        ``/tmp``.
    """
    if work_dir is None:
        try:
            from chipify import settings as _s
            work_dir = _s.WORK_DIR
        except Exception:
            work_dir = "/tmp"

    pdk_root = os.environ.get("PDK_ROOT", "")
    active_pdk = os.environ.get("PDK", "")

    info: dict[str, Any] = {
        "protocol": PREFLIGHT_PROTOCOL_VERSION,
        "chipify_version": _chipify_version(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "hostname": platform.node(),
        "cores": os.cpu_count() or 1,
        "ram_gb": _ram_gb(),
        "ngspice": _probe_version(
            ["ngspice", "--version"], pattern=r"ngspice-(\S+)"
        ),
        "xschem": _probe_version(
            ["xschem", "--version"], pattern=r"(\d+\.\d+\.\d+)"
        ),
        "vacask": _probe_version(["vacask", "--version"]),
        "pdk_root": pdk_root,
        "active_pdk": active_pdk,
        "available_pdks": _list_pdks(pdk_root),
        "work_dir": work_dir,
        "work_dir_free_gb": _disk_free_gb(work_dir),
        "work_dir_writable": _writable(work_dir),
        "iic_osic_tools": os.path.exists("/foss/tools")
                          and os.path.exists("/foss/pdks"),
    }

    try:
        info["paramiko"] = _probe_version(
            ["python3", "-c",
             "import paramiko, sys; sys.stdout.write(paramiko.__version__)"]
        )
    except Exception:
        info["paramiko"] = ""

    warnings: list[str] = []
    errors: list[str] = []

    if not info["chipify_version"]:
        errors.append("chipify not importable (check `pip install chipify`).")
    if not info["ngspice"]:
        errors.append("ngspice not found on PATH.")
    if not info["xschem"]:
        warnings.append(
            "xschem not found on PATH (only required if you generate "
            "templates on the remote — usually they are uploaded)."
        )
    if not pdk_root:
        warnings.append("PDK_ROOT not set; the wrapper defaults to /foss/pdks.")
    elif not os.path.isdir(pdk_root):
        errors.append(f"PDK_ROOT={pdk_root!r} does not exist.")
    if not active_pdk:
        warnings.append("PDK env var not set; pick one in ~/.chipify-remote.env.")
    if info["work_dir_free_gb"] is not None and info["work_dir_free_gb"] < 1.0:
        warnings.append(
            f"Only {info['work_dir_free_gb']} GB free on {work_dir}."
        )
    if not info["work_dir_writable"]:
        errors.append(f"work_dir {work_dir!r} is not writable.")
    if info["ram_gb"] is not None and info["ram_gb"] < 2:
        warnings.append(f"Only {info['ram_gb']} GB RAM detected.")

    info["warnings"] = warnings
    info["errors"] = errors
    info["ok"] = not errors
    return info


def format_summary(info: dict[str, Any]) -> str:
    """Render a multi-line human-friendly summary for the GUI."""
    def _row(label: str, value: Any) -> str:
        return f"  {label:<18} {value}"

    cores = info.get("cores")
    ram = info.get("ram_gb")
    ram_s = f"{ram} GB" if ram is not None else "?"
    free = info.get("work_dir_free_gb")
    free_s = f"{free} GB free" if free is not None else "?"

    lines = []
    lines.append(_row("Host:", info.get("hostname") or "?"))
    lines.append(_row("OS:", info.get("platform") or "?"))
    lines.append(
        _row("Chipify:", info.get("chipify_version") or "(missing)")
    )
    lines.append(_row("Python:", info.get("python") or "?"))
    lines.append(_row("ngspice:", info.get("ngspice") or "(missing)"))
    lines.append(_row("xschem:", info.get("xschem") or "(not on PATH)"))
    if info.get("vacask"):
        lines.append(_row("vacask:", info["vacask"]))
    lines.append(_row("PDK_ROOT:", info.get("pdk_root") or "(unset)"))
    lines.append(_row("Active PDK:", info.get("active_pdk") or "(unset)"))
    avail = info.get("available_pdks") or []
    if avail:
        lines.append(_row("Available PDKs:", ", ".join(avail)))
    lines.append(_row("Cores:", cores))
    lines.append(_row("RAM:", ram_s))
    lines.append(
        _row("Work dir:", f"{info.get('work_dir', '?')} ({free_s})")
    )
    if info.get("iic_osic_tools"):
        lines.append(_row("Container:", "iic-osic-tools detected"))

    for w in info.get("warnings") or []:
        lines.append(f"  ⚠  {w}")
    for e in info.get("errors") or []:
        lines.append(f"  ✗  {e}")
    if info.get("ok") and not info.get("warnings"):
        lines.append("  ✓  All checks passed.")
    return "\n".join(lines)


def emit_json() -> int:
    """Entry point for ``chipify-cli --preflight``.

    Always prints the JSON; returns 0 if ``ok`` else 3.
    """
    info = collect()
    print(json.dumps(info, ensure_ascii=False), flush=True)
    return 0 if info.get("ok") else 3
