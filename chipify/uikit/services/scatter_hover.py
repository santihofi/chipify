# Copyright (c) 2026 Santiago Hofwimmer
"""
scatter_hover.py – Shared hover tooltip + click handling for scatter plots.

One implementation serves both the Advanced Analytics tab (main window) and
the Multi-Plot Dashboard scatter cells. The tooltip annotation is created
lazily on the figure's current axes and is dropped via ``invalidate()``
whenever the owner redraws with ``fig.clf()``.

Robustness rules learned from the two previous copies:
- Never assume x/y values are numeric (corner sweeps yield strings) — format
  via ``fmt_value`` and anchor at the rendered scatter offsets instead of the
  raw data values.
- The annotation must sit above the axes title: titles are drawn after the
  regular axes children at the same default zorder, so an un-raised tooltip
  is painted over by the plot headline.
"""
from __future__ import annotations

import logging

log = logging.getLogger("chipify.uikit.scatter_hover")

_ACCENT = "#3484F0"
_OFFSET = 14  # px gap between the hovered point and the bubble corner


def fmt_value(v) -> str:
    """Format a hover value: 4-significant-digit float, anything else verbatim."""
    try:
        return f"{float(v):.4g}"
    except Exception:
        return str(v)


class HoverState:
    """Snapshot of everything the hover/click handlers need for one plot."""

    def __init__(self, artist, df, x_col, y_col, stim):
        self.artist = artist   # PathCollection returned by ax.scatter
        self.df = df           # DataFrame row-aligned with the artist offsets
        self.x_col = x_col
        self.y_col = y_col
        self.stim = stim       # util.Stimuli or None


class ScatterHoverManager:
    """Hover tooltip + optional point-click dispatch for one mpl canvas.

    Parameters
    ----------
    canvas, fig:
        The FigureCanvasTkAgg and its Figure.
    get_state:
        Callable returning a :class:`HoverState` when scatter hover is
        currently applicable, else ``None`` (e.g. other plot mode active).
    on_point_click:
        Optional ``(row, state, mpl_event) -> None`` called when a scatter
        point is clicked.
    """

    def __init__(self, canvas, fig, get_state, on_point_click=None):
        self._canvas = canvas
        self._fig = fig
        self._get_state = get_state
        self._on_point_click = on_point_click
        self._annot = None

    def connect(self) -> None:
        self._canvas.mpl_connect("motion_notify_event", self._on_motion)
        if self._on_point_click is not None:
            self._canvas.mpl_connect("button_press_event", self._on_click)

    def invalidate(self) -> None:
        """Forget the annotation — call after ``fig.clf()`` redraws."""
        self._annot = None

    # ── Internals ─────────────────────────────────────────────────────────────

    def _hide(self) -> None:
        if self._annot is not None and self._annot.get_visible():
            self._annot.set_visible(False)
            self._canvas.draw_idle()

    def _hit(self, event):
        """Return ``(state, idx)`` for the point under the cursor, else None."""
        state = self._get_state()
        if state is None or state.artist is None or state.df is None:
            return None
        if not self._fig.axes or event.inaxes != self._fig.axes[0]:
            return None
        try:
            cont, ind = state.artist.contains(event)
        except Exception:
            return None
        hits = ind.get("ind", []) if isinstance(ind, dict) else []
        if not cont or len(hits) == 0:
            return None
        return state, int(hits[0])

    def _ensure_annot(self):
        ax = self._fig.axes[0]
        if self._annot is not None and self._annot.axes is ax:
            return self._annot
        self._annot = ax.annotate(
            "", xy=(0, 0), xytext=(_OFFSET, _OFFSET), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.45", fc="#1c1c1c", ec=_ACCENT,
                      lw=1, alpha=0.95),
            color="white",
            arrowprops=dict(arrowstyle="-|>", color=_ACCENT),
        )
        self._annot.set_annotation_clip(False)
        # Above all axes children *including* the title (see module docstring).
        self._annot.set_zorder(1000)
        self._annot.set_visible(False)
        return self._annot

    def _place(self, annot, event) -> None:
        """Flip the bubble's offsets so it stays inside the canvas."""
        try:
            renderer = self._canvas.get_renderer()
            w, h = self._canvas.get_width_height()
            annot.set_position((_OFFSET, _OFFSET))
            annot.set_ha("left")
            annot.set_va("bottom")
            bbox = annot.get_window_extent(renderer)
            x_off = -_OFFSET if event.x + _OFFSET + bbox.width > w else _OFFSET
            y_off = -_OFFSET if event.y + _OFFSET + bbox.height > h else _OFFSET
        except Exception:
            # Renderer not ready — mirror near the top/right axes edges instead.
            try:
                ax_bbox = self._fig.axes[0].get_window_extent()
                x_off = -_OFFSET if event.x > (ax_bbox.x0 + ax_bbox.width * 0.70) else _OFFSET
                y_off = -_OFFSET if event.y > (ax_bbox.y0 + ax_bbox.height * 0.70) else _OFFSET
            except Exception:
                x_off = y_off = _OFFSET
        annot.set_position((x_off, y_off))
        annot.set_ha("right" if x_off < 0 else "left")
        annot.set_va("top" if y_off < 0 else "bottom")

    def _row_for(self, state, idx):
        try:
            return state.df.iloc[idx]
        except Exception:
            return None

    def _on_motion(self, event) -> None:
        hit = self._hit(event)
        if hit is None:
            self._hide()
            return
        state, idx = hit
        row = self._row_for(state, idx)
        if row is None:
            self._hide()
            return

        run_id = str(row.get("run_id", row.name))
        status = "PASS" if bool(row.get("global_pass", False)) else "FAIL"
        text_lines = [
            f"Run #{run_id.zfill(6)}",
            "-" * 15,
            f"{state.x_col}: {fmt_value(row.get(state.x_col, '-'))}",
            f"{state.y_col}: {fmt_value(row.get(state.y_col, '-'))}",
            "-" * 15,
            status,
        ]
        if state.stim is not None:
            for p in getattr(state.stim, "params", {}).keys():
                try:
                    if p in row and state.df[p].nunique() > 1:
                        text_lines.append(f"{p}: {row[p]}")
                except Exception:
                    continue

        annot = self._ensure_annot()
        # Anchor at the rendered offsets, not (row[x], row[y]) — also works
        # for categorical/string axes.
        try:
            annot.xy = tuple(state.artist.get_offsets()[idx])
        except Exception:
            self._hide()
            return
        annot.set_text("\n".join(text_lines))
        self._place(annot, event)
        annot.set_visible(True)
        self._canvas.draw_idle()

    def _on_click(self, event) -> None:
        if getattr(event, "button", None) not in (1, 3):
            return
        hit = self._hit(event)
        if hit is None:
            return
        state, idx = hit
        row = self._row_for(state, idx)
        if row is None:
            return
        try:
            self._on_point_click(row, state, event)
        except Exception:
            log.exception("Scatter point click handler failed.")
