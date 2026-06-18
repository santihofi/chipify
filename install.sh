#!/usr/bin/env bash
# Copyright (c) 2026 Santiago Hofwimmer
#
# Chipify installer (Linux): system Qt runtime libraries + the Python package
# in a virtual environment.
#
# NOTE: system libraries cannot live in pyproject.toml / setup.py — those only
# declare pip-installable Python packages. PySide6 needs two kinds of system libs:
#   * Base Qt runtime (libEGL.so.1 / libGL.so.1 / glib): dlopened when importing
#     QtWidgets — required even under the headless "offscreen" platform (so the
#     GUI *and* the offscreen test suite fail to import without them).
#   * xcb platform plugin (libxcb-cursor0, Qt >= 6.5): needed for the on-screen
#     GUI under XWayland; without it the app falls back to native Wayland, where
#     combo-box dropdowns don't close on selection.
# We install both here so the GUI and tests work out of the box.
set -e

# ── System dependencies (Debian/Ubuntu via apt; best-effort, never fatal) ──────
QT_BASE_LIBS="libegl1 libgl1 libglib2.0-0 libdbus-1-3"
QT_XCB_LIBS="libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0 libxcb-icccm4 \
libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0"

if command -v apt-get >/dev/null 2>&1; then
    SUDO=""
    if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    fi
    echo "[*] Installing Qt runtime libraries (libEGL/libGL base + libxcb-cursor0 + companions)…"
    ${SUDO} apt-get update -qq || true
    ${SUDO} apt-get install -y --no-install-recommends ${QT_BASE_LIBS} ${QT_XCB_LIBS} \
        || echo "[!] Could not auto-install Qt system libs (no permissions?). " \
                "Install libegl1 libgl1 (base) and libxcb-cursor0 (on-screen GUI) manually."
else
    echo "[i] apt-get not found; skipping system Qt libraries. PySide6 needs" \
         "libegl1/libgl1 to import at all, plus libxcb-cursor0 for the on-screen" \
         "GUI — install them with your package manager."
fi

# ── Python package in a virtual environment ────────────────────────────────────
python -m venv venv && source ./venv/bin/activate && pip install .
