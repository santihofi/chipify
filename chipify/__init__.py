# Copyright (c) 2026 Santiago Hofwimmer
"""Chipify – mismatch simulation, parameter sweeping, and yield analysis."""

__version__ = "0.2.3"


def version_info() -> str:
    """Version plus the install this import resolved to, as one line.

    The path carries as much information as the number: a machine can hold both
    a packaged chipify and a working tree (the IIC-OSIC-TOOLS container ships
    one preinstalled), and the two can report the *same* version — so the
    number alone cannot answer "which one am I running?".
    """
    from pathlib import Path

    return f"chipify {__version__} ({Path(__file__).resolve().parent})"
