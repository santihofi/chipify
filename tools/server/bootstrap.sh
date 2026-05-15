#!/usr/bin/env bash
# bootstrap.sh — convenience installer for the server side of chipify
# (typically inside an iic-osic-tools Docker container).
#
# This script is a thin wrapper around the canonical install path:
#
#   1. pip install chipify[remote]   (from a local checkout if available,
#                                     else from PyPI)
#   2. chipify-cli install-server    (drops the wrapper, writes env, runs
#                                     preflight)
#
# If you already have chipify installed, you can skip this script and
# just run `chipify-cli install-server` directly.
#
# All flags after `--` are forwarded to chipify-cli install-server.
# Common flags: --system, --pdk NAME, --no-env, --force, --no-verify.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)"

PYTHON="$(command -v python3 || command -v python || true)"
if [[ -z "$PYTHON" ]]; then
    echo "error: python3 / python not found." >&2
    exit 1
fi
echo "[1/2] Installing chipify (pip --user, extras=[remote])..."
if [[ -f "$REPO_ROOT/setup.py" && -d "$REPO_ROOT/chipify" ]]; then
    echo "      (from local checkout: $REPO_ROOT)"
    "$PYTHON" -m pip install --user --upgrade --no-warn-script-location \
        "${REPO_ROOT}[remote]"
else
    echo "      (from PyPI)"
    "$PYTHON" -m pip install --user --upgrade --no-warn-script-location \
        "chipify[remote]"
fi

# After --user install, chipify-cli lives in ~/.local/bin which is not
# guaranteed to be on PATH for non-interactive shells. Find it explicitly.
CHIPIFY_CLI=""
for c in \
    "$HOME/.local/bin/chipify-cli" \
    "/usr/local/bin/chipify-cli" \
    "$(command -v chipify-cli 2>/dev/null || true)"
do
    if [[ -n "$c" && -x "$c" ]]; then
        CHIPIFY_CLI="$c"
        break
    fi
done
if [[ -z "$CHIPIFY_CLI" ]]; then
    echo "error: chipify-cli was not found after pip install." >&2
    echo "       Ensure ~/.local/bin is on PATH, then run:" >&2
    echo "       chipify-cli install-server [--system] [--pdk NAME]" >&2
    exit 1
fi

echo "[2/2] Running ${CHIPIFY_CLI} install-server $*"
exec "$CHIPIFY_CLI" install-server "$@"
