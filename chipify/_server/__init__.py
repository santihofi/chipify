"""
chipify._server – Resources shipped to the remote side of a chipify install.

Currently this package only carries the env-aware wrapper script that
`chipify-cli install-server` drops onto a Linux server (typically the
iic-osic-tools Docker container). Keeping the script as package data
means it travels with the wheel — no separate ``tools/`` checkout is
needed on the server.
"""
from __future__ import annotations

from pathlib import Path

try:
    from importlib.resources import files as _resource_files
except ImportError:  # pragma: no cover — Python < 3.9 fallback
    from importlib_resources import files as _resource_files  # type: ignore[no-redef]


WRAPPER_SCRIPT_NAME = "chipify-remote.sh"


def wrapper_path() -> Path:
    """Return the absolute path to the bundled chipify-remote.sh script.

    Works for both source checkouts (``chipify/_server/chipify-remote.sh``)
    and installed wheels (the file is shipped as ``package_data``).
    """
    resource = _resource_files(__package__).joinpath(WRAPPER_SCRIPT_NAME)
    return Path(str(resource))


def wrapper_text() -> str:
    """Return the wrapper script as a string (for embedding or testing)."""
    return wrapper_path().read_text(encoding="utf-8")
