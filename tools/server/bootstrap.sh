#!/usr/bin/env bash
# bootstrap.sh — one-shot chipify install inside an iic-osic-tools container.
#
# Run this *inside* the container, as the unprivileged user (designer / root /
# headless — anything goes; --system needs sudo):
#
#   curl -fsSL <repo-raw>/tools/server/bootstrap.sh | bash
#   # or, from a checkout:
#   bash tools/server/bootstrap.sh [--system] [--pdk NAME] [--no-env]
#
# What it does (idempotent — safe to re-run):
#   1. pip install --user --upgrade "chipify[remote]"  (or local checkout if found)
#   2. Drops chipify-remote (the env-aware wrapper) into ~/.local/bin
#      or /usr/local/bin with --system.
#   3. Writes a default ~/.chipify-remote.env exporting PDK / PDK_ROOT
#      (skip with --no-env).
#   4. Runs `chipify-remote --preflight` and prints the JSON so you can
#      paste it back to whoever set this up.
#
# After this completes, in the Chipify GUI (locally) set the Remote tab to:
#   Remote Command : ~/.local/bin/chipify-remote   (or /usr/local/bin/chipify-remote)

set -euo pipefail

PDK_DEFAULT="${PDK:-ihp-sg13g2}"
ENV_FILE_DEFAULT="${HOME}/.chipify-remote.env"

usage() {
    cat <<EOF
chipify bootstrap inside iic-osic-tools

Usage: $(basename "$0") [--system] [--pdk NAME] [--no-env] [--no-verify]

Options:
  --system        Install wrapper system-wide to /usr/local/bin (needs sudo).
                  Otherwise per-user at \$HOME/.local/bin/chipify-remote.
  --pdk NAME      Default PDK written to ~/.chipify-remote.env
                  (current: ${PDK_DEFAULT}).
  --no-env        Skip writing a default ~/.chipify-remote.env.
  --no-verify     Skip the post-install --preflight check.
  -h, --help      Show this help.
EOF
}

SYSTEM=0
PDK_TARGET="$PDK_DEFAULT"
WRITE_ENV=1
DO_VERIFY=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --system)    SYSTEM=1; shift ;;
        --pdk)       PDK_TARGET="$2"; shift 2 ;;
        --no-env)    WRITE_ENV=0; shift ;;
        --no-verify) DO_VERIFY=0; shift ;;
        -h|--help)   usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

# ── Detect repo checkout vs. PyPI install ────────────────────────
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." &>/dev/null && pwd)"
HAVE_CHECKOUT=0
if [[ -f "$REPO_ROOT/setup.py" && -d "$REPO_ROOT/chipify" ]]; then
    HAVE_CHECKOUT=1
fi

PYTHON="$(command -v python3 || command -v python || true)"
if [[ -z "$PYTHON" ]]; then
    echo "python3 / python not found — aborting." >&2
    exit 1
fi
echo "Using python: $PYTHON ($($PYTHON -V 2>&1))"

# ── Step 1: pip install ──────────────────────────────────────────
echo "[1/4] Installing chipify (pip --user, extras=[remote])..."
if [[ "$HAVE_CHECKOUT" -eq 1 ]]; then
    echo "      (using local checkout at $REPO_ROOT)"
    "$PYTHON" -m pip install --user --upgrade --no-warn-script-location \
        "${REPO_ROOT}[remote]"
else
    echo "      (using PyPI)"
    "$PYTHON" -m pip install --user --upgrade --no-warn-script-location \
        "chipify[remote]"
fi

# ── Step 2: wrapper ──────────────────────────────────────────────
WRAPPER_SRC="$SCRIPT_DIR/chipify-remote.sh"
if [[ ! -r "$WRAPPER_SRC" ]]; then
    echo "Wrapper source not found at $WRAPPER_SRC — aborting." >&2
    exit 1
fi

if [[ "$SYSTEM" -eq 1 ]]; then
    WRAPPER_DST="/usr/local/bin/chipify-remote"
    SUDO=""
    [[ $EUID -ne 0 ]] && SUDO="sudo"
    echo "[2/4] Installing wrapper to $WRAPPER_DST (system-wide; may prompt for sudo)..."
    $SUDO install -m 0755 "$WRAPPER_SRC" "$WRAPPER_DST"
else
    WRAPPER_DST="$HOME/.local/bin/chipify-remote"
    mkdir -p "$(dirname "$WRAPPER_DST")"
    echo "[2/4] Installing wrapper to $WRAPPER_DST..."
    install -m 0755 "$WRAPPER_SRC" "$WRAPPER_DST"
fi

# ── Step 3: env file ─────────────────────────────────────────────
if [[ "$WRITE_ENV" -eq 1 && ! -f "$ENV_FILE_DEFAULT" ]]; then
    echo "[3/4] Writing default env file $ENV_FILE_DEFAULT (pdk=$PDK_TARGET)..."
    cat > "$ENV_FILE_DEFAULT" <<EOF
# Sourced by chipify-remote before exec'ing chipify-cli.
# Edit to point at your active PDK / extra tool paths.
export PDK_ROOT="/foss/pdks"
export PDK="${PDK_TARGET}"

# Optional standard cell selection (sky130 example):
# export STD_CELL_LIBRARY="sky130_fd_sc_hd"

# Optional extra PATH entries (xschem libs, custom binaries):
# export PATH="\$PATH:/foss/designs/mytools/bin"
EOF
    chmod 0600 "$ENV_FILE_DEFAULT"
else
    if [[ "$WRITE_ENV" -eq 0 ]]; then
        echo "[3/4] Skipping env file (--no-env)."
    else
        echo "[3/4] Env file already exists, leaving it alone: $ENV_FILE_DEFAULT"
    fi
fi

# ── Step 4: verify ───────────────────────────────────────────────
if [[ "$DO_VERIFY" -eq 1 ]]; then
    echo "[4/4] Verifying via $WRAPPER_DST --preflight ..."
    if "$WRAPPER_DST" --preflight; then
        cat <<EOF

────────────────────────────────────────────────────────────────
  chipify-remote is ready.

  In the Chipify GUI on your laptop, open Settings → Remote and set:
    Compute Target  : remote
    Server IP / Host: <this host's address>
    Username        : $(id -un)
    SSH Key Path    : (path to your private key file)
    Remote Command  : ${WRAPPER_DST}
  Then click "Test Connection".
────────────────────────────────────────────────────────────────
EOF
    else
        echo
        echo "× Preflight reported issues (JSON above)."
        echo "  Common fixes:"
        echo "    - Edit ${ENV_FILE_DEFAULT} to set the right PDK."
        echo "    - apt install ngspice xschem (or rebuild the container)."
        exit 3
    fi
else
    echo "[4/4] Skipping verify (--no-verify)."
fi
