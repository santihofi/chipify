#!/usr/bin/env bash
# chipify-remote — env-aware wrapper for chipify-cli inside an
# iic-osic-tools container.
#
# Installed by `chipify-cli install-server` (or tools/server/bootstrap.sh
# for source-checkout users) to one of:
#   ~/.local/bin/chipify-remote   (per-user, default)
#   /usr/local/bin/chipify-remote (system, --system mode)
#
# Used by the local Chipify GUI's RemoteDispatcher as the value of
# the "Remote Command" field. Its job is to fix the things that go
# wrong in a non-interactive SSH session:
#
#   1. ~/.local/bin and /foss/tools/*/bin are not on PATH.
#   2. ~/.bashrc / /etc/profile.d/*.sh are not sourced.
#   3. PDK / PDK_ROOT / STD_CELL_LIBRARY are unset.
#   4. Non-UTF8 locale corrupts ngspice / Python output.
#
# The wrapper applies a deterministic environment, then exec's
# chipify-cli with all passed arguments forwarded verbatim.

set -eu

# ── 1. PATH: pip --user, then EDA tools, then existing PATH ───────
PATH="${HOME}/.local/bin:${PATH}"
for d in /foss/tools/*/bin; do
    [ -d "$d" ] && PATH="$d:$PATH"
done
export PATH

# ── 2. PDK environment ────────────────────────────────────────────
# Honour an explicit env file if present. Search order:
#   $CHIPIFY_REMOTE_ENV   (explicit override)
#   ~/.chipify-remote.env (per-user, written by install-server)
#   /etc/chipify-remote.env (system-wide)
#   /headless/.chipify-remote.env (iic-osic-tools default home)
_chipify_env_loaded=""
for envf in \
    "${CHIPIFY_REMOTE_ENV:-}" \
    "${HOME}/.chipify-remote.env" \
    "/etc/chipify-remote.env" \
    "/headless/.chipify-remote.env"
do
    if [ -n "$envf" ] && [ -r "$envf" ]; then
        # shellcheck disable=SC1090
        . "$envf"
        _chipify_env_loaded="$envf"
        break
    fi
done

# Sensible defaults for iic-osic-tools when no env file was loaded.
: "${PDK_ROOT:=/foss/pdks}"
export PDK_ROOT

# ── 3. Locale ─────────────────────────────────────────────────────
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"

# ── 4. Stable Python output (avoid buffering deadlocks over SSH) ──
export PYTHONUNBUFFERED=1

# ── 5. Locate chipify-cli ─────────────────────────────────────────
if ! command -v chipify-cli >/dev/null 2>&1; then
    cat >&2 <<EOF
chipify-remote: chipify-cli not found after env setup.

  PATH=${PATH}
  loaded env file: ${_chipify_env_loaded:-<none>}

Reinstall chipify on this host:
  python3 -m pip install --user "chipify[remote]"
  chipify-cli install-server
EOF
    exit 127
fi

# ── 6. Hand off ──────────────────────────────────────────────────
exec chipify-cli "$@"
