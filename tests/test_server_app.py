"""Unit tests for chipify._server.app using FastAPI's TestClient."""
from __future__ import annotations

import io
import os
import stat
import sys
import textwrap
import time
import zipfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from chipify._server import build_app


TOKEN = "test-token-deadbeef"


def _make_stub_cli(tmp_path: Path) -> Path:
    """Write a tiny script that mimics the chipify-cli progress protocol."""
    if os.name == "nt":
        # On Windows we ship a .cmd file; subprocess can exec it directly.
        stub = tmp_path / "fake-chipify-cli.cmd"
        stub.write_text(textwrap.dedent(r"""
            @echo off
            echo PHASE: load_config
            echo PROGRESS: 0 2
            echo PROGRESS: 1 2
            echo PROGRESS: 2 2
            echo PHASE: complete
            mkdir out 2>nul
            (
              echo a,b
              echo 1,2
            ) > out\simulation_results.csv
            exit /B 0
        """))
        return stub
    stub = tmp_path / "fake-chipify-cli"
    stub.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        echo "PHASE: load_config"
        echo "PROGRESS: 0 2"
        echo "PROGRESS: 1 2"
        echo "PROGRESS: 2 2"
        echo "PHASE: complete"
        mkdir -p out
        printf "a,b\\n1,2\\n" > out/simulation_results.csv
        exit 0
    """))
    stub.chmod(0o755)
    return stub


def _make_bundle() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("datasheets/dummy.yaml", "name: dummy\n")
        zf.writestr("templates/tb__one.spice", "* dummy spice\n.end\n")
    return buf.getvalue()


@pytest.fixture
def client(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    stub = _make_stub_cli(tmp_path)
    app = build_app(token=TOKEN, work_dir=work, chipify_cli=str(stub))
    with TestClient(app) as c:
        yield c, work


def test_preflight_requires_auth(client):
    c, _ = client
    r = c.get("/preflight")
    assert r.status_code == 401


def test_preflight_with_auth(client):
    c, _ = client
    r = c.get("/preflight", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    body = r.json()
    assert "ok" in body
    assert "ngspice" in body


def test_preflight_wrong_token(client):
    c, _ = client
    r = c.get("/preflight", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_job_roundtrip(client):
    c, work = client
    hdr = {"Authorization": f"Bearer {TOKEN}"}

    r = c.post(
        "/jobs",
        headers=hdr,
        data={"yaml_basename": "dummy.yaml", "simulator": "ngspice"},
        files={"bundle": ("bundle.zip", _make_bundle(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    assert job_id

    # Drain SSE events. TestClient's StreamingResponse iter_lines blocks
    # until the response is done; the stub script exits quickly.
    seen = []
    with c.stream("GET", f"/jobs/{job_id}/events", headers=hdr) as resp:
        assert resp.status_code == 200
        for raw in resp.iter_lines():
            line = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
            if line.startswith("data: "):
                payload = line[len("data: "):]
                seen.append(payload)
                if payload.startswith("DONE "):
                    break

    assert any(s.startswith("PHASE: ") for s in seen), seen
    assert any(s.startswith("PROGRESS: ") for s in seen), seen
    assert any(s.startswith("DONE ") for s in seen), seen

    # Wait briefly for the subprocess to write out the CSV (some platforms
    # finalise file writes after the parent exit signal arrives).
    for _ in range(20):
        r = c.get(f"/jobs/{job_id}/result", headers=hdr)
        if r.status_code == 200:
            break
        time.sleep(0.05)
    assert r.status_code == 200, r.text
    assert b"a,b" in r.content

    # Cleanup
    r = c.delete(f"/jobs/{job_id}", headers=hdr)
    assert r.status_code == 200

    # Subsequent result fetch returns 404 (idempotent delete).
    r = c.get(f"/jobs/{job_id}/result", headers=hdr)
    assert r.status_code == 404


def test_delete_unknown_job_is_ok(client):
    c, _ = client
    r = c.delete("/jobs/doesnotexist", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
