"""
remote_dispatcher.py – Offload simulation sweeps to a chipify HTTPS server.

Local responsibilities:
    1. Run xschem and prepare Jinja2 templates (``simulator.generate_templates``).
    2. Bundle templates + datasheet YAML + SPICE library files (.lib/.mod/.inc).
    3. POST the bundle to ``<base_url>/jobs``; stream ``PHASE``/``PROGRESS``
       lines back via Server-Sent Events; capture remote log tail; support abort.
    4. GET the results CSV (and transient data) back into ``OUT_DIR``.

The HTTPS server lives in ``chipify._server`` and is started with
``chipify-cli serve`` (typically inside an iic-osic-tools container).

Authentication: bearer token in the ``Authorization`` header. Token is
configured per profile (or read from a token file at run time).

TLS: the client pins the server certificate's SHA-256 fingerprint via TOFU
on first contact (analogous to OpenSSH's known_hosts). The pin is stored in
``~/.chipify/server_fingerprints.json`` keyed by base URL; the GUI catches
``TlsCertificateVerificationError`` and prompts the user to trust the new
fingerprint.
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import hmac
import io
import json
import logging
import os
import socket
import ssl
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional, TYPE_CHECKING
from urllib.parse import urlparse

import pandas as pd

from chipify import settings
from chipify.preflight import format_summary
from chipify._server.protocol import (
    LOG_TAIL_SIZE, PHASE_RE, PROGRESS_RE, READY_RE,
)

if TYPE_CHECKING:
    from chipify.util import Stimuli

log = logging.getLogger("chipify.remote_dispatcher")

# ── Local pin store ──────────────────────────────────────────────────────
LOCAL_CONFIG_DIR = os.path.expanduser(os.path.join("~", ".chipify"))
LOCAL_PIN_STORE  = os.path.join(LOCAL_CONFIG_DIR, "server_fingerprints.json")


# ── Errors ────────────────────────────────────────────────────────────────

class RemoteDispatcherError(RuntimeError):
    """Raised when the remote sweep cannot be completed."""


class TlsCertificateVerificationError(RemoteDispatcherError):
    """Raised on TLS fingerprint mismatch or first-time server (TOFU).

    Carries enough metadata for the GUI to show a "trust this fingerprint?"
    dialog before retrying.
    """

    def __init__(
        self,
        base_url: str,
        fingerprint_sha256: str,
        subject: str,
        reason: str,
    ) -> None:
        super().__init__(reason)
        self.base_url = base_url
        self.fingerprint_sha256 = fingerprint_sha256
        self.subject = subject
        self.reason = reason

    def __str__(self) -> str:
        return (
            f"{self.reason} ({self.base_url} "
            f"{self.fingerprint_sha256} subject={self.subject!r})"
        )


# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class RemoteProfile:
    """Connection settings for one chipify HTTPS server.

    Mirrors the persisted dict in ``settings.json`` under
    ``remote_profiles[]`` so the GUI can pass it to the dispatcher as-is.
    """
    name: str = "default"
    base_url: str = ""               # e.g. https://10.0.0.5:8443
    token: str = ""                  # bearer token (literal value)
    token_file: str = ""             # optional: path read at run time, wins over `token`
    work_dir: str = "/tmp/chipify_remote"
    verify_tls: bool = True          # False = skip pin (dev only)
    cert_fingerprint_sha256: str = ""  # filled by TOFU
    keep_on_failure: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RemoteProfile":
        kwargs: dict[str, Any] = {}
        for f in (
            "name", "base_url", "token", "token_file",
            "work_dir", "cert_fingerprint_sha256",
        ):
            if f in d and d[f] is not None:
                kwargs[f] = str(d[f]).strip()
        if "verify_tls" in d:
            kwargs["verify_tls"] = bool(d["verify_tls"])
        if "keep_on_failure" in d:
            kwargs["keep_on_failure"] = bool(d["keep_on_failure"])
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "token": self.token,
            "token_file": self.token_file,
            "work_dir": self.work_dir,
            "verify_tls": self.verify_tls,
            "cert_fingerprint_sha256": self.cert_fingerprint_sha256,
            "keep_on_failure": self.keep_on_failure,
        }

    def resolve_token(self) -> str:
        """Return the literal token, reading from token_file if set."""
        if self.token_file:
            path = os.path.expanduser(self.token_file)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tok = fh.read().strip()
                if tok:
                    return tok
            except OSError as exc:
                raise RemoteDispatcherError(
                    f"Could not read token_file {path}: {exc}"
                ) from exc
        return self.token


@dataclass
class RemoteProgress:
    """Snapshot of an in-flight remote run."""
    phase: str = "starting"
    done: int = 0
    total: int = 0
    rate_per_sec: float = 0.0
    eta_sec: float | None = None
    log_tail: list[str] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────

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


def _ensure_local_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        log.exception("Could not create local dir %s", path)


# ── TLS pinning ──────────────────────────────────────────────────────────

def _fingerprint_der(der: bytes) -> str:
    """SHA256 fingerprint matching OpenSSH / openssl format."""
    digest = hashlib.sha256(der).digest()
    return "SHA256:" + base64.b64encode(digest).rstrip(b"=").decode("ascii")


def _fetch_server_cert_der(host: str, port: int, timeout: float = 10.0) -> bytes:
    """Open a TLS handshake just to grab the peer cert, then close.

    Verify mode is ``CERT_NONE`` because we're verifying by fingerprint pin,
    not by CA chain — the server is self-signed by design.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as ssock:
            der = ssock.getpeercert(binary_form=True)
            if not der:
                raise RemoteDispatcherError(
                    f"Server at {host}:{port} did not present a certificate."
                )
            return der


def _parse_subject(der: bytes) -> str:
    """Return a short, human-readable subject string (best effort)."""
    try:
        from cryptography import x509
        cert = x509.load_der_x509_certificate(der)
        return cert.subject.rfc4514_string()
    except Exception:
        # cryptography is server-only; fall back to a minimal indicator.
        return f"<DER {len(der)} bytes>"


def _load_pins() -> dict[str, dict[str, Any]]:
    if not os.path.exists(LOCAL_PIN_STORE):
        return {}
    try:
        with open(LOCAL_PIN_STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        log.warning("Could not read %s — pin store treated as empty.", LOCAL_PIN_STORE)
        return {}


def _save_pins(pins: dict[str, dict[str, Any]]) -> None:
    _ensure_local_dir(LOCAL_CONFIG_DIR)
    try:
        with open(LOCAL_PIN_STORE, "w", encoding="utf-8") as fh:
            json.dump(pins, fh, indent=2, sort_keys=True)
    except OSError:
        log.exception("Could not write %s", LOCAL_PIN_STORE)


def _pin_for(base_url: str) -> str | None:
    pins = _load_pins()
    entry = pins.get(base_url) or {}
    fp = entry.get("sha256") if isinstance(entry, dict) else None
    return fp if isinstance(fp, str) and fp else None


def _verify_pin_or_raise(profile: RemoteProfile) -> tuple[str, str]:
    """Fetch the live server cert and check it against the pin.

    Returns ``(fingerprint, subject)`` for the live cert on success.
    Raises ``TlsCertificateVerificationError`` if no pin is configured or
    the fingerprint does not match.
    """
    parsed = urlparse(profile.base_url)
    if parsed.scheme != "https":
        raise RemoteDispatcherError(
            f"base_url must use https://, got {profile.base_url!r}."
        )
    host = parsed.hostname or ""
    port = parsed.port or 443
    if not host:
        raise RemoteDispatcherError(
            f"base_url has no host: {profile.base_url!r}."
        )

    der = _fetch_server_cert_der(host, port)
    live_fp = _fingerprint_der(der)
    subject = _parse_subject(der)

    if not profile.verify_tls:
        log.warning(
            "verify_tls=False — accepting %s without pin check.",
            profile.base_url,
        )
        return live_fp, subject

    expected = (profile.cert_fingerprint_sha256 or "").strip() or _pin_for(profile.base_url)
    if not expected:
        raise TlsCertificateVerificationError(
            base_url=profile.base_url,
            fingerprint_sha256=live_fp,
            subject=subject,
            reason="Unknown server certificate (first connection).",
        )
    if not hmac.compare_digest(expected, live_fp):
        raise TlsCertificateVerificationError(
            base_url=profile.base_url,
            fingerprint_sha256=live_fp,
            subject=subject,
            reason=f"Server certificate fingerprint mismatch (expected {expected}).",
        )
    return live_fp, subject


def trust_server_fingerprint(
    base_url: str,
    fingerprint_sha256: str,
    subject: str = "",
) -> bool:
    """Add (or overwrite) a server-cert pin in the local store."""
    pins = _load_pins()
    pins[base_url] = {
        "sha256": fingerprint_sha256,
        "subject": subject,
        "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _save_pins(pins)
    return True


# ── Bundle build ─────────────────────────────────────────────────────────

def _build_bundle(
    stim: "Stimuli",
    yaml_path: str,
    simulator_name: str,
) -> bytes:
    """Zip templates + datasheet + libs into an in-memory bundle."""
    ext = ".sim" if simulator_name == "vacask" else ".spice"

    lib_files: list[tuple[str, str]] = []
    if os.path.isdir(settings.WORK_DIR):
        for fname in sorted(os.listdir(settings.WORK_DIR)):
            if not fname.lower().endswith((".lib", ".mod", ".inc")):
                continue
            src = os.path.join(settings.WORK_DIR, fname)
            if os.path.isfile(src):
                lib_files.append((fname, src))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        with open(yaml_path, "rb") as fh:
            zf.writestr(
                f"datasheets/{os.path.basename(yaml_path)}", fh.read()
            )
        for fname, src in lib_files:
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

    return buf.getvalue()


# ── Dispatcher ───────────────────────────────────────────────────────────

class RemoteDispatcher:
    """Owns one HTTPS client + one remote job over its lifecycle.

    Use as a context manager:

        with RemoteDispatcher(profile=profile) as disp:
            df = disp.run(stim, yaml_path)
    """

    def __init__(
        self,
        profile: RemoteProfile | None = None,
        *,
        # Back-compat kwargs (legacy SSH call signature). The fields that
        # have no HTTPS analogue are silently ignored.
        host: str = "",
        username: str = "",
        key_path: str = "",
        remote_work_dir: str = "/tmp/chipify_remote",
        port: int = 22,
        remote_chipify_cmd: str = "",
        connect_timeout: float = 15.0,
        trust_new_cert: bool = False,
    ) -> None:
        if profile is None:
            # No HTTPS analogue for SSH legacy args — fall back to a default
            # profile and let the caller fail at __enter__ with a clear msg.
            profile = RemoteProfile(work_dir=remote_work_dir)

        if not profile.base_url:
            raise RemoteDispatcherError(
                "Remote profile incomplete: base_url is required "
                "(e.g. https://10.0.0.5:8443)."
            )

        self.profile = profile
        self.connect_timeout = float(connect_timeout)
        self.trust_new_cert = trust_new_cert

        self.run_id = uuid.uuid4().hex[:12]
        self.job_id: Optional[str] = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._client = None  # httpx.AsyncClient | None

        self._progress = RemoteProgress()
        self._run_started_at = 0.0
        self._aborted = False
        self._keep_remote_dir_override: bool | None = None

    # ── Context manager ──────────────────────────────────────────────────

    def __enter__(self) -> "RemoteDispatcher":
        try:
            import httpx  # noqa: F401
        except ImportError as exc:
            raise RemoteDispatcherError(
                "httpx is required for remote compute. "
                "Install with: pip install 'chipify[remote]'"
            ) from exc

        # Resolve the token (may read from token_file).
        token = self.profile.resolve_token()
        if not token:
            raise RemoteDispatcherError(
                "Remote profile has no bearer token. Paste the token printed "
                "by `chipify-cli serve` into Settings → Remote."
            )

        # TLS pin check (TOFU). On first contact this raises and the GUI
        # prompts the user; after Trust, the profile carries the fingerprint
        # and verification passes silently.
        try:
            live_fp, subject = _verify_pin_or_raise(self.profile)
        except TlsCertificateVerificationError:
            if self.trust_new_cert:
                der = _fetch_server_cert_der(
                    urlparse(self.profile.base_url).hostname or "",
                    urlparse(self.profile.base_url).port or 443,
                    timeout=self.connect_timeout,
                )
                fp = _fingerprint_der(der)
                trust_server_fingerprint(self.profile.base_url, fp, _parse_subject(der))
                self.profile.cert_fingerprint_sha256 = fp
            else:
                raise
        else:
            self.profile.cert_fingerprint_sha256 = live_fp

        import httpx  # type: ignore[import]
        self._loop = asyncio.new_event_loop()
        # ``verify=False`` is safe because we've already verified the cert by
        # fingerprint pin above. CA-chain validation is meaningless for the
        # self-signed cert chipify-cli serve generates.
        self._client = httpx.AsyncClient(
            base_url=self.profile.base_url,
            headers={"Authorization": f"Bearer {token}"},
            verify=False,
            timeout=httpx.Timeout(self.connect_timeout, read=None),
            http2=False,
        )
        log.info(
            "HTTPS client open: %s (fp=%s)",
            self.profile.base_url, self.profile.cert_fingerprint_sha256,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client is not None and self._loop is not None:
            try:
                self._loop.run_until_complete(self._client.aclose())
            except Exception:
                log.debug("client.aclose() failed", exc_info=True)
        if self._loop is not None:
            try:
                self._loop.close()
            except Exception:
                log.debug("loop.close() failed", exc_info=True)
        self._client = None
        self._loop = None

    # ── Public: preflight ────────────────────────────────────────────────

    def preflight(self) -> dict[str, Any]:
        if self._client is None or self._loop is None:
            raise RemoteDispatcherError("preflight() requires open connection.")
        return self._loop.run_until_complete(self._preflight_async())

    async def _preflight_async(self) -> dict[str, Any]:
        assert self._client is not None
        try:
            resp = await self._client.get("/preflight")
            resp.raise_for_status()
        except Exception as exc:
            return {
                "ok": False,
                "errors": [f"GET /preflight failed: {exc}"],
            }
        info = resp.json()
        info["base_url"] = self.profile.base_url
        info["cert_fingerprint_sha256"] = self.profile.cert_fingerprint_sha256
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
            "Remote run %s on %s", self.run_id, self.profile.base_url,
        )
        if self._client is None or self._loop is None:
            raise RemoteDispatcherError("run() requires open connection.")

        self._run_started_at = time.monotonic()
        self._progress = RemoteProgress(phase="starting")
        _call_progress(progress_callback, 0, 0, self._progress)

        engine = _sim.get_simulator_engine(simulator_name)
        _sim.generate_templates(stim, engine)

        return self._loop.run_until_complete(
            self._run_async(stim, yaml_path, engine.name, progress_callback)
        )

    async def _run_async(
        self,
        stim: "Stimuli",
        yaml_path: str,
        simulator_name: str,
        progress_callback: Optional[Callable[..., None]],
    ) -> Optional[pd.DataFrame]:
        assert self._client is not None
        # ── Bundle build ──────────────────────────────────────────────────
        self._progress.phase = "bundle_build"
        _call_progress(progress_callback, 0, 0, self._progress)
        bundle = _build_bundle(stim, yaml_path, simulator_name)
        log.info("Bundle built: %d bytes", len(bundle))

        # ── Upload + start job ───────────────────────────────────────────
        self._progress.phase = "uploading"
        _call_progress(progress_callback, 0, 0, self._progress)
        try:
            resp = await self._client.post(
                "/jobs",
                files={
                    "bundle": ("bundle.zip", bundle, "application/zip"),
                },
                data={
                    "yaml_basename": os.path.basename(yaml_path),
                    "simulator": simulator_name,
                    "keep_on_failure": "true" if self.profile.keep_on_failure else "false",
                },
            )
            resp.raise_for_status()
        except Exception as exc:
            raise RemoteDispatcherError(f"POST /jobs failed: {exc}") from exc
        self.job_id = resp.json().get("job_id")
        if not self.job_id:
            raise RemoteDispatcherError(f"Server returned no job_id: {resp.text}")
        log.info("Server accepted job %s", self.job_id)

        # ── Stream events + parse PHASE/PROGRESS/READY ──────────────────
        self._progress.phase = "simulating"
        self._progress.done = 0
        self._progress.total = 0
        self._progress.log_tail = []
        _call_progress(progress_callback, 0, 0, self._progress)

        rc: Optional[int] = None
        try:
            async for line in self._iter_sse(f"/jobs/{self.job_id}/events"):
                if self._aborted:
                    break
                if line.startswith("DONE "):
                    try:
                        rc = int(line[len("DONE "):].strip())
                    except ValueError:
                        rc = -1
                    break
                self._progress.log_tail.append(line)
                if len(self._progress.log_tail) > LOG_TAIL_SIZE:
                    self._progress.log_tail = self._progress.log_tail[-LOG_TAIL_SIZE:]

                m_ready = READY_RE.match(line)
                if m_ready:
                    log.info("Server reported pgid=%s", m_ready.group(1))
                    continue
                m_phase = PHASE_RE.match(line)
                if m_phase:
                    self._progress.phase = m_phase.group(1)
                    _call_progress(
                        progress_callback,
                        self._progress.done,
                        max(1, self._progress.total),
                        self._progress,
                    )
                    continue
                m_prog = PROGRESS_RE.match(line)
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
                    continue
                # Otherwise just a log line — leave it in the tail.
                log.debug("[remote] %s", line)
        except InterruptedError:
            log.info("Local abort requested – DELETE /jobs/%s", self.job_id)
            self._aborted = True
            try:
                await self._client.delete(f"/jobs/{self.job_id}")
            except Exception:
                log.exception("DELETE /jobs/%s failed during abort", self.job_id)
            raise

        if rc is None or rc != 0:
            self._keep_remote_dir_override = True
            tail = "\n".join(self._progress.log_tail[-40:]) or "<no output>"
            try:
                await self._client.delete(f"/jobs/{self.job_id}")
            except Exception:
                pass
            raise RemoteDispatcherError(
                f"Remote chipify-cli exited with rc={rc}.\n"
                f"--- remote log tail ---\n{tail}\n--- end ---"
            )

        # ── Download results ─────────────────────────────────────────────
        os.makedirs(settings.OUT_DIR, exist_ok=True)
        local_csv = os.path.join(settings.OUT_DIR, "simulation_results.csv")
        self._progress.phase = "downloading"
        _call_progress(
            progress_callback,
            self._progress.done,
            max(1, self._progress.total),
            self._progress,
        )
        try:
            resp = await self._client.get(f"/jobs/{self.job_id}/result")
            resp.raise_for_status()
            with open(local_csv, "wb") as fh:
                fh.write(resp.content)
            log.info("Downloaded results → %s", local_csv)
        except Exception as exc:
            self._keep_remote_dir_override = True
            tail = "\n".join(self._progress.log_tail[-40:]) or "<no output>"
            raise RemoteDispatcherError(
                f"Could not download simulation_results.csv: {exc}\n"
                f"--- remote log tail ---\n{tail}\n--- end ---"
            ) from exc

        await self._download_tran_files()

        self._progress.phase = "complete"
        _call_progress(
            progress_callback,
            self._progress.done,
            max(1, self._progress.total),
            self._progress,
        )

        # Cleanup (server removes the run dir unless keep_on_failure
        # applies, which only kicks in for failures we've already returned
        # for above).
        try:
            await self._client.delete(f"/jobs/{self.job_id}")
        except Exception:
            log.debug("Final DELETE /jobs/%s failed", self.job_id, exc_info=True)

        try:
            return pd.read_csv(local_csv)
        except Exception as exc:
            raise RemoteDispatcherError(
                f"Could not parse downloaded CSV: {exc}"
            ) from exc

    async def _download_tran_files(self) -> None:
        assert self._client is not None
        try:
            resp = await self._client.get(f"/jobs/{self.job_id}/tran")
            resp.raise_for_status()
            entries = resp.json()
        except Exception:
            return
        if not isinstance(entries, list) or not entries:
            return
        for name in entries:
            try:
                resp = await self._client.get(f"/jobs/{self.job_id}/tran/{name}")
                resp.raise_for_status()
            except Exception as exc:
                log.warning("Could not download tran %s: %s", name, exc)
                continue
            local_path = os.path.join(settings.OUT_DIR, "tran_data", name)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as fh:
                fh.write(resp.content)

    # ── SSE consumer ─────────────────────────────────────────────────────

    async def _iter_sse(self, path: str) -> AsyncIterator[str]:
        """Yield each ``data:`` payload from a Server-Sent Events stream."""
        assert self._client is not None
        async with self._client.stream("GET", path) as r:
            r.raise_for_status()
            buf = ""
            async for chunk in r.aiter_text():
                buf += chunk
                while "\n" in buf:
                    raw, buf = buf.split("\n", 1)
                    line = raw.rstrip("\r")
                    if not line:
                        continue
                    if line.startswith(":"):
                        # Comment / keepalive
                        continue
                    if line.startswith("data: "):
                        yield line[len("data: "):]
                    # event:/id:/retry: are ignored.

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


# ── Top-level helpers used by the GUI ────────────────────────────────────

def test_connection(
    # Legacy positional kwargs are accepted but ignored — the GUI now uses
    # the keyword-only ``profile=`` form. They stay here so older callers
    # don't error out at import time.
    host: str = "",
    username: str = "",
    key_path: str = "",
    port: int = 22,
    remote_chipify_cmd: str = "",
    *,
    profile: RemoteProfile | None = None,
    trust_new_cert: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """Probe the remote and return (ok, summary, info_dict).

    The third return value is the raw preflight JSON; the GUI uses it to
    render a structured panel. ``TlsCertificateVerificationError`` is
    captured into ``info['needs_trust']`` so the caller can show a TOFU
    dialog instead of treating it as a hard failure.
    """
    try:
        import httpx  # noqa: F401
    except ImportError:
        return False, "httpx not installed (pip install chipify[remote])", {}

    if profile is None:
        return False, "test_connection requires a RemoteProfile.", {}

    try:
        dispatcher = RemoteDispatcher(
            profile=profile,
            trust_new_cert=trust_new_cert,
        )
    except RemoteDispatcherError as exc:
        return False, str(exc), {}

    try:
        with dispatcher as disp:
            info = disp.preflight()
    except TlsCertificateVerificationError as exc:
        return False, (
            f"TLS certificate trust required for {exc.base_url}.\n"
            f"  fingerprint: {exc.fingerprint_sha256}\n"
            f"  subject:     {exc.subject}\n"
            f"Click 'Trust this fingerprint' to record it."
        ), {
            "needs_trust": True,
            "fingerprint_sha256": exc.fingerprint_sha256,
            "subject": exc.subject,
            "base_url": exc.base_url,
        }
    except RemoteDispatcherError as exc:
        return False, str(exc), {}
    except Exception as exc:
        return False, f"Connection failed: {exc}", {}

    if not info.get("ok"):
        msg = "Connected, but preflight reported issues:\n" + format_summary(info)
        return False, msg, info
    return True, "OK — " + format_summary(info), info
