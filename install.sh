#!/usr/bin/env bash
# Copyright (c) 2026 Santiago Hofwimmer
#
# Chipify installer (Linux): system Qt runtime libraries + the Python package
# in a virtual environment.
#
# NOTE: system libraries cannot live in pyproject.toml / setup.py — those only
# declare pip-installable Python packages. The Qt GUI uses PySide6-Essentials
# (the pip dependency), which needs two kinds of system libs:
#   * Base Qt runtime (libEGL.so.1 / libGL.so.1 / glib): dlopened when importing
#     QtWidgets — required even under the headless "offscreen" platform (so the
#     GUI *and* the offscreen test suite fail to import without them).
#   * xcb platform plugin (libxcb-cursor0, Qt >= 6.5): needed for the on-screen
#     GUI under XWayland; without it the app falls back to native Wayland, where
#     combo-box dropdowns don't close on selection.
# We install both here so the GUI and tests work out of the box. If apt can't
# reach the Ubuntu mirrors — some networks block archive.ubuntu.com while general
# internet (PyPI) still works — we fall back to fetching libxcb-cursor0, the lib
# the on-screen GUI most often lacks, straight from a reachable package mirror.
set -e

# ── System dependencies (Debian/Ubuntu via apt; best-effort, never fatal) ──────
QT_BASE_LIBS="libegl1 libgl1 libglib2.0-0 libdbus-1-3"
QT_XCB_LIBS="libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0 libxcb-icccm4 \
libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0"

# Run privileged steps via sudo when not already root (never fatal if absent).
SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
fi

# Download URL ($1) to file ($2) with whichever of curl/wget exists; 1 if neither.
_fetch() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -q "$1" -O "$2"
    else
        return 1
    fi
}

# Fallback for the one lib the on-screen GUI most often lacks. Qt >= 6.5 hard-
# requires libxcb-cursor.so.0 for the xcb platform plugin; without it chipify
# can't use xcb/XWayland and falls back to native Wayland (slow launch + combo-box
# popup bugs). When apt can't reach archive.ubuntu.com the step below silently
# leaves this lib missing, so here we grab just that .deb from the first reachable
# mirror and dpkg-install it — its runtime deps (libxcb1 / -render0 / -image0)
# ship with any Qt base install, so no dependency resolution is needed. No-op when
# the lib is already present or no downloader/dpkg/gzip is available.
ensure_libxcb_cursor() {
    command -v ldconfig >/dev/null 2>&1 || return 0
    if ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so\.0'; then
        return 0
    fi
    command -v dpkg >/dev/null 2>&1 || return 0
    command -v gzip >/dev/null 2>&1 || return 0

    local codename arch tmp relpath deb
    codename="$( . /etc/os-release 2>/dev/null && printf '%s' "${VERSION_CODENAME:-}" )"
    arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
    if [ -z "$codename" ]; then
        echo "[!] libxcb-cursor0 missing and the Ubuntu codename is unknown — install it manually."
        return 0
    fi

    echo "[*] libxcb-cursor0 not found; fetching it directly (apt mirror unreachable?)…"
    tmp="$(mktemp -d)"
    for m in \
        https://mirror.us.leaseweb.net/ubuntu \
        http://mirrors.kernel.org/ubuntu \
        http://mirror.enzu.com/ubuntu
    do
        for comp in universe main; do
            _fetch "${m}/dists/${codename}/${comp}/binary-${arch}/Packages.gz" \
                   "${tmp}/Packages.gz" || continue
            relpath="$(gzip -dc "${tmp}/Packages.gz" 2>/dev/null | awk '
                $1 == "Package:"  { pkg = $2 }
                pkg == "libxcb-cursor0" && $1 == "Filename:" { print $2; exit }')"
            [ -n "$relpath" ] || continue
            if _fetch "${m}/${relpath}" "${tmp}/libxcb-cursor0.deb"; then
                deb="${tmp}/libxcb-cursor0.deb"
                break 2
            fi
        done
    done

    if [ -n "${deb:-}" ]; then
        ${SUDO} dpkg -i "$deb" \
            && echo "[*] Installed libxcb-cursor0 from a package mirror." \
            || echo "[!] Fetched libxcb-cursor0 but dpkg failed — install it manually."
    else
        echo "[!] Could not fetch libxcb-cursor0 from any fallback mirror — install it manually."
    fi
    rm -rf "$tmp"
}

if command -v apt-get >/dev/null 2>&1; then
    echo "[*] Installing Qt runtime libraries (libEGL/libGL base + libxcb-cursor0 + companions)…"
    ${SUDO} apt-get update -qq || true
    ${SUDO} apt-get install -y --no-install-recommends ${QT_BASE_LIBS} ${QT_XCB_LIBS} \
        || echo "[!] apt could not install all Qt system libs (no permissions / mirror unreachable?)."
else
    echo "[i] apt-get not found; skipping apt. PySide6 needs libegl1/libgl1 to import" \
         "at all, plus libxcb-cursor0 for the on-screen GUI — install with your package manager."
fi

# Even when apt reports success, a silently-blocked mirror can leave this one out;
# make sure it's present (best-effort, never fatal).
ensure_libxcb_cursor || true

# ── Python package in a virtual environment ────────────────────────────────────
python -m venv venv && source ./venv/bin/activate && pip install -e .

# ── Expose the commands on PATH without activating the venv ────────────────────
# The console scripts in venv/bin carry an absolute shebang (the venv's own
# python), so symlinks to them work from any directory and any shell — no
# activation needed. `chipify` is mapped to chipify-qt so the Qt GUI is the
# default entry point.
VENV_BIN="$(cd venv/bin && pwd)"
USER_BIN="${HOME}/.local/bin"
mkdir -p "${USER_BIN}"
ln -sf "${VENV_BIN}/chipify"  "${USER_BIN}/chipify"      # Qt GUI = default
ln -sf "${VENV_BIN}/chipify-cli" "${USER_BIN}/chipify-cli"

# Make sure ~/.local/bin is on PATH for future shells (bash and zsh).
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
touch "${HOME}/.bashrc"
for RC in "${HOME}/.bashrc" "${HOME}/.zshrc"; do
    [ -e "${RC}" ] || continue
    grep -qsF '.local/bin' "${RC}" || printf '%s\n' "${PATH_LINE}" >> "${RC}"
done

echo "[*] Linked chipify and chipify-cli into ${USER_BIN} (chipify -> Qt GUI)."
echo "    Run 'chipify' in a new shell, or load it now with:"
echo "        export PATH=\"\$HOME/.local/bin:\$PATH\""
