"""
remote_dispatcher.py – Offload simulation sweeps to a remote Linux server.

Local responsibilities:
    1. Run xschem and prepare Jinja2 templates (``simulator.generate_templates``).
    2. Bundle templates + datasheet YAML + SPICE library files (.lib/.mod/.inc).
    3. SFTP upload, SSH exec chipify-cli on the remote, stream progress, abort.
    4. SFTP download the results CSV (and transient data) back into OUT_DIR.

Remote responsibilities (handled by chipify-cli with --templates-dir):
    Skip xschem, read pre-rendered templates from disk, run the existing
    multiprocessing.Pool sweep there.

Authentication is key-path only – no password handling.
"""
from __future__ import annotations

import io
import logging
import os
import re
import shlex
import time
import uuid
import zipfile
from typing import Callable, Optional, TYPE_CHECKING

import pandas as pd

from chipify import settings

if TYPE_CHECKING:
    from chipify.util import Stimuli

log = logging.getLogger("chipify.remote_dispatcher")

_PROGRESS_RE = re.compile(r"^PROGRESS:\s+(\d+)\s+(\d+)\s*$")
_READY_RE = re.compile(r"^READY\s+(\d+)\s*$")

# How often we poke progress_callback even when the remote is silent so that
# the GUI stop_event has a chance to interrupt the loop.
_HEARTBEAT_SEC = 0.5
_RECV_POLL_SEC = 0.1


class RemoteDispatcherError(RuntimeError):
    """Raised when the remote sweep cannot be completed."""


def _safe_filename(path: str) -> str:
    return path.replace("/", "__").replace("\\", "__")


class RemoteDispatcher:
    """Owns one SSH+SFTP session and one remote run directory."""

    def __init__(
        self,
        host: str,
        username: str,
        key_path: str,
        remote_work_dir: str = "/tmp/chipify_remote",
        port: int = 22,
        remote_chipify_cmd: str = "chipify-cli",
        connect_timeout: int = 15,
    ) -> None:
        if not host or not username or not key_path:
            raise RemoteDispatcherError(
                "Remote settings incomplete: host, username and key path are required."
            )
        key_path = os.path.expanduser(key_path)
        if not os.path.exists(key_path):
            raise RemoteDispatcherError(f"SSH key not found: {key_path}")

        self.host = host
        self.username = username
        self.key_path = key_path
        self.port = port
        self.remote_work_dir = remote_work_dir.rstrip("/") or "/tmp/chipify_remote"
        self.remote_chipify_cmd = remote_chipify_cmd
        self.connect_timeout = connect_timeout

        self.run_id = uuid.uuid4().hex[:12]
        self.remote_run_dir = f"{self.remote_work_dir}/run_{self.run_id}"
        self.remote_project_dir = f"{self.remote_run_dir}/project"

        self._ssh = None
        self._sftp = None
        self._paramiko = None

    # ── Context manager ──────────────────────────────────────────────────────

    def __enter__(self) -> "RemoteDispatcher":
        try:
            import paramiko  # type: ignore[import]
        except ImportError as exc:
            raise RemoteDispatcherError(
                "paramiko is required for remote compute. "
                "Install with: pip install chipify[remote]"
            ) from exc

        self._paramiko = paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                key_filename=self.key_path,
                timeout=self.connect_timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        except paramiko.AuthenticationException as exc:
            raise RemoteDispatcherError(
                f"SSH authentication failed for {self.username}@{self.host}: {exc}"
            ) from exc
        except paramiko.SSHException as exc:
            raise RemoteDispatcherError(
                f"SSH protocol error for {self.host}:{self.port}: {exc}"
            ) from exc
        except OSError as exc:
            raise RemoteDispatcherError(
                f"SSH connection to {self.host}:{self.port} failed: {exc}"
            ) from exc

        self._ssh = ssh
        try:
            self._sftp = ssh.open_sftp()
        except Exception as exc:
            ssh.close()
            self._ssh = None
            raise RemoteDispatcherError(
                f"Could not open SFTP channel: {exc}"
            ) from exc
        log.info("SSH connected: %s@%s:%d", self.username, self.host, self.port)
        return self

    def __exit__(self, *_exc) -> None:
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

    # ── Public entry point ───────────────────────────────────────────────────

    def run(
        self,
        stim: "Stimuli",
        yaml_path: str,
        simulator_name: str = "ngspice",
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Optional[pd.DataFrame]:
        """Drive a full remote sweep. Returns the parsed DataFrame or None."""
        from chipify import simulator as _sim

        log.info(
            "Remote run %s on %s@%s → %s",
            self.run_id, self.username, self.host, self.remote_run_dir,
        )

        engine = _sim.get_simulator_engine(simulator_name)
        # Local xschem + jinja preparation.
        _sim.generate_templates(stim, engine)

        try:
            self._mkdir_p_remote(self.remote_project_dir)
            self._upload_bundle(stim, yaml_path, simulator_name)
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

    # ── Bundle build + upload ────────────────────────────────────────────────

    def _upload_bundle(
        self, stim: "Stimuli", yaml_path: str, simulator_name: str
    ) -> None:
        ext = ".sim" if simulator_name == "vacask" else ".spice"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            with open(yaml_path, "rb") as fh:
                zf.writestr(
                    f"datasheets/{os.path.basename(yaml_path)}", fh.read()
                )
            for fname in os.listdir(settings.WORK_DIR):
                if not fname.lower().endswith((".lib", ".mod", ".inc")):
                    continue
                src = os.path.join(settings.WORK_DIR, fname)
                if os.path.isfile(src):
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

        payload = buf.getvalue()
        remote_zip = f"{self.remote_run_dir}/bundle.zip"
        log.info("Uploading bundle (%d bytes) → %s", len(payload), remote_zip)
        with self._sftp.file(remote_zip, "wb") as fh:
            fh.write(payload)

        self._exec_blocking(
            f"cd {shlex.quote(self.remote_run_dir)} && "
            f"mkdir -p project && cd project && "
            f"unzip -q -o ../bundle.zip && rm -f ../bundle.zip"
        )

    # ── Remote exec with progress + abort ────────────────────────────────────

    def _exec_remote(
        self,
        yaml_basename: str,
        simulator_name: str,
        progress_callback: Optional[Callable[[int, int], None]],
    ) -> Optional[str]:
        # setsid creates a new process group so we can kill the whole tree by
        # sending SIGTERM to -PID. The wrapper prints "READY <pid>" so we
        # capture the group leader id before chipify-cli starts.
        inner = (
            f"echo READY $$ && "
            f"exec {shlex.quote(self.remote_chipify_cmd)} "
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
        progress_done = 0
        progress_total = 0
        last_heartbeat = time.monotonic()
        recent_lines: list[str] = []
        recv_buf = b""

        try:
            while True:
                # Drain stdout
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
                    recent_lines.append(s)
                    if len(recent_lines) > 200:
                        recent_lines = recent_lines[-200:]

                    m_ready = _READY_RE.match(s)
                    if m_ready and remote_pid is None:
                        try:
                            remote_pid = int(m_ready.group(1))
                            log.info("Remote chipify pgid=%d", remote_pid)
                        except ValueError:
                            pass
                        continue

                    m_prog = _PROGRESS_RE.match(s)
                    if m_prog:
                        progress_done = int(m_prog.group(1))
                        progress_total = int(m_prog.group(2))
                        if progress_callback:
                            progress_callback(progress_done, progress_total)
                        last_heartbeat = time.monotonic()
                        continue

                    log.debug("[remote] %s", s)

                # Heartbeat: let progress_callback observe stop_event
                # even if remote is silent.
                now = time.monotonic()
                if (
                    progress_callback
                    and (now - last_heartbeat) >= _HEARTBEAT_SEC
                ):
                    progress_callback(progress_done, max(1, progress_total))
                    last_heartbeat = now

                if channel.exit_status_ready() and not channel.recv_ready():
                    break

                if not got_data:
                    time.sleep(_RECV_POLL_SEC)

            rc = channel.recv_exit_status()
        except InterruptedError:
            log.info("Local abort requested – terminating remote.")
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
            tail = "\n".join(recent_lines[-40:]) or "<no output>"
            raise RemoteDispatcherError(
                f"Remote chipify-cli exited with rc={rc}.\n"
                f"--- remote log tail ---\n{tail}\n--- end ---"
            )

        # Download results CSV
        os.makedirs(settings.OUT_DIR, exist_ok=True)
        remote_csv = f"{self.remote_project_dir}/out/simulation_results.csv"
        local_csv = os.path.join(settings.OUT_DIR, "simulation_results.csv")
        try:
            self._sftp.get(remote_csv, local_csv)
            log.info("Downloaded results → %s", local_csv)
        except (IOError, OSError) as exc:
            tail = "\n".join(recent_lines[-40:]) or "<no output>"
            raise RemoteDispatcherError(
                f"Could not download {remote_csv}: {exc}\n"
                f"--- remote log tail ---\n{tail}\n--- end ---"
            ) from exc
        return local_csv

    def _download_tran_dir_if_any(self) -> None:
        """Mirror remote out/tran_data/* into local OUT_DIR/tran_data/."""
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

    # ── SSH helpers ──────────────────────────────────────────────────────────

    def _exec_blocking(self, cmd: str) -> str:
        """Run *cmd* on remote, raise if rc != 0, return combined stdout."""
        log.debug("Remote: %s", cmd)
        stdin, stdout, stderr = self._ssh.exec_command(cmd, timeout=60)
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

    def _kill_remote(self, pid: Optional[int]) -> None:
        if pid is None:
            log.warning("No remote PID captured – cannot kill.")
            return
        try:
            self._exec_blocking(
                f"kill -TERM -{pid} 2>/dev/null; "
                f"sleep 1; "
                f"kill -KILL -{pid} 2>/dev/null; "
                f"true"
            )
            log.info("Sent SIGTERM/SIGKILL to remote pgid=%d", pid)
        except Exception:
            log.exception("Failed to kill remote pgid=%s", pid)

    def _cleanup_remote(self) -> None:
        if self._ssh is None:
            return
        try:
            self._exec_blocking(
                f"rm -rf {shlex.quote(self.remote_run_dir)}"
            )
            log.info("Cleaned up remote dir %s", self.remote_run_dir)
        except Exception as exc:
            log.warning("Could not clean up %s: %s", self.remote_run_dir, exc)


def test_connection(
    host: str, username: str, key_path: str, port: int = 22,
    remote_chipify_cmd: str = "chipify-cli",
) -> tuple[bool, str]:
    """Quick connectivity probe for the settings dialog.

    Probes the configured *remote_chipify_cmd* (which may be a bare name on
    PATH like ``chipify-cli`` or an absolute path like
    ``/usr/local/bin/chipify-cli`` for a wrapper that shells into a docker
    container). Falls back to a direct file existence check if the command
    is absolute.
    """
    try:
        import paramiko  # type: ignore[import]
    except ImportError:
        return False, "paramiko not installed (pip install chipify[remote])"

    if not host or not username or not key_path:
        return False, "host, username and key path are required"

    key_path = os.path.expanduser(key_path)
    if not os.path.exists(key_path):
        return False, f"SSH key not found: {key_path}"

    cmd = (remote_chipify_cmd or "chipify-cli").strip() or "chipify-cli"
    if cmd.startswith("/"):
        probe = (
            f"if [ -x {shlex.quote(cmd)} ]; then "
            f"echo FOUND: {shlex.quote(cmd)}; uname -srm; "
            f"else echo MISSING: {shlex.quote(cmd)}; fi"
        )
    else:
        probe = (
            f"if command -v {shlex.quote(cmd)} >/dev/null 2>&1; then "
            f"echo FOUND: $(command -v {shlex.quote(cmd)}); uname -srm; "
            f"else echo MISSING: {shlex.quote(cmd)}; fi"
        )

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=host, port=port, username=username,
            key_filename=key_path, timeout=10,
            allow_agent=False, look_for_keys=False,
        )
        _, stdout, _ = ssh.exec_command(probe, timeout=10)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        stdout.channel.recv_exit_status()
        ssh.close()
        if out.startswith("FOUND:"):
            return True, f"OK – {out[len('FOUND:'):].strip()}"
        return True, (
            f"Connected, but '{cmd}' not found on remote.\n"
            f"Hints: use the absolute wrapper path (e.g. /usr/local/bin/chipify-cli) "
            f"or move the wrapper into /usr/bin (always on the non-interactive SSH PATH)."
        )
    except paramiko.AuthenticationException as exc:
        return False, f"Authentication failed: {exc}"
    except (paramiko.SSHException, OSError) as exc:
        return False, f"Connection failed: {exc}"
    finally:
        try:
            ssh.close()
        except Exception:
            pass
