"""
auth.py – Bearer-token authentication for the chipify HTTPS server.

The server requires ``Authorization: Bearer <token>`` on every request. The
token is loaded (or created) lazily from one of:

    1. an explicit ``--token-file`` path
    2. the ``CHIPIFY_TOKEN`` env var
    3. ``~/.chipify/server-token`` (auto-generated on first start)

Tokens are 32 url-safe random bytes (~256 bits). Comparison uses
``hmac.compare_digest`` to avoid timing leaks.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Callable

log = logging.getLogger("chipify._server.auth")


def _default_token_path() -> Path:
    return Path.home() / ".chipify" / "server-token"


def load_or_create_token(path: Path | None = None) -> str:
    """Resolve the server bearer token.

    Precedence: explicit *path* → ``$CHIPIFY_TOKEN`` → default path
    (auto-generated if missing). Generated tokens are written with mode 0600
    and the path is logged to stderr so the operator can copy it into the
    GUI.
    """
    if path is not None:
        path = Path(path)
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
            if not token:
                raise RuntimeError(f"Token file {path} is empty.")
            return token
        # Path provided but file missing → generate at that path.
        return _generate_token(path)

    env_tok = os.environ.get("CHIPIFY_TOKEN", "").strip()
    if env_tok:
        return env_tok

    default = _default_token_path()
    if default.is_file():
        token = default.read_text(encoding="utf-8").strip()
        if token:
            return token
    return _generate_token(default)


def _generate_token(target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    target.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    log.warning(
        "Generated new chipify server token at %s — copy it into the "
        "GUI's Remote settings.",
        target,
    )
    return token


def make_require_token(expected: str) -> Callable:
    """Return a FastAPI dependency that enforces the bearer header."""
    # Imported lazily so the chipify[server] extra is only needed when the
    # server actually runs (the dispatcher imports this module too).
    from fastapi import Header, HTTPException, status

    expected_bytes = expected.encode("utf-8")

    async def require_token(
        authorization: str | None = Header(default=None),
    ) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        candidate = authorization[len("Bearer "):].strip().encode("utf-8")
        if not hmac.compare_digest(candidate, expected_bytes):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return require_token
