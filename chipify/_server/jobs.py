"""
jobs.py – Subprocess-backed job manager for the chipify HTTPS server.

A *job* is one remote sweep:

    1. Client POSTs a bundle.zip containing pre-rendered Jinja2 templates,
       the datasheet YAML and any SPICE library files (.lib/.mod/.inc).
    2. The manager unzips that into ``<work_dir>/run_<job_id>/project`` and
       launches ``chipify-cli --templates-dir ./templates --progress-stream``
       in a new process session (so we can SIGTERM the whole group later).
    3. The chipify-cli stdout (the existing PHASE/PROGRESS/READY/log
       protocol) is forwarded line-by-line as Server-Sent Events.
    4. The client GETs the resulting ``simulation_results.csv`` and any
       transient files, then DELETEs the job.

This module never touches HTTP itself — see ``app.py``. The split keeps the
state machine testable without a TestClient.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import signal
import sys
import time
import uuid
import zipfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Optional

from chipify._server.protocol import LOG_TAIL_SIZE, SSE_KEEPALIVE

log = logging.getLogger("chipify._server.jobs")

_HEARTBEAT_SEC = 0.5
_KILL_GRACE_SEC = 2.0


class JobNotFound(KeyError):
    """Raised when a job_id does not exist (or has been cleaned up)."""


class JobAlreadyTerminated(RuntimeError):
    """Raised when an operation requires a live process but the job is done."""


@dataclass
class Job:
    job_id: str
    work_dir: Path                # <root>/run_<id>
    project_dir: Path             # <root>/run_<id>/project
    yaml_basename: str
    simulator: str
    keep_on_failure: bool = False
    proc: Optional[asyncio.subprocess.Process] = None
    pgid: Optional[int] = None
    started_at: float = 0.0
    finished_at: float = 0.0
    return_code: Optional[int] = None
    aborted: bool = False
    log_tail: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_TAIL_SIZE))
    # Each subscriber to /events gets a private queue. The reader task fans
    # lines out to every queue so multiple SSE clients could in principle
    # tail the same run (v1 only expects one).
    _subscribers: list["asyncio.Queue[Optional[str]]"] = field(default_factory=list)
    _reader_done: Optional["asyncio.Event"] = None


class JobManager:
    """Owns the run-directory tree and the live subprocesses.

    A single ``JobManager`` instance is attached to the FastAPI app and
    shared across all requests.
    """

    def __init__(self, work_dir: Path, *, chipify_cli: str | None = None) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # ``chipify_cli`` overrides the executable used to run jobs. Tests
        # pass a stub script here; production leaves it None and we fall
        # back to ``sys.executable -m chipify.cli`` for max portability
        # (works even if ~/.local/bin isn't on PATH for sshd-style subshells).
        self._chipify_cli_override = chipify_cli
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    # ── Job creation ──────────────────────────────────────────────────────

    async def create_job(
        self,
        bundle: bytes,
        yaml_basename: str,
        simulator: str,
        *,
        keep_on_failure: bool = False,
    ) -> str:
        """Allocate a run dir, unzip the bundle, return the job_id."""
        job_id = uuid.uuid4().hex[:12]
        run_dir = self.work_dir / f"run_{job_id}"
        project_dir = run_dir / "project"
        project_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._extract_bundle(bundle, project_dir)
        except Exception:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise
        # Surface any libs the client shipped at the root of the project so
        # ngspice .include statements resolve them. The bundle places libs
        # under ``tmp/`` (matching the local sweep convention).
        async with self._lock:
            self._jobs[job_id] = Job(
                job_id=job_id,
                work_dir=run_dir,
                project_dir=project_dir,
                yaml_basename=yaml_basename,
                simulator=simulator,
                keep_on_failure=keep_on_failure,
            )
        log.info("Created job %s in %s", job_id, run_dir)
        return job_id

    @staticmethod
    def _extract_bundle(payload: bytes, project_dir: Path) -> None:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            # Reject path-traversal entries before extracting anything.
            for name in zf.namelist():
                norm = os.path.normpath(name)
                if norm.startswith("..") or os.path.isabs(norm):
                    raise ValueError(f"Refusing unsafe path in bundle: {name!r}")
            zf.extractall(project_dir)

    # ── Subprocess launch + stdout fanout ────────────────────────────────

    async def start(self, job_id: str) -> None:
        job = self._require(job_id)
        if job.proc is not None:
            raise RuntimeError(f"Job {job_id} already started.")

        argv = self._build_argv(job)
        log.info("Launching job %s: %s", job_id, " ".join(argv))

        kwargs: dict = dict(
            cwd=str(job.project_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if os.name == "posix":
            # Own process group so kill -TERM -<pgid> reaches every child.
            kwargs["start_new_session"] = True

        job.proc = await asyncio.create_subprocess_exec(*argv, **kwargs)
        job.started_at = time.monotonic()
        try:
            job.pgid = os.getpgid(job.proc.pid) if os.name == "posix" else None
        except (ProcessLookupError, OSError):
            job.pgid = None

        job._reader_done = asyncio.Event()
        asyncio.create_task(self._reader(job))

    def _build_argv(self, job: Job) -> list[str]:
        if self._chipify_cli_override:
            argv: list[str] = [self._chipify_cli_override]
        else:
            # Use the same interpreter that's running uvicorn so we never
            # depend on PATH inside the container. ``chipify.cli`` exposes
            # the same ``main()`` that the ``chipify-cli`` console script
            # invokes.
            argv = [sys.executable, "-m", "chipify.cli"]
        argv += [
            "--config", job.yaml_basename,
            "--simulator", job.simulator,
            "--templates-dir", "./templates",
            "--progress-stream",
        ]
        return argv

    async def _reader(self, job: Job) -> None:
        """Drain the subprocess stdout and fan lines out to subscribers."""
        assert job.proc is not None and job.proc.stdout is not None
        # First: emit a READY line carrying the PGID so the client can
        # display it / log it. chipify-cli itself never emits READY (that
        # was the SSH wrapper's job); we synthesise it here so the existing
        # client regex stays useful.
        if job.pgid is not None:
            self._fanout(job, f"READY {job.pgid}")
        try:
            async for raw in job.proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                job.log_tail.append(line)
                self._fanout(job, line)
        except Exception:
            log.exception("Reader for job %s crashed", job.job_id)
        finally:
            rc = await job.proc.wait()
            job.return_code = rc
            job.finished_at = time.monotonic()
            log.info("Job %s exited rc=%d", job.job_id, rc)
            # Signal end-of-stream to every subscriber.
            for q in list(job._subscribers):
                await q.put(None)
            if job._reader_done is not None:
                job._reader_done.set()

    def _fanout(self, job: Job, line: str) -> None:
        for q in list(job._subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                # Subscriber is slow; drop the line rather than block the
                # reader. Bounded queues prevent unbounded memory growth.
                pass

    # ── SSE feed ──────────────────────────────────────────────────────────

    async def stream_events(self, job_id: str) -> AsyncIterator[str]:
        """Yield SSE-encoded frames for *job_id*.

        Each chipify-cli stdout line is forwarded verbatim as ``data: <line>``
        so the existing client regex (PHASE/PROGRESS/READY) can match without
        modification. Sends a ``: keepalive`` comment every ~0.5s when idle.
        """
        job = self._require(job_id)
        q: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=1024)
        job._subscribers.append(q)
        # Replay the existing log tail so a subscriber that joins late still
        # sees PHASE markers from earlier in the run.
        for line in list(job.log_tail):
            yield _sse_data(line)
        try:
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_SEC)
                except asyncio.TimeoutError:
                    yield SSE_KEEPALIVE
                    continue
                if line is None:
                    # End-of-stream marker. Tell the client the run is done.
                    rc = job.return_code if job.return_code is not None else -1
                    yield _sse_data(f"DONE {rc}")
                    return
                yield _sse_data(line)
        finally:
            try:
                job._subscribers.remove(q)
            except ValueError:
                pass

    # ── Abort + result + cleanup ──────────────────────────────────────────

    async def abort(self, job_id: str) -> None:
        job = self._require(job_id)
        if job.proc is None or job.return_code is not None:
            return
        job.aborted = True
        if os.name == "posix" and job.pgid is not None:
            try:
                os.killpg(job.pgid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
            await asyncio.sleep(_KILL_GRACE_SEC)
            try:
                os.killpg(job.pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
        else:
            # Windows / no pgid: terminate the leader only.
            try:
                job.proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(job.proc.wait(), timeout=_KILL_GRACE_SEC)
            except asyncio.TimeoutError:
                try:
                    job.proc.kill()
                except ProcessLookupError:
                    pass
        if job._reader_done is not None:
            try:
                await asyncio.wait_for(job._reader_done.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                log.warning("Reader for job %s did not finish after abort.", job_id)

    def result_csv(self, job_id: str) -> Path:
        job = self._require(job_id)
        return job.project_dir / "out" / "simulation_results.csv"

    def tran_files(self, job_id: str) -> list[str]:
        job = self._require(job_id)
        root = job.project_dir / "out" / "tran_data"
        if not root.is_dir():
            return []
        names: list[str] = []
        for sub in sorted(p for p in root.iterdir() if p.is_dir()):
            for f in sorted(sub.iterdir()):
                if f.is_file():
                    names.append(f"{sub.name}/{f.name}")
        return names

    def tran_file_path(self, job_id: str, name: str) -> Path:
        job = self._require(job_id)
        root = (job.project_dir / "out" / "tran_data").resolve()
        target = (root / name).resolve()
        # Path-traversal guard.
        if not str(target).startswith(str(root)):
            raise JobNotFound(name)
        if not target.is_file():
            raise JobNotFound(name)
        return target

    async def cleanup(self, job_id: str, *, force: bool = False) -> None:
        """Remove the job's run dir unless keep_on_failure says otherwise."""
        async with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return
        keep = job.keep_on_failure and (
            job.aborted or (job.return_code is not None and job.return_code != 0)
        )
        if keep and not force:
            log.warning(
                "Keeping run dir for inspection: %s", job.work_dir,
            )
            return
        try:
            shutil.rmtree(job.work_dir, ignore_errors=True)
            log.info("Cleaned up run dir %s", job.work_dir)
        except Exception:
            log.exception("Could not remove %s", job.work_dir)

    def has_job(self, job_id: str) -> bool:
        return job_id in self._jobs

    def get_job(self, job_id: str) -> Job:
        return self._require(job_id)

    def _require(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise JobNotFound(job_id) from None


def _sse_data(line: str) -> str:
    # A single chipify-cli stdout line maps to one SSE frame. The protocol
    # requires a trailing blank line as the frame terminator.
    return f"data: {line}\n\n"
