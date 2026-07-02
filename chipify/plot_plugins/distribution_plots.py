# Copyright (c) 2026 Santiago Hofwimmer
"""Distribution Plots — built-in QQ, ECDF, and Yield-vs-Spec plot modes.

Ships with Chipify and registers through the standard PlotPlugin
interface (``get_plot_plugins()`` merges these with user plugins; a user
plugin with the same ``name`` overrides the built-in). Three entries in
the Advanced Analytics mode dropdown:

- **QQ Plot (Normality)** — sample vs. theoretical normal quantiles per
  measurement, with the fit r². Points hugging the line mean the metric is
  Gaussian; curvature means skew or heavy tails — i.e. do *not* extrapolate
  yield from a ±3σ fit.
- **ECDF + Spec Limits** — empirical CDF per measurement with the datasheet
  min/max limits drawn in and fail regions shaded; yield is read directly
  off the curve.
- **Yield vs Spec Curve** — yield as a function of where a spec limit is
  placed, the other limit (if any) held fixed. Answers "how much yield do
  we buy if we relax the spec?".

All three are spec-aware: measurements and their min/max limits come from
the loaded datasheet YAML (``values:`` entries; scalar ``measure:``
expressions are included without limits). Panels are laid out as a grid,
one per measurement, capped at 9.

See PLUGINS.md → PlotPlugin for the interface contract.
"""
import logging
import math

import numpy as np
import pandas as pd

from chipify.plugin_loader import PlotPlugin

# ``scipy.stats`` is imported lazily inside ``QQPlot.draw`` (its only user). This
# module is imported eagerly at startup to register the built-in plot modes, so a
# top-level scipy import would add ~0.8s to every launch — even for users who
# never open a QQ plot. See plot_manager.py and app._start_import_warmup.

log = logging.getLogger("chipify.plugins.distribution_plots")

# Mirrors plot_manager defaults so the plugin also renders standalone.
_FALLBACK_THEME = {
    "bg":          "#1a1a1a",
    "fg":          "white",
    "grid":        "gray",
    "spine":       "white",
    "legend_bg":   "#2b2b2b",
    "legend_edge": "gray",
    "legend_text": "white",
    "accent":      "#3484F0",
}

_MAX_PANELS = 9
_SPEC_COLOR = "#e74c3c"     # spec-limit lines and fail shading
_LOWER_COLOR = "#e67e22"    # lower-limit sweep curve (vs accent for upper)
_MIN_POINTS = 3


def _theme(theme):
    th = dict(_FALLBACK_THEME)
    if theme:
        th.update({k: v for k, v in theme.items() if v is not None})
    return th


def _metric_data(valid_df, stim, param=None):
    """[(name, vmin, vmax, values)] for datasheet measurements found in the results.

    Order follows the datasheet; ``values:`` entries carry their limits,
    ``measure:`` expressions come limitless. Columns missing from the
    DataFrame or with fewer than _MIN_POINTS finite values are skipped.

    *param* narrows the result to that single measurement (the host's
    measurement selector); ``None`` keeps every declared measurement.
    """
    declared, seen = [], set()
    for test in getattr(stim, "tests", None) or []:
        for v in getattr(test, "value_lst", None) or []:
            if v.name not in seen:
                seen.add(v.name)
                declared.append((v.name, v.vmin, v.vmax))
        for name in (getattr(test, "measure", None) or {}):
            if name not in seen:
                seen.add(name)
                declared.append((name, None, None))

    if param:
        declared = [d for d in declared if d[0] == param]

    out = []
    for name, vmin, vmax in declared:
        if name not in valid_df.columns:
            continue
        data = pd.to_numeric(valid_df[name], errors="coerce").to_numpy(dtype=float)
        data = data[np.isfinite(data)]
        if data.size >= _MIN_POINTS:
            out.append((name, vmin, vmax, data))
    if len(out) > _MAX_PANELS:
        log.warning("Distribution Plots: %d measurements, showing first %d.",
                    len(out), _MAX_PANELS)
        out = out[:_MAX_PANELS]
    return out


def _grid(fig, n, th):
    """Replace the figure content with an n-panel grid; returns the axes."""
    fig.clf()
    ncols = 1 if n == 1 else (2 if n <= 4 else 3)
    nrows = math.ceil(n / ncols)
    axes = []
    for i in range(n):
        ax = fig.add_subplot(nrows, ncols, i + 1)
        ax.set_facecolor(th["bg"])
        for spine in ax.spines.values():
            spine.set_edgecolor(th["spine"])
        ax.tick_params(colors=th["fg"], labelsize=8)
        ax.grid(True, color=th["grid"], alpha=0.3, linewidth=0.5)
        axes.append(ax)
    return axes


def _message(ax, text, th):
    ax.text(0.5, 0.5, text, ha="center", va="center",
            color=th["fg"], transform=ax.transAxes)


def _yield_pct(data, vmin, vmax):
    ok = np.ones(data.size, dtype=bool)
    if vmin is not None:
        ok &= data >= vmin
    if vmax is not None:
        ok &= data <= vmax
    return 100.0 * float(ok.mean())


_NO_METRICS_MSG = ("No datasheet measurements found in the results.\n"
                   "Define values:/measure: entries in the datasheet YAML.")


def _no_data_msg(param) -> str:
    if param:
        return (f"No data for measurement {param!r}.\n"
                "It may be missing from this run or have too few points.")
    return _NO_METRICS_MSG


class QQPlot(PlotPlugin):
    """Normal quantile-quantile plot per measurement."""

    name = "QQ Plot (Normality)"
    supports_param = True

    def draw(self, fig, ax, valid_df, stim, *, theme=None, param=None):
        import scipy.stats as stats  # lazy: keeps scipy off the GUI launch path
        th = _theme(theme)
        metrics = _metric_data(valid_df, stim, param)
        if not metrics:
            _message(ax, _no_data_msg(param), th)
            return
        for ax_i, (name, _vmin, _vmax, data) in zip(_grid(fig, len(metrics), th), metrics):
            (osm, osr), (slope, intercept, r) = stats.probplot(data, dist="norm")
            osm = np.asarray(osm)
            ax_i.plot(osm, osr, "o", ms=3, color=th["accent"],
                      alpha=0.65, mec="none")
            ax_i.plot(osm, slope * osm + intercept, "-", color=th["fg"],
                      lw=1.0, alpha=0.8)
            ax_i.set_title(f"{name}  (n={data.size}, r²={r ** 2:.4f})",
                           color=th["fg"], fontsize=9)
            ax_i.set_xlabel("Theoretical quantiles (σ)", color=th["fg"], fontsize=8)
            ax_i.set_ylabel(name, color=th["fg"], fontsize=8)


class ECDFSpecLimits(PlotPlugin):
    """Empirical CDF per measurement with spec limits and fail shading."""

    name = "ECDF + Spec Limits"
    supports_param = True

    def draw(self, fig, ax, valid_df, stim, *, theme=None, param=None):
        th = _theme(theme)
        metrics = _metric_data(valid_df, stim, param)
        if not metrics:
            _message(ax, _no_data_msg(param), th)
            return
        for ax_i, (name, vmin, vmax, data) in zip(_grid(fig, len(metrics), th), metrics):
            x = np.sort(data)
            y = np.arange(1, x.size + 1) * (100.0 / x.size)
            ax_i.step(x, y, where="post", color=th["accent"], lw=1.4)
            ax_i.set_ylim(0, 105)

            for limit in (vmin, vmax):
                if limit is not None:
                    ax_i.axvline(limit, color=_SPEC_COLOR, ls="--", lw=1.0)
            # Shade the fail regions outside the limits.
            xlo, xhi = ax_i.get_xlim()
            if vmin is not None and vmin > xlo:
                ax_i.axvspan(xlo, vmin, color=_SPEC_COLOR, alpha=0.10, lw=0)
            if vmax is not None and vmax < xhi:
                ax_i.axvspan(vmax, xhi, color=_SPEC_COLOR, alpha=0.10, lw=0)
            ax_i.set_xlim(xlo, xhi)

            title = name
            if vmin is not None or vmax is not None:
                title += f"  —  yield {_yield_pct(data, vmin, vmax):.1f}%"
            ax_i.set_title(title, color=th["fg"], fontsize=9)
            ax_i.set_xlabel(name, color=th["fg"], fontsize=8)
            ax_i.set_ylabel("Cumulative %", color=th["fg"], fontsize=8)


class YieldVsSpecCurve(PlotPlugin):
    """Yield as a function of spec-limit placement, per measurement."""

    name = "Yield vs Spec Curve"
    supports_param = True

    def draw(self, fig, ax, valid_df, stim, *, theme=None, param=None):
        th = _theme(theme)
        metrics = _metric_data(valid_df, stim, param)
        if not metrics:
            _message(ax, _no_data_msg(param), th)
            return
        for ax_i, (name, vmin, vmax, data) in zip(_grid(fig, len(metrics), th), metrics):
            n = data.size
            lo, hi = float(data.min()), float(data.max())
            span = (hi - lo) or max(abs(hi), 1.0)
            ts = np.linspace(lo - 0.05 * span, hi + 0.05 * span, 257)

            # Sweep one limit while the other (if defined) stays fixed, so the
            # curve passes exactly through the current joint yield at the spec.
            if vmax is not None or vmin is None:
                subset = np.sort(data[data >= vmin]) if vmin is not None else np.sort(data)
                y = np.searchsorted(subset, ts, side="right") * (100.0 / n)
                label = "max-spec swept" + ("" if vmin is None else " (min fixed)")
                ax_i.plot(ts, y, color=th["accent"], lw=1.4, label=label)
            if vmin is not None or vmax is None:
                subset = np.sort(data[data <= vmax]) if vmax is not None else np.sort(data)
                y = (subset.size - np.searchsorted(subset, ts, side="left")) * (100.0 / n)
                label = "min-spec swept" + ("" if vmax is None else " (max fixed)")
                ax_i.plot(ts, y, color=_LOWER_COLOR, lw=1.4, label=label)

            # Mark the currently configured spec point(s).
            pct_now = _yield_pct(data, vmin, vmax)
            for limit in (vmin, vmax):
                if limit is not None:
                    ax_i.plot([limit], [pct_now], "o", ms=6, color=_SPEC_COLOR)
                    ax_i.annotate(f"{pct_now:.1f}%", (limit, pct_now),
                                  textcoords="offset points", xytext=(6, 6),
                                  color=th["fg"], fontsize=8)
                    ax_i.axvline(limit, color=_SPEC_COLOR, ls=":", lw=0.8, alpha=0.6)

            ax_i.set_ylim(0, 105)
            ax_i.set_title(name, color=th["fg"], fontsize=9)
            ax_i.set_xlabel(f"{name} spec threshold", color=th["fg"], fontsize=8)
            ax_i.set_ylabel("Yield (%)", color=th["fg"], fontsize=8)
            leg = ax_i.legend(fontsize=7, facecolor=th["legend_bg"],
                              edgecolor=th["legend_edge"])
            for text in leg.get_texts():
                text.set_color(th["legend_text"])
