"""
main_thread_bridge.py – Thread-safe DataFrame transfer from background
threads to the Tkinter main thread via queue.Queue + widget.after().

The background thread calls ``enqueue_chunk(df)`` (thread-safe).
The main thread polls the queue and calls ``AppState.append_results()``.
"""
from __future__ import annotations

import logging
import queue

import pandas as pd

log = logging.getLogger("chipify.bridge")


class MainThreadBridge:
    """Queue-based dispatcher: background thread → Tkinter main thread."""

    def __init__(self, root_widget, state, poll_interval_ms: int = 100):
        self._root = root_widget
        self._state = state
        self._queue: queue.Queue = queue.Queue()
        self._poll_ms = poll_interval_ms
        self._polling = False
        self._after_id = None
        self._defer_apply_id = None
        self._deferred_apply_df = None

    # ── Called from ANY thread (thread-safe) ──────────────────────────────

    def enqueue_chunk(self, chunk_df) -> None:
        """Put a partial DataFrame onto the queue. Thread-safe."""
        self._queue.put(chunk_df)

    # ── Called from main thread only ──────────────────────────────────────

    def start_polling(self) -> None:
        """Begin polling the queue on the Tkinter main thread."""
        self._polling = True
        self._poll()

    def stop_polling(self) -> None:
        """Stop polling and drain any remaining queued items."""
        self._polling = False
        if self._after_id is not None:
            self._root.after_cancel(self._after_id)
            self._after_id = None
        if self._defer_apply_id is not None:
            self._root.after_cancel(self._defer_apply_id)
            self._defer_apply_id = None
        if self._deferred_apply_df is not None:
            df = self._deferred_apply_df
            self._deferred_apply_df = None
            try:
                self._state.append_results(df)
            except Exception:
                log.exception("append_results failed in bridge stop flush.")
        self._drain()

    def _schedule_apply_flush(self) -> None:
        if self._defer_apply_id is None:
            self._defer_apply_id = self._root.after(0, self._flush_deferred_apply)

    def _flush_deferred_apply(self) -> None:
        self._defer_apply_id = None
        df = self._deferred_apply_df
        self._deferred_apply_df = None
        if df is None:
            return
        try:
            self._state.append_results(df)
        except Exception:
            log.exception("append_results failed in deferred bridge apply.")

    def _poll(self) -> None:
        """Process queued chunks (merge per tick), then reschedule."""
        batch_limit = 12
        chunks: list = []
        for _ in range(batch_limit):
            try:
                chunks.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if chunks:
            merged = chunks[0]
            if len(chunks) > 1:
                merged = pd.concat(chunks, ignore_index=True)
            if self._deferred_apply_df is not None:
                merged = pd.concat([self._deferred_apply_df, merged], ignore_index=True)
            self._deferred_apply_df = merged
            self._schedule_apply_flush()
        if self._polling:
            self._after_id = self._root.after(self._poll_ms, self._poll)

    def _drain(self) -> None:
        """Process all remaining items in the queue (merged into one append)."""
        chunks: list = []
        while not self._queue.empty():
            try:
                chunks.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return
        merged = chunks[0]
        if len(chunks) > 1:
            merged = pd.concat(chunks, ignore_index=True)
        try:
            self._state.append_results(merged)
        except Exception:
            log.exception("append_results failed in bridge drain.")
