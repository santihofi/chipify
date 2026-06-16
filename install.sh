#!/usr/bin/env bash
# Copyright (c) 2026 Santiago Hofwimmer
#
# Chipify installer (Linux): system Qt runtime libraries + the Python package
# in a virtual environment.
#
# NOTE: system libraries cannot live in pyproject.toml / setup.py — those only
# declare pip-installable Python packages. The Qt "xcb" platform plugin needs
# the libxcb-cursor0 system library (Qt >= 6.5); without it the PySide6 GUI
# falls back to native Wayland, where combo-box dropdowns don't close on
# selection. We install it here so the GUI works out of the box under XWayland.
set -e

# ── System dependencies (Debian/Ubuntu via apt; best-effort, never fatal) ──────
QT_XCB_LIBS="libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0 libxcb-icccm4 \
libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0"

if command -v apt-get >/dev/null 2>&1; then
    SUDO=""
    if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    fi
    echo "[*] Installing Qt xcb runtime libraries (libxcb-cursor0 + companions)…"
    ${SUDO} apt-get update -qq || true
    ${SUDO} apt-get install -y --no-install-recommends ${QT_XCB_LIBS} \
        || echo "[!] Could not auto-install Qt xcb libs (no permissions?). " \
                "If GUI dropdowns misbehave, install libxcb-cursor0 manually."
else
    echo "[i] apt-get not found; skipping system Qt libraries. On Wayland the GUI" \
         "needs libxcb-cursor0 — install it with your package manager if dropdowns stick."
fi

# ── Python package in a virtual environment ────────────────────────────────────
python -m venv venv && source ./venv/bin/activate && pip install .
