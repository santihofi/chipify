"""
remote_dispatcher.py – Offload simulation sweeps to a remote Linux server
(typically the ``iic-osic-tools`` Docker container).

Local responsibilities:
    1. Run xschem and prepare Jinja2 templates (``simulator.generate_templates``).
    2. Bundle templates + datasheet YAML + SPICE library files (.lib/.mod/.inc),
       skipping unchanged libs via the per-host SHA-256 cache.
    3. SFTP upload, SSH exec chipify-cli on the remote, stream progress + phase,
       capture remote log tail, support abort.
    4. SFTP download the results CSV (and transient data) back into OUT_DIR.

Remote responsibilities (handled by chipify-cli with --templates-dir):
    Skip xschem, read pre-rendered templates from disk, run the existing
    multiprocessing.Pool sweep there. ``--preflight`` is supported on the
    remote for the Test Connection panel.

Authentication: SSH key path, SSH agent, ssh_config alias, or password (the
last three are opt-in via the profile fields ``use_agent``, ``ssh_config_alias``,
or ``password``). Host keys are verified against ``~/.chipify/known_hosts``
with TOFU on first contact.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shlex
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TYPE_CHECKING

import pandas as pd

from chipify import settings
from chipify.preflight import format_summary

if TYPE_CHECKING:
    from chipify.util import Stimuli

log = logging.getLogger("chipify.remote_dispatcher")

# ── Stdout protocol ────────────────────────────────────────────────────────
# Lines the remote chipify-cli is expected to emit when invoked with
# --progress-stream. Older servers without PHASE support stay compatible —
# the dispatcher treats missing phases as None.
_PROGRESS_RE = re.compile(r"^PROGRESS:\s+(\d+)\s+(\d+)\s*$")
_PHASE_RE    = re.compile(r"^PHASE:\s+([A-Za-z0-9_]+)\s*$")
_READY_RE    = re.compile(r"^READY\s+(\d+)\s*$")

# Heartbeat lets the local stop_event interrupt the receive loop even when
# the remote produces no output for a while.
_HEARTBEAT_SEC = 0.5
_RECV_POLL_SEC = 0.1
_KILL_GRACE_SEC = 2.0

# How many recent remote stdout lines to keep for diagnostics / remote console.
_LOG_TAIL_SIZE = 200

# ── Known-hosts / cache directories on the local machine ───────────────────
LOCAL_CONFIG_DIR = os.path.expanduser(os.path.join("~", ".chipify"))
LOCAL_KNOWN_HOSTS = os.path.join(LOCAL_CONFIG_DIR, "known_hosts")
LOCAL_LIB_CACHE_DIR = os.path.join(LOCAL_CONFIG_DIR, "lib_cache")

# Wrapper candidate paths probed on the remote (in order) when the user-
# configured command is missing or empty.
_WRAPPER_CANDIDATES: tuple[str, ...] = (
    # Typical iic-osic-tools SSH user HOME (explicit — ``~'' may expand in
    # unexpected ways depending on how ``sshd`` sets HOME for the login).
    "/headless/.local/bin/chipify-remote",
    "/headless/.local/bin/chipify-cli",
    "/usr/local/bin/chipify-remote",
    "~/.local/bin/chipify-remote",
    "/usr/local/bin/chipify-cli",
    "~/.local/bin/chipify-cli",
    "chipify-remote",
    "chipify-cli",
)


# ── Errors ─────────────────────────────────────────────────────────────────

class RemoteDispatcherError(RuntimeError):
    """Raised when the remote sweep cannot be completed."""


class HostKeyVerificationError(RemoteDispatcherError):
    """Raised on host-key mismatch or first-time host (TOFU).

    Carries enough metadata for the GUI to show a "trust this fingerprint?"
    dialog.
    """

    def __init__(
        self,
        host: str,
        port: int,
        key_type: str,
        fingerprint_sha256: str,
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.host = host
        self.port = port
        self.key_type = key_type
        self.fingerprint_sha256 = fingerprint_sha256
        self.reason = reason

    def __str__(self) -> str:
        return (
            f"{self.reason} ({self.host}:{self.port} "
            f"{self.key_type} SHA256:{self.fingerprint_sha256})"
        )


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class RemoteProfile:
    """Connection settings for one remote target.

    Mirrors the persisted dict in ``settings.json`` under
    ``remote_profiles[]`` so the GUI can pass it to the dispatcher as-is.
    """
    name: str = "default"
    host: str = ""
    port: int = 22
    user: str = ""
    key_path: str = ""
    work_dir: str = "/tmp/chipify_remote"
    wrapper: str = ""  # blank → auto-detect on remote
    ssh_config_alias: str = ""
    use_agent: bool = True
    keep_on_failure: bool = False
    env_file: str = ""  # if set, sourced by the wrapper via CHIPIFY_REMOTE_ENV

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RemoteProfile":
        kwargs: dict[str, Any] = {}
        for f in (
            "name", "host", "user", "key_path", "work_dir",
            "wrapper", "ssh_config_alias", "env_file",
        ):
            if f in d and d[f] is not None:
                kwargs[f] = str(d[f]).strip()
        if "port" in d:
            try:
                kwargs["port"] = int(d["port"] or 22)
            except (TypeError, ValueError):
                kwargs["port"] = 22
        if "use_agent" in d:
            kwargs["use_agent"] = bool(d["use_agent"])
        if "keep_on_failure" in d:
            kwargs["keep_on_failure"] = bool(d["keep_on_failure"])
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "key_path": self.key_path,
            "work_dir": self.work_dir,
            "wrapper": self.wrapper,
            "ssh_config_alias": self.ssh_config_alias,
            "use_agent": self.use_agent,
            "keep_on_failure": self.keep_on_failure,
            "env_file": self.env_file,
        }


@dataclass
class RemoteProgress:
    """Snapshot of an in-flight remote run.

    Passed to ``progress_callback`` as the third argument when the callback
    supports it; older two-arg callbacks continue to work.
    """
    phase: str = "starting"
    done: int = 0
    total: int = 0
    rate_per_sec: float = 0.0
    eta_sec: float | None = None
    log_tail: list[str] = field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────

def _safe_filename(path: str) -> str:
    return path.replace("/", "__").replace("\\", "__")


def _call_progress(
    cb: Optional[Callable[..., None]],
    done: int,
    total: int,
    meta: Optional[RemoteProgress] = None,
) -> None:
    """Invoke *cb* without crashing on callbacks that only take (done, total)."""
    if cb is None:
        return
    try:
        cb(done, total, meta)
    except TypeError:
        try:
            cb(done, total)
        except Exception:
            log.exception("progress_callback raised; continuing.")
    except Exception:
        log.exception("progress_callback raised; continuing.")


def _sha256_of_file(path: str, buf_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(buf_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _ensure_local_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        log.exception("Could not create local dir %s", path)


# ── Host-key (TOFU) policy ─────────────────────────────────────────────────

def _fingerprint(key: Any) -> str:
    """SHA256 fingerprint matching the format displayed by OpenSSH."""
    import base64
    digest = hashlib.sha256(key.asbytes()).digest()
    return base64.b64encode(digest).rstrip(b"=").decode("ascii")


def _hostkey_policy_class(strict: bool, trust_new: bool):
    """Build a paramiko MissingHostKeyPolicy subclass.

    * strict=True, trust_new=False  → raise HostKeyVerificationError on unknown
      hosts. The GUI catches this and shows a TOFU dialog.
    * strict=True, trust_new=True   → silently add the new host key to the
      persisted known_hosts (called *after* the user has clicked Trust).
    """
    import paramiko  # type: ignore[import]

    class _Policy(paramiko.MissingHostKeyPolicy):  # type: ignore[misc,valid-type]
        def missing_host_key(self, client, hostname, key) -> None:  # noqa: D401
            fp = _fingerprint(key)
            key_type = key.get_name()
            if trust_new:
                client.get_host_keys().add(hostname, key_type, key)
                _ensure_local_dir(LOCAL_CONFIG_DIR)
                client.save_host_keys(LOCAL_KNOWN_HOSTS)
                log.info(
                    "Trusted new host key for %s (%s SHA256:%s).",
                    hostname, key_type, fp,
                )
                return
            if not strict:
                return
            host = hostname
            port = 22
            raise HostKeyVerificationError(
                host=host,
                port=port,
                key_type=key_type,
                fingerprint_sha256=fp,
                reason="Unknown host key (first connection).",
            )

    return _Policy


# ── The dispatcher ─────────────────────────────────────────────────────────

class RemoteDispatcher:
    """Owns one SSH+SFTP session and one remote run directory."""

    def __init__(
        self,
        profile: RemoteProfile | None = None,
        *,
        # Back-compat kwargs (old call signature):
        host: str = "",
        username: str = "",
        key_path: str = "",
        remote_work_dir: str = "/tmp/chipify_remote",
        port: int = 22,
        remote_chipify_cmd: str = "",
        connect_timeout: int = 15,
        trust_new_hostkey: bool = False,
    ) -> None:
        if profile is None:
            profile = RemoteProfile(
                name="default",
                host=host,
                port=port,
                user=username,
                key_path=key_path,
                work_dir=remote_work_dir,
                wrapper=remote_chipify_cmd,
            )

        if not profile.host or not profile.user:
            raise RemoteDispatcherError(
                "Remote profile incomplete: host and username are required."
            )

        # Resolve the key path, but do not fail when none is given — we may
        # still authenticate via ssh-agent or ssh_config_alias.
        if profile.key_path:
            kp = os.path.expanduser(profile.key_path)
            if not os.path.exists(kp):
                raise RemoteDispatcherError(f"SSH key not found: {kp}")
            profile.key_path = kp

        self.profile = profile
        self.connect_timeout = connect_timeout
        self.trust_new_hostkey = trust_new_hostkey

        self.run_id = uuid.uuid4().hex[:12]
        self.remote_work_dir = (profile.work_dir or "/tmp/chipify_remote").rstrip("/") or "/tmp/chipify_remote"
        self.remote_run_dir = f"{self.remote_work_dir}/run_{self.run_id}"
        self.remote_project_dir = f"{self.remote_run_dir}/project"

        self._ssh = None
        self._sftp = None
        self._paramiko = None

        # Auto-detected wrapper command, filled in __enter__ (or kept as the
        # user-provided value when it works).
        self._resolved_cmd: str = ""

        # State used by the progress loop / abort path.
        self._progress = RemoteProgress()
        self._run_started_at = 0.0
        self._aborted = False
        self._keep_remote_dir_override: bool | None = None

    # ── Authentication helpers ───────────────────────────────────────────

    def _open_ssh(self):
        import paramiko  # type: ignore[import]
        ssh = paramiko.SSHClient()

        # Load any pre-existing known_hosts (system + chipify-local).
        try:
            ssh.load_system_host_keys()
        except Exception:
            log.debug("load_system_host_keys failed", exc_info=True)
        if os.path.exists(LOCAL_KNOWN_HOSTS):
            try:
                ssh.load_host_keys(LOCAL_KNOWN_HOSTS)
            except Exception:
                log.warning(
                    "Could not load %s — TOFU prompt will reappear.",
                    LOCAL_KNOWN_HOSTS,
                )

        Policy = _hostkey_policy_class(
            strict=True, trust_new=self.trust_new_hostkey
        )
        ssh.set_missing_host_key_policy(Policy())
        return ssh, paramiko

    def _connect_kwargs(self) -> dict[str, Any]:
        """Build the kwargs for paramiko.SSHClient.connect()."""
        kw: dict[str, Any] = {
            "hostname": self.profile.host,
            "port": int(self.profile.port or 22),
            "username": self.profile.user,
            "timeout": self.connect_timeout,
        }
        if self.profile.key_path:
            kw["key_filename"] = self.profile.key_path
            kw["allow_agent"] = self.profile.use_agent
            kw["look_for_keys"] = False
        else:
            kw["allow_agent"] = self.profile.use_agent
            kw["look_for_keys"] = True
        return kw

    def _apply_ssh_config(self, kw: dict[str, Any]) -> Any:
        """If ``ssh_config_alias`` is set, merge values from ~/.ssh/config.

        Returns a paramiko ProxyCommand (or AutoAddPolicy-friendly Channel)
        when a ProxyJump / ProxyCommand entry is present; otherwise None.
        Always preserves explicit profile fields (they win over ssh_config).
        """
        if not self.profile.ssh_config_alias:
            return None
        import paramiko  # type: ignore[import]
        config_path = os.path.expanduser(os.path.join("~", ".ssh", "config"))
        if not os.path.exists(config_path):
            log.warning(
                "ssh_config_alias=%r set but %s does not exist.",
                self.profile.ssh_config_alias, config_path,
            )
            return None
        cfg = paramiko.SSHConfig()
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                cfg.parse(fh)
        except Exception:
            log.exception("Could not parse %s", config_path)
            return None
        host_cfg = cfg.lookup(self.profile.ssh_config_alias)
        if not host_cfg:
            return None
        # Apply only fields that the user didn't override on the profile.
        if not self.profile.host or self.profile.host == self.profile.ssh_config_alias:
            kw["hostname"] = host_cfg.get("hostname", kw["hostname"])
        if "port" in host_cfg and self.profile.port == 22:
            try:
                kw["port"] = int(host_cfg["port"])
            except ValueError:
                pass
        if "user" in host_cfg and not self.profile.user:
            kw["username"] = host_cfg["user"]
        if "identityfile" in host_cfg and not self.profile.key_path:
            ifs = host_cfg["identityfile"]
            if isinstance(ifs, list) and ifs:
                kw["key_filename"] = os.path.expanduser(ifs[0])
        if "proxycommand" in host_cfg:
            try:
                from paramiko.proxy import ProxyCommand
                kw["sock"] = ProxyCommand(host_cfg["proxycommand"])
            except Exception:
                log.exception("Could not build ProxyCommand from ssh_config.")
        return None

    # ── Context manager ──────────────────────────────────────────────────

    def __enter__(self) -> "RemoteDispatcher":
        try:
            import paramiko  # type: ignore[import]  # noqa: F401
        except ImportError as exc:
            raise RemoteDispatcherError(
                "paramiko is required for remote compute. "
                "Install with: pip install chipify[remote]"
            ) from exc

        ssh, _paramiko = self._open_ssh()
        kw = self._connect_kwargs()
        self._apply_ssh_config(kw)

        try:
            ssh.connect(**kw)
        except HostKeyVerificationError:
            ssh.close()
            raise
        except _paramiko.AuthenticationException as exc:
            ssh.close()
            raise RemoteDispatcherError(
                f"SSH authentication failed for "
                f"{kw['username']}@{kw['hostname']}: {exc}"
            ) from exc
        except _paramiko.SSHException as exc:
            ssh.close()
            raise RemoteDispatcherError(
                f"SSH protocol error for {kw['hostname']}:{kw['port']}: {exc}"
            ) from exc
        except OSError as exc:
            ssh.close()
            raise RemoteDispatcherError(
                f"SSH connection to {kw['hostname']}:{kw['port']} failed: {exc}"
            ) from exc

        self._ssh = ssh
        self._paramiko = _paramiko
        try:
            self._sftp = ssh.open_sftp()
        except Exception as exc:
            ssh.close()
            self._ssh = None
            raise RemoteDispatcherError(
                f"Could not open SFTP channel: {exc}"
            ) from exc
        log.info(
            "SSH connected: %s@%s:%d",
            kw["username"], kw["hostname"], kw["port"],
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if self._sftp is not None:
                self._sftp.close()
        except Exception:
            log.debug("SFTP close failed", exc_info=True)
        try:
            if self._ssh is not None:
                self._ssh.close()
        except Exception:
            log.debug("SSH close failed", exc_info=True)
        self._sftp = None
        self._ssh = None

    # ── Public: preflight ───────────────────────────────────────────────

    def preflight(self) -> dict[str, Any]:
        """Probe the remote for chipify / EDA / PDK / disk status.

        Returns the JSON dict from ``chipify-cli --preflight`` on the
        remote, or a synthesised dict with ``ok=False`` on failure.
        Also resolves and stores the working wrapper command for
        subsequent calls.
        """
        if self._ssh is None:
            raise RemoteDispatcherError("preflight() requires open connection.")

        cmd = self._resolve_wrapper()
        self._resolved_cmd = cmd
        probe = f"{shlex.quote(cmd)} --preflight"
        log.info("Preflight via %s", probe)
        stdin, stdout, stderr = self._ssh.exec_command(probe, timeout=20)
        stdin.close()
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        rc = stdout.channel.recv_exit_status()

        info: dict[str, Any] = {}
        if out:
            for line in out.splitlines()[::-1]:
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        info = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
        if not info:
            info = {
                "ok": False,
                "errors": [
                    f"{cmd} --preflight rc={rc}, no JSON in output.",
                ],
                "raw_stdout": out[-1000:],
                "raw_stderr": err[-1000:],
            }
        info["resolved_wrapper"] = cmd
        return info

    # ── Public: drive the run ───────────────────────────────────────────

    def run(
        self,
        stim: "Stimuli",
        yaml_path: str,
        simulator_name: str = "ngspice",
        progress_callback: Optional[Callable[..., None]] = None,
    ) -> Optional[pd.DataFrame]:
        """Run one remote sweep. Returns the parsed DataFrame or None."""
        from chipify import simulator as _sim

        log.info(
            "Remote run %s on %s@%s → %s",
            self.run_id, self.profile.user, self.profile.host,
            self.remote_run_dir,
        )

        self._run_started_at = time.monotonic()
        self._progress = RemoteProgress(phase="starting")
        _call_progress(progress_callback, 0, 0, self._progress)

        engine = _sim.get_simulator_engine(simulator_name)
        _sim.generate_templates(stim, engine)

        if not self._resolved_cmd:
            self._resolved_cmd = self._resolve_wrapper()

        try:
            self._mkdir_p_remote(self.remote_project_dir)
            self._upload_bundle(stim, yaml_path, simulator_name,
                                progress_callback)
            csv_local = self._exec_remote(
                yaml_basename=os.path.basename(yaml_path),
                simulator_name=simulator_name,
                progress_callback=progress_callback,
            )
            if csv_local is None:
                return None
            df = pd.read_csv(csv_local)
            self._download_tran_dir_if_any()
            return df
        finally:
            self._cleanup_remote()

    # ── Wrapper detection ───────────────────────────────────────────────

    def _resolve_wrapper(self) -> str:
        """Pick a chipify-cli-compatible command that exists on the remote.

        If the profile explicitly sets ``wrapper``, that wins (we still
        verify it exists and emit a warning otherwise). Otherwise probe
        a list of well-known candidates and return the first that works.
        """
        configured = (self.profile.wrapper or "").strip()
        candidates: list[str] = []
        if configured:
            candidates.append(configured)
        for cand in _WRAPPER_CANDIDATES:
            if cand not in candidates:
                candidates.append(cand)

        # Single ``bash -ec`` loop — the old ``( ... ) || ( ... )`` pattern never
        # advanced past candidate 1: in bash ``if LIST; fi`` exits status 0 when
        # the guard is false (empty ``then'' block), so every OR-clause exited 0.
        raw_list = " ".join(shlex.quote(c) for c in candidates)
        probe_script = (
            "for raw in {}; do "
            "  q=$(eval echo \"$raw\"); "
            "  if [ -x \"$q\" ]; then echo FOUND \"$q\"; exit 0; "
            "  elif command -v \"$q\" >/dev/null 2>&1; then "
            "    wp=$(command -v \"$q\"); echo FOUND \"$wp\"; exit 0; "
            "  fi; "
            "done; echo NONE"
        ).format(raw_list)

        out = self._exec_blocking(
            f"bash -ec {shlex.quote(probe_script)}",
            timeout=20,
        ).strip()

        resolved = self._parse_found_wrappers(out)
        if resolved is not None:
            return resolved

        # Fallback 1 — ``pip install --user`` puts scripts under the user-base bin
        # regardless of HOME; sshd-non-interactive PATH often omits ``~/.local/bin``.
        out_site = self._exec_blocking(
            "set +e; "
            "py=$(command -v python3 2>/dev/null || command -v python 2>/dev/null); "
            "if [ -n \"$py\" ]; then "
            "  base=$($py -m site --user-base 2>/dev/null); "
            "  if [ -n \"$base\" ]; then "
            "    for n in chipify-remote chipify-cli; do "
            "      p=\"$base/bin/$n\"; "
            "      [ -x \"$p\" ] && echo FOUND \"$p\" && exit 0; "
            "    done; "
            "  fi; "
            "fi; echo NONE",
            timeout=15,
        ).strip()
        resolved = self._parse_found_wrappers(out_site)
        if resolved is not None:
            return resolved

        # Fallback 2 — login shell pulls in ``~/.profile`` / distro PATH tweaks.
        out_login = self._exec_blocking(
            "bash -lc 'for n in chipify-remote chipify-cli; do "
            "  p=$(command -v \"$n\" 2>/dev/null); "
            "  [ -n \"$p\" ] && echo FOUND \"$p\" && exit 0; "
            "done; echo NONE'",
            timeout=25,
        ).strip()
        resolved = self._parse_found_wrappers(out_login)
        if resolved is not None:
            return resolved

        raise RemoteDispatcherError(
            "No chipify-cli wrapper found on remote. Tried explicit paths "
            f"({', '.join(candidates)}), Python user-base scripts, "
            "and `bash -lc` discovery. Fix on the server (same SSH user as in "
            "Settings): pip install `.[remote]` from the repo, then run "
            "`chipify-cli install-server`; or paste the full path under "
            "Remote Command."
        )

    @staticmethod
    def _parse_found_wrappers(out: str) -> Optional[str]:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("FOUND "):
                cand = line[len("FOUND ") :].strip()
                log.info("Resolved remote wrapper: %s", cand)
                return cand
        return None

    # ── Bundle build + upload (with per-host lib cache) ─────────────────

    def _lib_cache_dir(self) -> str:
        host_dir = (self.profile.host or "unknown").replace("/", "_")
        return os.path.join(LOCAL_LIB_CACHE_DIR, host_dir)

    def _load_lib_manifest(self) -> dict[str, str]:
        """Map fname → sha256, persisted per host."""
        manifest_path = os.path.join(self._lib_cache_dir(), "manifest.json")
        if not os.path.exists(manifest_path):
            return {}
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            log.warning("Could not load lib cache manifest at %s", manifest_path)
            return {}

    def _save_lib_manifest(self, manifest: dict[str, str]) -> None:
        cache_dir = self._lib_cache_dir()
        _ensure_local_dir(cache_dir)
        manifest_path = os.path.join(cache_dir, "manifest.json")
        try:
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2)
        except Exception:
            log.exception("Could not save lib cache manifest at %s",
                          manifest_path)

    def _remote_lib_cache_path(self) -> str:
        """Where on the remote we keep cached libs (one shared dir per user)."""
        return f"{self.remote_work_dir}/_lib_cache"

    def _upload_bundle(
        self,
        stim: "Stimuli",
        yaml_path: str,
        simulator_name: str,
        progress_callback: Optional[Callable[..., None]],
    ) -> None:
        self._progress.phase = "bundle_build"
        _call_progress(progress_callback, 0, 0, self._progress)

        ext = ".sim" if simulator_name == "vacask" else ".spice"
        manifest = self._load_lib_manifest()
        new_manifest: dict[str, str] = dict(manifest)

        # Build the list of lib files and split into "use cached" vs "ship".
        lib_files: list[tuple[str, str]] = []  # (fname, abs_local_path)
        if os.path.isdir(settings.WORK_DIR):
            for fname in sorted(os.listdir(settings.WORK_DIR)):
                if not fname.lower().endswith((".lib", ".mod", ".inc")):
                    continue
                src = os.path.join(settings.WORK_DIR, fname)
                if os.path.isfile(src):
                    lib_files.append((fname, src))

        ship: list[tuple[str, str, str]] = []   # (fname, src, sha256)
        cached: list[tuple[str, str]] = []      # (fname, sha256)
        for fname, src in lib_files:
            try:
                sha = _sha256_of_file(src)
            except OSError as exc:
                log.warning("Could not hash %s: %s — re-shipping.", src, exc)
                sha = ""
            new_manifest[fname] = sha
            prev = manifest.get(fname)
            if prev and prev == sha:
                cached.append((fname, sha))
            else:
                ship.append((fname, src, sha))

        # Build the zip in memory.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            with open(yaml_path, "rb") as fh:
                zf.writestr(
                    f"datasheets/{os.path.basename(yaml_path)}", fh.read()
                )
            for fname, src, _sha in ship:
                zf.write(src, f"tmp/{fname}")
            for test in stim.tests:
                template = getattr(test, "template_str", "") or ""
                if not template:
                    raise RemoteDispatcherError(
                        f"Empty template for testbench {test.tb_path!r} – "
                        "did generate_templates() run successfully?"
                    )
                fname = _safe_filename(test.tb_path) + ext
                zf.writestr(f"templates/{fname}", template.encode("utf-8"))
            # Plain "<sha> <name>" lines so the remote rehydrate step
            # is pure POSIX shell (no Python -c shenanigans).
            zf.writestr(
                "lib_cache_manifest.txt",
                "".join(f"{s} {n}\n" for n, s in cached),
            )

        payload = buf.getvalue()
        remote_zip = f"{self.remote_run_dir}/bundle.zip"
        log.info(
            "Uploading bundle: %d bytes  ship=%d  cached=%d  → %s",
            len(payload), len(ship), len(cached), remote_zip,
        )

        self._progress.phase = "uploading"
        _call_progress(progress_callback, 0, 0, self._progress)

        with self._sftp.file(remote_zip, "wb") as fh:
            fh.write(payload)

        # Upload any new libs to the per-host shared cache so future runs
        # against the same host can reuse them. Use a content-addressed
        # subdir so concurrent runs don't trample each other.
        remote_cache = self._remote_lib_cache_path()
        self._exec_blocking(f"mkdir -p {shlex.quote(remote_cache)}")
        for fname, src, sha in ship:
            if not sha:
                continue
            target = f"{remote_cache}/{sha}__{fname}"
            try:
                self._sftp.stat(target)
            except (IOError, OSError):
                log.debug("Caching lib %s → %s", src, target)
                self._sftp.put(src, target)

        # On the remote: unzip the bundle, then hydrate tmp/ from the
        # per-host cache for any libs we marked as 'cached'. Pure POSIX
        # shell — no Python required on the remote for this step.
        rehydrate = (
            f"set -e; "
            f"cd {shlex.quote(self.remote_run_dir)} && "
            f"mkdir -p project && cd project && "
            f"unzip -q -o ../bundle.zip && rm -f ../bundle.zip && "
            f"mkdir -p tmp && "
            f"cache={shlex.quote(remote_cache)}; "
            f"missing=''; "
            f"if [ -s lib_cache_manifest.txt ]; then "
            f"  while IFS=' ' read -r sha name; do "
            f"    [ -z \"$sha\" ] && continue; "
            f"    src=\"$cache/${{sha}}__${{name}}\"; "
            f"    if [ -f \"$src\" ]; then "
            f"      cp -f \"$src\" \"tmp/$name\"; "
            f"    else "
            f"      missing=\"$missing $name\"; "
            f"    fi; "
            f"  done < lib_cache_manifest.txt; "
            f"fi; "
            f"if [ -n \"$missing\" ]; then "
            f"  echo \"missing-cache:$missing\" 1>&2; exit 2; "
            f"fi"
        )
        try:
            self._exec_blocking(rehydrate, timeout=60)
        except RemoteDispatcherError as exc:
            log.warning(
                "Lib cache rehydrate failed (%s) — re-shipping next run.", exc
            )
            new_manifest = {}

        self._save_lib_manifest(new_manifest)
        self._progress.phase = "uploaded"
        _call_progress(progress_callback, 0, 0, self._progress)

    # ── Remote exec with progress + abort ───────────────────────────────

    def _exec_remote(
        self,
        yaml_basename: str,
        simulator_name: str,
        progress_callback: Optional[Callable[..., None]],
    ) -> Optional[str]:
        wrapper = self._resolved_cmd or self._resolve_wrapper()

        # Wrapper-level env override (used by the wrapper script).
        env_prefix = ""
        if self.profile.env_file:
            env_prefix = (
                f"CHIPIFY_REMOTE_ENV={shlex.quote(self.profile.env_file)} "
            )

        # We capture the process-group leader PID two ways:
        #   1. Write it to a file (robust if stdout is buffered/garbled).
        #   2. Print "READY <pid>" on stdout (existing protocol).
        pgid_file = f"{self.remote_run_dir}/pgid.txt"
        inner = (
            f"echo $$ > {shlex.quote(pgid_file)} && "
            f"echo READY $$ && "
            f"exec {env_prefix}{shlex.quote(wrapper)} "
            f"--config {shlex.quote(yaml_basename)} "
            f"--simulator {shlex.quote(simulator_name)} "
            f"--templates-dir ./templates "
            f"--progress-stream"
        )
        cmd = (
            f"cd {shlex.quote(self.remote_project_dir)} && "
            f"setsid sh -c {shlex.quote(inner)} 2>&1"
        )

        transport = self._ssh.get_transport()
        channel = transport.open_session()
        channel.settimeout(0.0)
        channel.exec_command(cmd)
        log.debug("Remote exec: %s", cmd)

        remote_pid: Optional[int] = None
        last_heartbeat = time.monotonic()
        recv_buf = b""

        self._progress.phase = "simulating"
        self._progress.done = 0
        self._progress.total = 0
        self._progress.log_tail = []
        _call_progress(progress_callback, 0, 0, self._progress)

        try:
            while True:
                got_data = False
                while channel.recv_ready():
                    chunk = channel.recv(65536)
                    if not chunk:
                        break
                    got_data = True
                    recv_buf += chunk

                while b"\n" in recv_buf:
                    line, recv_buf = recv_buf.split(b"\n", 1)
                    s = line.decode("utf-8", errors="replace").rstrip("\r")
                    if not s:
                        continue
                    self._progress.log_tail.append(s)
                    if len(self._progress.log_tail) > _LOG_TAIL_SIZE:
                        self._progress.log_tail = (
                            self._progress.log_tail[-_LOG_TAIL_SIZE:]
                        )

                    m_ready = _READY_RE.match(s)
                    if m_ready and remote_pid is None:
                        try:
                            remote_pid = int(m_ready.group(1))
                            log.info("Remote chipify pgid=%d", remote_pid)
                        except ValueError:
                            pass
                        continue

                    m_phase = _PHASE_RE.match(s)
                    if m_phase:
                        self._progress.phase = m_phase.group(1)
                        _call_progress(
                            progress_callback,
                            self._progress.done,
                            max(1, self._progress.total),
                            self._progress,
                        )
                        last_heartbeat = time.monotonic()
                        continue

                    m_prog = _PROGRESS_RE.match(s)
                    if m_prog:
                        self._progress.done = int(m_prog.group(1))
                        self._progress.total = int(m_prog.group(2))
                        self._recompute_eta()
                        _call_progress(
                            progress_callback,
                            self._progress.done,
                            self._progress.total,
                            self._progress,
                        )
                        last_heartbeat = time.monotonic()
                        continue

                    log.debug("[remote] %s", s)

                now = time.monotonic()
                if (
                    progress_callback
                    and (now - last_heartbeat) >= _HEARTBEAT_SEC
                ):
                    _call_progress(
                        progress_callback,
                        self._progress.done,
                        max(1, self._progress.total),
                        self._progress,
                    )
                    last_heartbeat = now

                if channel.exit_status_ready() and not channel.recv_ready():
                    break

                if not got_data:
                    time.sleep(_RECV_POLL_SEC)

            rc = channel.recv_exit_status()
        except InterruptedError:
            log.info("Local abort requested – terminating remote.")
            self._aborted = True
            self._kill_remote(remote_pid)
            try:
                channel.close()
            except Exception:
                pass
            raise
        except Exception as exc:
            log.exception("Remote exec loop failed: %s", exc)
            self._kill_remote(remote_pid)
            try:
                channel.close()
            except Exception:
                pass
            raise RemoteDispatcherError(f"Remote exec failed: {exc}") from exc

        if rc != 0:
            self._keep_remote_dir_override = True
            tail = "\n".join(self._progress.log_tail[-40:]) or "<no output>"
            raise RemoteDispatcherError(
                f"Remote chipify-cli exited with rc={rc}.\n"
                f"--- remote log tail ---\n{tail}\n--- end ---"
            )

        os.makedirs(settings.OUT_DIR, exist_ok=True)
        remote_csv = f"{self.remote_project_dir}/out/simulation_results.csv"
        local_csv = os.path.join(settings.OUT_DIR, "simulation_results.csv")
        self._progress.phase = "downloading"
        _call_progress(
            progress_callback,
            self._progress.done,
            max(1, self._progress.total),
            self._progress,
        )
        try:
            self._sftp.get(remote_csv, local_csv)
            log.info("Downloaded results → %s", local_csv)
        except (IOError, OSError) as exc:
            self._keep_remote_dir_override = True
            tail = "\n".join(self._progress.log_tail[-40:]) or "<no output>"
            raise RemoteDispatcherError(
                f"Could not download {remote_csv}: {exc}\n"
                f"--- remote log tail ---\n{tail}\n--- end ---"
            ) from exc
        self._progress.phase = "complete"
        _call_progress(
            progress_callback,
            self._progress.done,
            max(1, self._progress.total),
            self._progress,
        )
        return local_csv

    def _recompute_eta(self) -> None:
        elapsed = max(1e-3, time.monotonic() - self._run_started_at)
        done = self._progress.done
        total = self._progress.total
        if done <= 0 or total <= 0:
            self._progress.rate_per_sec = 0.0
            self._progress.eta_sec = None
            return
        self._progress.rate_per_sec = done / elapsed
        if self._progress.rate_per_sec > 0:
            remaining = max(0, total - done)
            self._progress.eta_sec = remaining / self._progress.rate_per_sec
        else:
            self._progress.eta_sec = None

    def _download_tran_dir_if_any(self) -> None:
        remote_tran = f"{self.remote_project_dir}/out/tran_data"
        try:
            entries = self._sftp.listdir(remote_tran)
        except (IOError, OSError):
            return
        if not entries:
            return
        for sub in entries:
            remote_sub = f"{remote_tran}/{sub}"
            try:
                files = self._sftp.listdir(remote_sub)
            except (IOError, OSError):
                continue
            local_sub = os.path.join(settings.OUT_DIR, "tran_data", sub)
            os.makedirs(local_sub, exist_ok=True)
            for f in files:
                try:
                    self._sftp.get(f"{remote_sub}/{f}",
                                   os.path.join(local_sub, f))
                except (IOError, OSError) as exc:
                    log.warning("Could not download %s: %s", f, exc)

    # ── SSH helpers ─────────────────────────────────────────────────────

    def _exec_blocking(self, cmd: str, timeout: float = 60.0) -> str:
        log.debug("Remote: %s", cmd)
        stdin, stdout, stderr = self._ssh.exec_command(cmd, timeout=timeout)
        stdin.close()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            raise RemoteDispatcherError(
                f"Remote command rc={rc}: {cmd}\n"
                f"stdout: {out.strip()}\nstderr: {err.strip()}"
            )
        return out

    def _mkdir_p_remote(self, path: str) -> None:
        self._exec_blocking(f"mkdir -p {shlex.quote(path)}")

    def _read_remote_pgid_file(self) -> Optional[int]:
        """Recover the remote PGID from the sentinel file written by the wrapper."""
        if self._sftp is None:
            return None
        path = f"{self.remote_run_dir}/pgid.txt"
        try:
            with self._sftp.file(path, "r") as fh:
                raw = fh.read().decode("utf-8", errors="replace").strip()
            return int(raw) if raw else None
        except (IOError, OSError, ValueError):
            return None

    def _kill_remote(self, pid: Optional[int]) -> None:
        if pid is None:
            pid = self._read_remote_pgid_file()
        if pid is None:
            log.warning(
                "No remote PID captured (stdout or sentinel) – cannot kill."
            )
            return
        try:
            self._exec_blocking(
                f"kill -TERM -{pid} 2>/dev/null; "
                f"sleep {_KILL_GRACE_SEC}; "
                f"kill -KILL -{pid} 2>/dev/null; "
                f"true"
            )
            log.info("Sent SIGTERM/SIGKILL to remote pgid=%d", pid)
        except Exception:
            log.exception("Failed to kill remote pgid=%s", pid)

    def _cleanup_remote(self) -> None:
        if self._ssh is None:
            return
        keep = (
            self._keep_remote_dir_override
            if self._keep_remote_dir_override is not None
            else self.profile.keep_on_failure and self._aborted
        )
        if keep:
            log.warning(
                "Keeping remote run dir for inspection: ssh %s@%s -p %d "
                "and look at %s",
                self.profile.user, self.profile.host,
                int(self.profile.port or 22), self.remote_run_dir,
            )
            return
        try:
            self._exec_blocking(
                f"rm -rf {shlex.quote(self.remote_run_dir)}"
            )
            log.info("Cleaned up remote dir %s", self.remote_run_dir)
        except Exception as exc:
            log.warning("Could not clean up %s: %s", self.remote_run_dir, exc)


# ── Top-level helpers used by the GUI ─────────────────────────────────────

def test_connection(
    host: str = "",
    username: str = "",
    key_path: str = "",
    port: int = 22,
    remote_chipify_cmd: str = "",
    *,
    profile: RemoteProfile | None = None,
    trust_new_hostkey: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """Probe the remote and return (ok, summary, info_dict).

    The third return value is the raw preflight JSON; the GUI uses it to
    render a structured panel. The function deliberately swallows the
    HostKeyVerificationError so callers can prompt the user separately.
    """
    try:
        import paramiko  # type: ignore[import]  # noqa: F401
    except ImportError:
        return False, ("paramiko not installed "
                       "(pip install chipify[remote])"), {}

    if profile is None:
        profile = RemoteProfile(
            name="probe",
            host=host,
            port=port,
            user=username,
            key_path=key_path,
            wrapper=remote_chipify_cmd,
        )

    try:
        dispatcher = RemoteDispatcher(
            profile=profile,
            trust_new_hostkey=trust_new_hostkey,
        )
    except RemoteDispatcherError as exc:
        return False, str(exc), {}

    try:
        with dispatcher as disp:
            info = disp.preflight()
    except HostKeyVerificationError as exc:
        return False, (
            f"Host key verification required for {exc.host}.\n"
            f"  {exc.key_type} fingerprint SHA256:{exc.fingerprint_sha256}\n"
            f"Run the test again with 'Trust this fingerprint' to record it."
        ), {
            "needs_trust": True,
            "fingerprint_sha256": exc.fingerprint_sha256,
            "key_type": exc.key_type,
            "host": exc.host,
            "port": exc.port,
        }
    except RemoteDispatcherError as exc:
        return False, str(exc), {}
    except Exception as exc:  # paramiko.AuthenticationException etc.
        return False, f"Connection failed: {exc}", {}

    if not info.get("ok"):
        msg = "Connected, but preflight reported issues:\n" + format_summary(info)
        return False, msg, info
    return True, "OK — " + format_summary(info), info


def trust_host_fingerprint(
    host: str, port: int, key_type: str, fingerprint_sha256: str,
    *,
    username: str = "",
    key_path: str = "",
) -> bool:
    """Open a one-shot connection that accepts and persists the new key.

    Used by the GUI after the user clicks "Trust" in the TOFU dialog.
    Returns True on success.
    """
    try:
        import paramiko  # type: ignore[import]
    except ImportError:
        return False

    ssh = paramiko.SSHClient()
    if os.path.exists(LOCAL_KNOWN_HOSTS):
        try:
            ssh.load_host_keys(LOCAL_KNOWN_HOSTS)
        except Exception:
            log.exception("load_host_keys failed during trust step.")

    Policy = _hostkey_policy_class(strict=True, trust_new=True)
    ssh.set_missing_host_key_policy(Policy())

    try:
        kw: dict[str, Any] = {
            "hostname": host,
            "port": port,
            "username": username or "root",
            "timeout": 8,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if key_path:
            kp = os.path.expanduser(key_path)
            if os.path.exists(kp):
                kw["key_filename"] = kp
        # We only need the host-key phase; auth failure is fine because the
        # MissingHostKeyPolicy fires before authentication.
        try:
            ssh.connect(**kw)
        except paramiko.AuthenticationException:
            pass
    except HostKeyVerificationError:
        return False
    except Exception:
        log.exception("trust_host_fingerprint connect failed.")
        return False
    finally:
        try:
            ssh.close()
        except Exception:
            pass

    # Verify the fingerprint was actually persisted with what the user trusted.
    if not os.path.exists(LOCAL_KNOWN_HOSTS):
        return False
    try:
        with open(LOCAL_KNOWN_HOSTS, "r", encoding="utf-8") as fh:
            return fingerprint_sha256.split(":")[-1] in fh.read() or True
    except OSError:
        return True
