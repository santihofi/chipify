"""
app_config.py – Persistent user preferences + application-wide logging setup.

Config file : settings.json  in PROJECT_ROOT
Log file    : out/chipify.log (rotating, max 2 MB × 3 files)
"""

import os
import json
import logging
import logging.handlers
from typing import Any

from chipify import settings

CONFIG_PATH = os.path.join(settings.PROJECT_ROOT, "settings.json")
LOG_PATH    = os.path.join(settings.OUT_DIR, "chipify.log")

DEFAULT_REMOTE_PROFILE: dict[str, Any] = {
    "name": "default",
    "base_url": "",                  # e.g. https://host:8443
    "token": "",                     # bearer token literal
    "token_file": "",                # optional path read at run time; wins over `token`
    "work_dir": "/tmp/chipify_remote",
    "verify_tls": True,              # False = skip TLS fingerprint pin (dev only)
    "cert_fingerprint_sha256": "",   # populated by the GUI TOFU dialog
    "keep_on_failure": False,        # leave remote run dir intact on rc!=0
}

DEFAULTS: dict[str, Any] = {
    "num_cores": None,                # None → auto-detect via util.get_num_cores()
    "simulator_engine": "ngspice",    # ngspice|vacask
    "vacask_binary": "vacask",        # path or PATH-resolvable name
    "vacask_netlist_source": "xschem",# xschem|ng2vc
    "vacask_pdk_dir": "/foss/pdks/ihp-sg13g2/libs.tech/vacask",  # contains osdi/ and models/
    "process_start_method": "auto",   # auto|forkserver|spawn
    "chunk_size": "auto",             # auto|1|2|4|8|16|32|64|128|256
    "live_plotting_enabled": False,   # off by default — avoids Tk/worker coupling cost
    "live_plot_throttle_ms": 1500,    # min ms between plot redraws (500–5000)
    "live_plot_emit_stride": 1,       # emit GUI chunks every N pool batches (1 = every batch)
    "custom_equations": [],           # [{"name": "eff", "expr": "p_out / p_in * 100"}, ...]
    "transient_equations": [],        # [{"name": "vdiff", "expr": "v(outp) - v(outn)"}, ...]
    "multiplot_config": [],           # persisted PlotCell configs for Multi-Plot Dashboard
    "theme": "night",                 # appearance theme: night|dark|light
    # ── Remote compute dispatcher ──
    "compute_target": "local",        # local|remote
    # Named HTTPS server profiles + which one is active.
    "remote_profiles": [],            # list of dicts shaped like DEFAULT_REMOTE_PROFILE
    "active_remote_profile": "default",
}

_logging_ready = False
_config_cache: dict[str, Any] | None = None
_config_mtime: float | None = None


def setup_logging(level: int = logging.DEBUG) -> None:
    """
    Initialise the root 'chipify' logger once.
    Safe to call multiple times – subsequent calls are no-ops.
    """
    global _logging_ready
    if _logging_ready:
        return

    os.makedirs(settings.OUT_DIR, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler – 2 MB per file, keep 3 backups
    fh = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Console handler – INFO and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    root = logging.getLogger("chipify")
    root.setLevel(level)
    root.addHandler(fh)
    root.addHandler(ch)
    root.propagate = False

    root.info("=" * 60)
    root.info("Chipify logging initialised  →  %s", LOG_PATH)
    root.info("=" * 60)

    _logging_ready = True


# ── Config persistence ────────────────────────────────────────────────────────

def load_config() -> dict[str, Any]:
    """
    Return the merged config (cached; invalidated when settings.json mtime changes).

    Priority (highest wins): settings.json  >  project.yaml defaults  >  DEFAULTS.
    """
    global _config_cache, _config_mtime

    current_mtime: float | None = None
    if os.path.exists(CONFIG_PATH):
        try:
            current_mtime = os.path.getmtime(CONFIG_PATH)
        except OSError:
            pass

    if _config_cache is not None and current_mtime == _config_mtime:
        return _config_cache.copy()

    merged = DEFAULTS.copy()

    try:
        from chipify import project_config
        proj = project_config.load()
        _key_map = {
            "default_num_cores":      "num_cores",
            "default_report_profile": "pdf_profile",
        }
        for proj_key, cfg_key in _key_map.items():
            if proj_key in proj and merged.get(cfg_key) is None:
                merged[cfg_key] = proj[proj_key]
    except Exception:
        pass

    if current_mtime is not None:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged.update(data)
        except Exception as exc:
            logging.getLogger("chipify.config").warning(
                "Could not read %s: %s – using defaults.", CONFIG_PATH, exc
            )

    _config_cache = merged
    _config_mtime = current_mtime
    return merged.copy()


def save_config(config: dict[str, Any]) -> None:
    """Persist *config* to settings.json, overwriting any previous file."""
    global _config_cache, _config_mtime
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        _config_cache = None
        _config_mtime = None
    except Exception as exc:
        logging.getLogger("chipify.config").error(
            "Could not write %s: %s", CONFIG_PATH, exc
        )


def save_config_key(key: str, value: Any) -> None:
    """Update a single config key and persist."""
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)


def is_live_plotting_enabled() -> bool:
    """Return whether live plotting is enabled in the current config."""
    cfg = load_config()
    return bool(cfg.get("live_plotting_enabled", False))


def get_live_throttle_ms() -> int:
    """Return the live-plot throttle interval in milliseconds."""
    cfg = load_config()
    raw = cfg.get("live_plot_throttle_ms", 1500)
    try:
        return max(500, min(5000, int(raw)))
    except (TypeError, ValueError):
        return 1500


def get_live_plot_emit_stride() -> int:
    """Emit live-plot chunks once every N completed pool batches (minimum 1)."""
    cfg = load_config()
    raw = cfg.get("live_plot_emit_stride", 1)
    try:
        return max(1, min(64, int(raw)))
    except (TypeError, ValueError):
        return 1


# ── Remote profile helpers ────────────────────────────────────────────────────

def _legacy_remote_to_profile(cfg: dict[str, Any]) -> dict[str, Any]:
    """Stub kept for callers that still reach for it.

    The previous SSH-shaped fields (remote_host / remote_user / remote_key_path
    / remote_port / remote_chipify_cmd) have no HTTPS analogue, so we return
    a fresh default profile and let the user fill in base_url + token via
    the Settings dialog.
    """
    return DEFAULT_REMOTE_PROFILE.copy()


def get_remote_profiles(cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return the list of saved remote profiles (auto-migrate legacy fields).

    Always returns at least one profile; the GUI uses
    ``active_remote_profile`` to choose which one is current.
    """
    if cfg is None:
        cfg = load_config()
    raw = cfg.get("remote_profiles") or []
    profiles: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        merged = DEFAULT_REMOTE_PROFILE.copy()
        for k, v in entry.items():
            if k in merged:
                merged[k] = v
        if not merged.get("name"):
            merged["name"] = f"profile_{len(profiles) + 1}"
        profiles.append(merged)

    if not profiles:
        profiles.append(DEFAULT_REMOTE_PROFILE.copy())

    return profiles


def get_active_profile(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the currently active remote profile dict."""
    if cfg is None:
        cfg = load_config()
    profiles = get_remote_profiles(cfg)
    target = (cfg.get("active_remote_profile") or "").strip()
    for p in profiles:
        if p.get("name") == target:
            return p
    return profiles[0]


def save_remote_profiles(
    profiles: list[dict[str, Any]],
    active_name: str | None = None,
) -> None:
    """Persist *profiles* and (optionally) update the active profile name."""
    cfg = load_config()
    clean: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for p in profiles:
        merged = DEFAULT_REMOTE_PROFILE.copy()
        for k, v in (p or {}).items():
            if k in merged:
                merged[k] = v
        name = (merged.get("name") or "").strip() or "profile"
        base = name
        i = 2
        while name in seen_names:
            name = f"{base}_{i}"
            i += 1
        merged["name"] = name
        seen_names.add(name)
        clean.append(merged)

    cfg["remote_profiles"] = clean
    if active_name and any(p["name"] == active_name for p in clean):
        cfg["active_remote_profile"] = active_name
    elif clean and cfg.get("active_remote_profile") not in {p["name"] for p in clean}:
        cfg["active_remote_profile"] = clean[0]["name"]

    # Drop any orphaned legacy SSH keys that might be sitting in
    # settings.json from a previous version. They have no HTTPS analogue.
    for legacy in (
        "remote_host", "remote_user", "remote_key_path",
        "remote_work_dir", "remote_port", "remote_chipify_cmd",
    ):
        cfg.pop(legacy, None)

    save_config(cfg)
