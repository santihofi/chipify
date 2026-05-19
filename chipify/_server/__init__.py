"""
chipify._server – HTTPS remote-compute server.

Run via ``chipify-cli serve`` (see ``chipify.cli._serve_main``). The public
surface is intentionally tiny so callers can swap the transport in tests
without touching FastAPI internals:

    from chipify._server import build_app, run

``build_app`` constructs the FastAPI instance (used by tests). ``run`` is
the production entry point that also handles uvicorn + TLS.
"""
from __future__ import annotations

from .app import build_app, run

__all__ = ["build_app", "run"]
