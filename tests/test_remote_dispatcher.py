"""Unit tests for the remote_dispatcher client side.

Uses ``httpx.MockTransport`` so we never need a real server. The TLS pin
check (`_verify_pin_or_raise`) is monkeypatched out — the real socket
work happens only against a running server, which the e2e test exercises.
"""
from __future__ import annotations

import json
import os

import pytest

httpx = pytest.importorskip("httpx")

from chipify import remote_dispatcher as rd


# ── Pin-store helpers ───────────────────────────────────────────────────

def test_trust_and_recall(tmp_path, monkeypatch):
    monkeypatch.setattr(rd, "LOCAL_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(rd, "LOCAL_PIN_STORE", str(tmp_path / "pins.json"))
    assert rd._pin_for("https://x:8443") is None
    rd.trust_server_fingerprint("https://x:8443", "SHA256:abc", "CN=x")
    assert rd._pin_for("https://x:8443") == "SHA256:abc"
    data = json.loads((tmp_path / "pins.json").read_text())
    assert data["https://x:8443"]["subject"] == "CN=x"


def test_remote_profile_roundtrip():
    p = rd.RemoteProfile.from_dict({
        "name": "lab",
        "base_url": "https://lab:8443",
        "token": "abc",
        "work_dir": "/tmp/cw",
        "verify_tls": False,
        "cert_fingerprint_sha256": "SHA256:zz",
        "keep_on_failure": True,
    })
    assert p.name == "lab"
    assert p.base_url == "https://lab:8443"
    assert p.verify_tls is False
    assert p.keep_on_failure is True
    assert p.cert_fingerprint_sha256 == "SHA256:zz"
    assert rd.RemoteProfile.from_dict(p.to_dict()) == p


def test_resolve_token_from_file(tmp_path):
    f = tmp_path / "tok"
    f.write_text("file-token-value\n")
    p = rd.RemoteProfile(base_url="https://x", token="ignored",
                         token_file=str(f))
    assert p.resolve_token() == "file-token-value"


# ── Dispatcher context manager + TOFU + httpx mock ──────────────────────

class _FakeSocketCert:
    """Stand-in for the live cert returned by `_fetch_server_cert_der`."""
    def __init__(self, der: bytes, subject: str):
        self.der = der
        self.subject = subject


@pytest.fixture
def mock_pin(monkeypatch, tmp_path):
    """Make pin-store writes hit a temp dir and stub out socket TLS."""
    monkeypatch.setattr(rd, "LOCAL_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(rd, "LOCAL_PIN_STORE", str(tmp_path / "pins.json"))

    # Stub the live-cert fetch to return deterministic bytes.
    fake_der = b"FAKE-DER-CERT-BYTES"
    expected_fp = rd._fingerprint_der(fake_der)
    monkeypatch.setattr(rd, "_fetch_server_cert_der", lambda h, p, timeout=10.0: fake_der)
    monkeypatch.setattr(rd, "_parse_subject", lambda der: "CN=test")
    return expected_fp


def test_tofu_first_contact_raises(mock_pin):
    profile = rd.RemoteProfile(
        base_url="https://x:8443", token="t", verify_tls=True,
    )
    with pytest.raises(rd.TlsCertificateVerificationError) as exc:
        rd.RemoteDispatcher(profile=profile).__enter__()
    assert exc.value.fingerprint_sha256 == mock_pin


def test_pin_match_passes(mock_pin):
    # Pre-pin the fingerprint so __enter__ succeeds. We don't run a sweep —
    # the test passes if no exception is raised before httpx.AsyncClient is
    # constructed.
    rd.trust_server_fingerprint("https://x:8443", mock_pin, "CN=test")
    profile = rd.RemoteProfile(
        base_url="https://x:8443", token="t", verify_tls=True,
    )
    disp = rd.RemoteDispatcher(profile=profile)
    try:
        disp.__enter__()
        assert disp._client is not None
        assert disp.profile.cert_fingerprint_sha256 == mock_pin
    finally:
        disp.__exit__(None, None, None)


def test_pin_mismatch_raises(mock_pin):
    rd.trust_server_fingerprint("https://x:8443", "SHA256:OTHER", "CN=other")
    profile = rd.RemoteProfile(
        base_url="https://x:8443", token="t", verify_tls=True,
    )
    with pytest.raises(rd.TlsCertificateVerificationError):
        rd.RemoteDispatcher(profile=profile).__enter__()


def test_verify_tls_false_skips_pin(mock_pin):
    profile = rd.RemoteProfile(
        base_url="https://x:8443", token="t", verify_tls=False,
    )
    disp = rd.RemoteDispatcher(profile=profile)
    try:
        disp.__enter__()
        assert disp._client is not None
    finally:
        disp.__exit__(None, None, None)


def test_iter_sse_parses_lines(mock_pin):
    """Feed the SSE consumer a canned stream; assert it yields the data
    payloads stripped of the SSE framing."""
    import asyncio

    rd.trust_server_fingerprint("https://x:8443", mock_pin, "CN=test")
    profile = rd.RemoteProfile(base_url="https://x:8443", token="t")

    body = (
        b": keepalive\n\n"
        b"data: PHASE: simulating\n\n"
        b"data: PROGRESS: 3 10\n\n"
        b"data: DONE 0\n\n"
    )

    def handler(req):
        return httpx.Response(200, content=body, headers={
            "content-type": "text/event-stream",
        })

    disp = rd.RemoteDispatcher(profile=profile)
    try:
        disp.__enter__()
        # Swap in a MockTransport for the streamed GET.
        import httpx as _httpx
        disp._client = _httpx.AsyncClient(
            base_url="https://x:8443",
            transport=_httpx.MockTransport(handler),
            timeout=_httpx.Timeout(5.0, read=None),
        )

        async def drain():
            seen = []
            async for line in disp._iter_sse("/jobs/abc/events"):
                seen.append(line)
            return seen

        result = disp._loop.run_until_complete(drain())
    finally:
        disp.__exit__(None, None, None)

    assert result == ["PHASE: simulating", "PROGRESS: 3 10", "DONE 0"]
