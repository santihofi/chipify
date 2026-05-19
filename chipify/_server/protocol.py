"""
protocol.py – Shared wire-format constants for the chipify HTTPS transport.

Both the server (``chipify/_server/jobs.py``) and the client
(``chipify/remote_dispatcher.py``) parse the same stdout protocol emitted by
``chipify-cli --progress-stream``:

    PROGRESS: <done> <total>      # sweep progress
    PHASE: <name>                 # lifecycle marker (startup, simulating, ...)
    READY <pgid>                  # leader pgid for abort

Keeping the regexes in one module guarantees the formats never drift between
the two ends.
"""
from __future__ import annotations

import re

PROGRESS_RE = re.compile(r"^PROGRESS:\s+(\d+)\s+(\d+)\s*$")
PHASE_RE    = re.compile(r"^PHASE:\s+([A-Za-z0-9_]+)\s*$")
READY_RE    = re.compile(r"^READY\s+(\d+)\s*$")

# Server-Sent Events keepalive line. SSE consumers ignore lines starting with
# ``:`` per the spec; we emit one every ~0.5s when no real data is available
# so middleboxes don't drop the long-poll connection.
SSE_KEEPALIVE = ": keepalive\n\n"

# Bounded log tail kept by both ends for diagnostics / remote console.
LOG_TAIL_SIZE = 200
