"""
app.py – FastAPI app for the chipify HTTPS remote-compute server.

Routes
------
GET    /preflight                  → environment probe JSON
POST   /jobs                       → multipart bundle upload, returns job_id
GET    /jobs/{id}/events           → SSE stream of PHASE/PROGRESS/log lines
GET    /jobs/{id}/result           → simulation_results.csv
GET    /jobs/{id}/tran             → JSON list of transient files
GET    /jobs/{id}/tran/{name}      → individual tran file
DELETE /jobs/{id}                  → abort (if live) + cleanup

Every route requires ``Authorization: Bearer <token>``; the token is
resolved at startup by ``chipify.cli serve``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("chipify._server.app")


def build_app(*, token: str, work_dir: Path, chipify_cli: str | None = None):
    """Return a configured FastAPI instance.

    *chipify_cli* overrides the executable used to run jobs. Production
    callers leave it None (we fall back to ``python -m chipify.cli``).
    Tests inject a stub script.
    """
    from fastapi import (
        Depends, FastAPI, File, Form, HTTPException, Path as PathParam,
        UploadFile, status,
    )
    from fastapi.responses import FileResponse, StreamingResponse, JSONResponse

    from chipify import preflight as _preflight
    from chipify._server.auth import make_require_token
    from chipify._server.jobs import (
        JobAlreadyTerminated, JobManager, JobNotFound,
    )

    app = FastAPI(title="chipify-server", version="1")
    jobs = JobManager(Path(work_dir), chipify_cli=chipify_cli)
    require_token = make_require_token(token)
    app.state.jobs = jobs           # for tests / introspection

    @app.get("/preflight")
    async def preflight(_: None = Depends(require_token)) -> dict[str, Any]:
        return _preflight.collect()

    @app.post("/jobs")
    async def post_job(
        bundle: UploadFile = File(...),
        yaml_basename: str = Form(...),
        simulator: str = Form("ngspice"),
        keep_on_failure: bool = Form(False),
        _: None = Depends(require_token),
    ) -> dict[str, str]:
        payload = await bundle.read()
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="empty bundle",
            )
        try:
            job_id = await jobs.create_job(
                payload, yaml_basename, simulator,
                keep_on_failure=keep_on_failure,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        await jobs.start(job_id)
        return {"job_id": job_id}

    @app.get("/jobs/{job_id}/events")
    async def events(
        job_id: str = PathParam(..., min_length=4),
        _: None = Depends(require_token),
    ) -> StreamingResponse:
        try:
            stream = jobs.stream_events(job_id)
        except JobNotFound:
            raise HTTPException(status_code=404, detail="job not found")
        # ``X-Accel-Buffering: no`` keeps nginx from buffering SSE if anyone
        # ever puts a reverse proxy in front. Harmless otherwise.
        headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(
            stream, media_type="text/event-stream", headers=headers,
        )

    @app.get("/jobs/{job_id}/result")
    async def result(
        job_id: str = PathParam(..., min_length=4),
        _: None = Depends(require_token),
    ) -> FileResponse:
        try:
            csv = jobs.result_csv(job_id)
        except JobNotFound:
            raise HTTPException(status_code=404, detail="job not found")
        if not csv.is_file():
            raise HTTPException(
                status_code=409,
                detail="result not ready",
            )
        return FileResponse(
            path=str(csv),
            filename="simulation_results.csv",
            media_type="text/csv",
        )

    @app.get("/jobs/{job_id}/tran")
    async def tran_list(
        job_id: str = PathParam(..., min_length=4),
        _: None = Depends(require_token),
    ) -> list[str]:
        try:
            return jobs.tran_files(job_id)
        except JobNotFound:
            raise HTTPException(status_code=404, detail="job not found")

    @app.get("/jobs/{job_id}/tran/{name:path}")
    async def tran_file(
        job_id: str,
        name: str,
        _: None = Depends(require_token),
    ) -> FileResponse:
        try:
            path = jobs.tran_file_path(job_id, name)
        except JobNotFound:
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(path=str(path), filename=path.name)

    @app.delete("/jobs/{job_id}")
    async def kill_job(
        job_id: str = PathParam(..., min_length=4),
        _: None = Depends(require_token),
    ) -> dict[str, bool]:
        try:
            await jobs.abort(job_id)
            await jobs.cleanup(job_id)
        except JobNotFound:
            # Idempotent: deleting an unknown job is a no-op.
            return {"ok": True}
        return {"ok": True}

    return app


def run(
    *,
    host: str,
    port: int,
    cert: Path,
    key: Path,
    token: str,
    work_dir: Path,
    chipify_cli: str | None = None,
) -> int:
    """Boot uvicorn with the configured app. Returns the uvicorn exit code."""
    import uvicorn

    app = build_app(token=token, work_dir=work_dir, chipify_cli=chipify_cli)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        ssl_certfile=str(cert),
        ssl_keyfile=str(key),
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()
    return 0
