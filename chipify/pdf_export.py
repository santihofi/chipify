"""
pdf_export.py – Professional IC-datasheet-style PDF report for Chipify.

Page structure (strict A4 portrait throughout):
  1. Cover          – header bar, metadata block, yield badge, stats,
                      fail-breakdown pie chart (only when yield < 100 %)
  2. Measurements   – centred, IC-datasheet-styled table, alternating rows,
                      colour-coded Cpk + Status cells
  3. Histograms     – 2-up per page, white bg, Gauss fit + spec lines +
                      per-plot annotation box (μ, σ, Cpk, Status)
  4. Correlation    – white-background Pearson heatmap
"""

import os
import datetime
import math
import textwrap

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
import scipy.stats as stats

from chipify import app_config
from chipify.plot_manager import PlotManager

# ── Style constants ────────────────────────────────────────────────────────────
BLUE   = "#1a5fa8"
GREEN  = "#1e7d3a"
LGREEN = "#d6f0de"
RED    = "#b71c1c"
LRED   = "#fde8e8"
AMBER  = "#c67c00"
LGRAY  = "#f0f0f0"
MGRAY  = "#c8c8c8"
DGRAY  = "#555555"

A4     = (8.27, 11.69)   # inches
ML     = 0.07            # left/right margin in figure-fraction units
MB     = 0.05            # bottom margin

mpl.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.8,
})


# ── Low-level helpers ──────────────────────────────────────────────────────────

def _fmt(v):
    if v is None:
        return "–"
    if isinstance(v, float) and math.isnan(v):
        return "–"
    if isinstance(v, (int, float, np.number)):
        return f"{v:.4g}"
    return str(v)


def _build_global_pass(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "sim_error" not in out.columns:
        out["sim_error"] = "None"
    out["sim_error"] = out["sim_error"].fillna("None").astype(str)
    out.loc[out["sim_error"].str.lower() == "nan", "sim_error"] = "None"
    tb_cols = [c for c in out.columns if c.endswith("_overall_pass")]
    out["global_pass"] = True
    for c in tb_cols:
        out["global_pass"] &= out[c]
    return out


def _get_spec(val_obj):
    lo = getattr(val_obj, "vmin", getattr(val_obj, "min", None))
    hi = getattr(val_obj, "vmax", getattr(val_obj, "max", None))
    return lo, hi


def _compute_cpk(data: pd.Series, lo, hi) -> float:
    if len(data) < 2:
        return float("nan")
    mu, sigma = data.mean(), data.std()
    if sigma <= 0:
        return float("nan")
    cpks = []
    if lo is not None:
        cpks.append((mu - lo) / (3 * sigma))
    if hi is not None:
        cpks.append((hi - mu) / (3 * sigma))
    return min(cpks) if cpks else float("nan")


def _cpk_cell_bg(cpk):
    if math.isnan(cpk):
        return LGRAY
    if cpk >= 1.33:
        return LGREEN
    if cpk >= 1.0:
        return "#fff3cd"
    return LRED


def _measurement_rows(valid_df: pd.DataFrame, stim) -> list:
    rows = []
    for test in stim.tests:
        for val_obj in test.value_lst:
            p = val_obj.name
            if p not in valid_df.columns:
                continue
            data = valid_df[p].dropna()
            lo, hi = _get_spec(val_obj)
            cpk = _compute_cpk(data, lo, hi)
            pass_col = f"{p}_pass"
            passed = pass_col in valid_df.columns and bool(valid_df[pass_col].all())
            rows.append({
                "name":    p,
                "sim_min": data.min()  if not data.empty else float("nan"),
                "sim_typ": data.mean() if not data.empty else float("nan"),
                "sim_max": data.max()  if not data.empty else float("nan"),
                "spec_lo": lo,
                "spec_hi": hi,
                "cpk":     cpk,
                "passed":  passed,
            })
    return rows


# ── Metadata helpers (for cover page) ─────────────────────────────────────────

def _swept_params(stim, df: pd.DataFrame) -> list:
    if stim is not None and hasattr(stim, "params"):
        names = []
        for pname, pvalues in stim.params.items():
            try:
                if hasattr(pvalues, "__len__") and not isinstance(pvalues, str) and len(pvalues) > 1:
                    names.append(str(pname))
            except Exception:
                continue
        return names
    fallback = []
    for c in df.columns:
        if c.endswith("_pass") or c.endswith("_overall_pass") or c in ("global_pass", "sim_error"):
            continue
        try:
            n = df[c].nunique(dropna=True)
            if 1 < n <= 64:
                fallback.append(c)
        except Exception:
            continue
    return fallback


def _sim_duration_sec(df: pd.DataFrame):
    for col in (
        "simulation_duration_s_total",
        "sim_duration_s",
        "simulation_duration_s",
        "duration_s",
        "elapsed_s",
        "sim_time_s",
    ):
        if col in df.columns:
            try:
                return float(pd.to_numeric(df[col], errors="coerce").sum())
            except Exception:
                continue
    return None


class _DummyCanvas:
    def draw(self):
        pass


# ── Page header bar (shared across all pages) ─────────────────────────────────

def _page_header(fig, label: str):
    ax = fig.add_axes([0, 0.935, 1, 0.065])
    ax.set_facecolor(BLUE)
    ax.axis("off")
    ax.text(0.5, 0.5, label, color="white", fontsize=14, weight="bold",
            ha="center", va="center", transform=ax.transAxes)
    return ax


# ── Section 1: Cover page ─────────────────────────────────────────────────────

def _add_cover(pdf: PdfPages, df: pd.DataFrame, yaml_path, rows, stim, sim_duration_sec=None):
    fig = plt.figure(figsize=A4, facecolor="white")
    _page_header(fig, "Chipify Statistical Report")

    ax = fig.add_axes([ML, MB, 1 - 2 * ML, 0.935 - MB])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # ── Title block ──────────────────────────────────────────────────────────
    yaml_name = os.path.basename(yaml_path) if yaml_path else "Unknown"
    ax.text(0.5, 0.955, yaml_name,
            ha="center", va="top", fontsize=12, weight="bold", color=DGRAY)
    ax.text(0.5, 0.925,
            datetime.datetime.now().strftime("Generated  %Y-%m-%d  %H:%M:%S"),
            ha="center", va="top", fontsize=9, color=MGRAY)

    # ── Metadata grid ────────────────────────────────────────────────────────
    cfg = app_config.load_config()
    core_raw = cfg.get("num_cores")
    core_txt = str(core_raw) if core_raw else "auto"

    dur = sim_duration_sec if sim_duration_sec is not None else _sim_duration_sec(df)
    dur_txt = f"{dur:.1f} s" if dur is not None else "n/a"

    swept = _swept_params(stim, df)
    swept_txt = ", ".join(swept) if swept else "–"
    if len(swept_txt) > 72:
        swept_txt = swept_txt[:69] + "…"

    meta = [
        ("CPU Cores",           core_txt),
        ("Simulation Duration", dur_txt),
        ("Swept Parameters",    swept_txt),
    ]
    lx, rx = 0.04, 0.38
    for i, (lbl, val) in enumerate(meta):
        y = 0.885 - i * 0.030
        ax.text(lx, y, lbl + ":", ha="left", va="top", fontsize=8.5, color=DGRAY)
        ax.text(rx, y, val,         ha="left", va="top", fontsize=8.5,
                color="black", weight="bold")

    ax.axhline(0.772, xmin=0.0, xmax=1.0, color=MGRAY, linewidth=0.7)

    # ── Statistics ───────────────────────────────────────────────────────────
    total  = len(df)
    bad    = int((df["sim_error"] != "None").sum())
    valid  = total - bad
    passed = int(df["global_pass"].sum()) if total else 0
    yld    = passed / total * 100 if total else 0.0
    yld_color = GREEN if yld >= 99 else AMBER if yld >= 80 else RED

    # Yield badge (left side)
    badge = mpatches.FancyBboxPatch(
        (0.01, 0.62), 0.44, 0.135,
        boxstyle="round,pad=0.01", linewidth=1.4,
        edgecolor=yld_color, facecolor="white",
        transform=ax.transData, clip_on=False,
    )
    ax.add_patch(badge)
    ax.text(0.23, 0.710, f"{yld:.1f}%",
            ha="center", va="center", fontsize=28, weight="bold", color=yld_color)
    ax.text(0.23, 0.626, "Global Yield",
            ha="center", va="bottom", fontsize=9.5, color=DGRAY)

    # Run counts (right side of badge row)
    stats_items = [
        ("Total Iterations",  f"{total}"),
        ("Simulator Crashes", f"{bad}"),
        ("Valid Runs",        f"{valid}"),
        ("Passing Runs",      f"{passed}"),
    ]
    for i, (lbl, val) in enumerate(stats_items):
        y = 0.748 - i * 0.034
        ax.text(0.50, y, lbl + ":", ha="left", va="center", fontsize=9.5, color=DGRAY)
        ax.text(0.88, y, val,         ha="right", va="center", fontsize=9.5,
                weight="bold", color="black")

    ax.axhline(0.606, xmin=0.0, xmax=1.0, color=MGRAY, linewidth=0.7)

    # ── Measurement summary text ──────────────────────────────────────────────
    n_pass = sum(1 for r in rows if r["passed"])
    n_fail = len(rows) - n_pass

    ax.text(0.0, 0.588, "Measurement Results Summary",
            ha="left", va="top", fontsize=13, weight="bold", color=BLUE)
    ax.text(0.0, 0.549, f"Measurements evaluated: {len(rows)}",
            ha="left", va="top", fontsize=9.5, color=DGRAY)
    ax.text(0.0, 0.517, f"PASS: {n_pass}",
            ha="left", va="top", fontsize=9.5, weight="bold", color=GREEN)
    ax.text(0.145, 0.517, f"FAIL: {n_fail}",
            ha="left", va="top", fontsize=9.5, weight="bold",
            color=RED if n_fail > 0 else DGRAY)

    if n_fail > 0:
        failing  = [r["name"] for r in rows if not r["passed"]]
        wrapped  = textwrap.fill("Failing: " + ", ".join(failing), width=78)
        ax.text(0.0, 0.488, wrapped,
                ha="left", va="top", fontsize=8.5, color=RED)

    pdf.savefig(fig)
    plt.close(fig)


# ── Section 2: Measurements table ─────────────────────────────────────────────

def _add_table(pdf: PdfPages, rows: list, valid_df: pd.DataFrame, stim):
    if not rows:
        return

    HEADERS   = ["Parameter", "Sim Min", "Sim Typ", "Sim Max",
                 "Spec Min", "Spec Max", "Cpk", "Status"]
    # Fractional column widths (sum ≈ 0.84 → centred with margins)
    COL_W     = [0.20, 0.09, 0.09, 0.09, 0.09, 0.09, 0.08, 0.09]
    TABLE_W   = sum(COL_W)                       # ~0.83
    X0        = (1.0 - TABLE_W) / 2.0            # left edge of table
    ROWS_PP   = 16
    ROW_H     = 0.82 / (ROWS_PP + 1.5)
    pages     = math.ceil(len(rows) / ROWS_PP)

    for pg in range(pages):
        chunk = rows[pg * ROWS_PP: (pg + 1) * ROWS_PP]
        fig = plt.figure(figsize=A4, facecolor="white")
        _page_header(fig, f"Measurements  ({pg + 1} / {pages})")

        ax = fig.add_axes([ML, MB, 1 - 2 * ML, 0.885])
        ax.axis("off")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        fig.text(0.5, 0.922, "Measurement Results Summary",
                 ha="center", va="center", fontsize=13, weight="bold", color=DGRAY)

        hdr_y = 0.94

        # Header row
        x = X0
        for txt, w in zip(HEADERS, COL_W):
            ax.add_patch(mpatches.FancyBboxPatch(
                (x, hdr_y - ROW_H * 0.5), w - 0.002, ROW_H,
                boxstyle="square,pad=0", facecolor=BLUE,
                edgecolor="white", linewidth=0.6,
                clip_on=False, transform=ax.transData,
            ))
            ax.text(x + w / 2, hdr_y, txt,
                    ha="center", va="center", fontsize=8.5,
                    color="white", weight="bold")
            x += w

        # Data rows
        for ri, row in enumerate(chunk):
            y     = hdr_y - ROW_H * (ri + 1)
            even  = ri % 2 == 0

            cells = [
                row["name"],
                _fmt(row["sim_min"]), _fmt(row["sim_typ"]), _fmt(row["sim_max"]),
                _fmt(row["spec_lo"]), _fmt(row["spec_hi"]),
                _fmt(row["cpk"]),
                "PASS" if row["passed"] else "FAIL",
            ]
            row_bg = LGRAY if even else "white"

            x = X0
            for ci, (txt, w) in enumerate(zip(cells, COL_W)):
                if ci == 6:
                    fc = _cpk_cell_bg(row["cpk"])
                elif ci == 7:
                    fc = LGREEN if row["passed"] else LRED
                else:
                    fc = row_bg

                ax.add_patch(mpatches.FancyBboxPatch(
                    (x, y - ROW_H * 0.5), w - 0.002, ROW_H,
                    boxstyle="square,pad=0", facecolor=fc,
                    edgecolor=MGRAY, linewidth=0.4,
                    clip_on=False, transform=ax.transData,
                ))

                tc     = DGRAY
                weight = "normal"
                ha_txt = "center"
                tx     = x + w / 2

                if ci == 0:
                    ha_txt = "left"
                    tx     = x + 0.006
                    weight = "bold"
                elif ci == 7:
                    tc     = GREEN if row["passed"] else RED
                    weight = "bold"

                ax.text(tx, y, txt, ha=ha_txt, va="center",
                        fontsize=8, color=tc, weight=weight)
                x += w

        if pg == 0:
            total_valid = len(valid_df)
            passed_valid = int(valid_df["global_pass"].sum()) if total_valid else 0
            if total_valid > 0 and passed_valid < total_valid:
                # Center pie chart between table bottom and page end.
                table_bottom_ax = hdr_y - ROW_H * len(chunk) - ROW_H * 0.5
                table_bottom_fig = MB + max(0.0, table_bottom_ax) * 0.885
                area_bottom = 0.03
                area_height = max(0.12, table_bottom_fig - area_bottom)
                pie_h = min(0.24, area_height * 0.86)
                pie_y = area_bottom + (area_height - pie_h) / 2.0
                try:
                    pie_ax = fig.add_axes([0.24, pie_y, 0.52, pie_h])
                    PlotManager.draw_adv_plot(
                        fig=fig,
                        ax_dummy=pie_ax,
                        canvas=_DummyCanvas(),
                        valid_df=valid_df,
                        current_stim=stim,
                        mode="Fail Breakdown (Pie Chart)",
                        x_col="-",
                        y_col="-",
                        target="-",
                        bg_color="white",
                    )
                    pie_ax.set_title("")
                except Exception:
                    pass
            else:
                fig.text(0.5, 0.12, "All runs passed specifications.",
                         ha="center", va="center", fontsize=12, color=GREEN, weight="bold")

        pdf.savefig(fig)
        plt.close(fig)


# ── Section 3: Histograms (2-up) ──────────────────────────────────────────────

def _draw_hist_ax(ax, data, param, lo, hi, cpk, passed):
    ax.set_facecolor("white")
    ax.grid(True, linestyle="--", alpha=0.40, color=MGRAY, zorder=0)

    counts, _, _ = ax.hist(
        data, bins="auto", density=True,
        color=BLUE, alpha=0.55, edgecolor="white", linewidth=0.4,
        zorder=2,
    )

    mu = sigma = float("nan")
    if len(data) > 2:
        try:
            mu, sigma = stats.norm.fit(data)
            xf = np.linspace(min(data), max(data), 300)
            yf = np.clip(stats.norm.pdf(xf, mu, sigma), 0, max(counts, default=1) * 1.6)
            ax.plot(xf, yf, color=BLUE, linewidth=2.0, zorder=3,
                    label=f"Gauss  (μ={mu:.4g}, σ={sigma:.4g})")
        except Exception:
            mu, sigma = data.mean(), data.std()
    else:
        mu, sigma = data.mean(), data.std()

    for val, lbl in [(lo, "Min Spec"), (hi, "Max Spec")]:
        if val is not None:
            ax.axvline(val, color=RED, linestyle="--", linewidth=1.8, zorder=4,
                       label=f"{lbl} ({_fmt(val)})")

    status_clr = GREEN if passed else RED
    info = (f"μ = {_fmt(mu)}\nσ = {_fmt(sigma)}\n"
            f"Cpk = {_fmt(cpk)}\n{'PASS' if passed else 'FAIL'}")
    ax.text(0.975, 0.975, info,
            ha="right", va="top", transform=ax.transAxes,
            fontsize=8, family="monospace", color=status_clr, weight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor=status_clr, linewidth=1.2, alpha=0.93),
            zorder=5)

    ax.set_title(param, fontsize=11, weight="bold", pad=6)
    ax.set_xlabel(param, fontsize=9, color=DGRAY)
    ax.set_ylabel("Density",         fontsize=9, color=DGRAY)
    ax.tick_params(colors=DGRAY, labelsize=8)
    for sp in ax.spines.values():
        sp.set_edgecolor(MGRAY)
    if ax.get_legend_handles_labels()[1]:
        ax.legend(fontsize=7.5, framealpha=0.9, loc="upper left")
    # Match GUI "fit" option behavior: zoom to simulated data range.
    data_min = min(data) if len(data) else 0.0
    data_max = max(data) if len(data) else 1.0
    pad = (data_max - data_min) * 0.05
    ax.set_xlim(data_min - (pad or 0.1), data_max + (pad or 0.1))


def _add_histograms(pdf: PdfPages, valid_df: pd.DataFrame, stim, rows_meta: list):
    meta = {r["name"]: r for r in rows_meta}
    params = [r["name"] for r in rows_meta if r["name"] in valid_df.columns]
    if not params:
        return

    pairs = [params[i:i + 2] for i in range(0, len(params), 2)]
    total = len(pairs)

    for pi, pair in enumerate(pairs):
        fig = plt.figure(figsize=A4, facecolor="white")
        _page_header(fig, f"Histograms  ({pi + 1} / {total})")
        fig.text(0.5, 0.925, "Measurement Distributions",
                 ha="center", va="center", fontsize=13, color=DGRAY, weight="bold")

        for si, p in enumerate(pair):
            m = meta.get(p)
            if m is None:
                continue
            data = valid_df[p].dropna()
            if data.empty:
                continue
            # Two balanced slots that avoid clipping and keep labels/legend readable.
            bottom = 0.56 - si * 0.43
            ax = fig.add_axes([ML + 0.015, bottom, 1 - 2 * (ML + 0.015), 0.29])
            _draw_hist_ax(ax, data, p,
                          m["spec_lo"], m["spec_hi"], m["cpk"], m["passed"])

        pdf.savefig(fig)
        plt.close(fig)


# ── Section 4: Correlation heatmap ────────────────────────────────────────────

def _add_correlation(pdf: PdfPages, valid_df: pd.DataFrame):
    numeric = valid_df.select_dtypes(include=[np.number]).columns.tolist()
    cols = [c for c in numeric
            if not c.endswith("_pass") and c != "global_pass"
            and valid_df[c].nunique() > 1]
    if len(cols) < 2:
        return

    corr = valid_df[cols].corr()
    n = len(cols)

    fig = plt.figure(figsize=A4, facecolor="white")
    fig.patch.set_facecolor("white")
    # Centered plotting block on the page.
    ax = fig.add_axes([0.20, 0.24, 0.60, 0.60])
    ax.set_facecolor("white")

    cax  = ax.matshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    cbar = fig.colorbar(cax, ax=ax, fraction=0.036, pad=0.04)
    cbar.ax.tick_params(labelsize=8)
    cbar.set_label("Pearson r", fontsize=9)

    fs = max(6, 10 - n // 3)
    for i in range(n):
        for j in range(n):
            v  = corr.iloc[i, j]
            fc = "black" if abs(v) < 0.6 else "white"
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=fs, color=fc)

    ticks = np.arange(n)
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)
    ax.set_xticklabels(cols, rotation=45, ha="right", rotation_mode="anchor", fontsize=9, color=DGRAY)
    ax.set_yticklabels(cols, fontsize=9, color=DGRAY)
    ax.tick_params(axis="x", labelbottom=True, bottom=True, labeltop=False, top=False, pad=4)
    ax.tick_params(axis="y", labelleft=True, left=True, labelright=False, right=False, pad=4)
    ax.xaxis.set_ticks_position("bottom")
    ax.set_title("Parameter Correlation Matrix", fontsize=13, pad=14, weight="bold")
    fig.text(0.5, 0.925, "Correlation Matrix",
             ha="center", va="center", fontsize=13, color=DGRAY, weight="bold")
    for sp in ax.spines.values():
        sp.set_edgecolor(MGRAY)

    pdf.savefig(fig)
    plt.close(fig)


# ── Public entry point ────────────────────────────────────────────────────────

def generate_pdf_report(df, stim, yaml_path, out_dir, sim_duration_sec=None):
    os.makedirs(out_dir, exist_ok=True)
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = os.path.join(out_dir, f"report_{ts}.pdf")

    prepared = _build_global_pass(df)
    valid_df = prepared[prepared["sim_error"] == "None"]
    rows     = _measurement_rows(valid_df, stim)

    with PdfPages(pdf_path) as pdf:
        _add_cover(pdf, prepared, yaml_path, rows, stim, sim_duration_sec=sim_duration_sec)
        _add_table(pdf, rows, valid_df, stim)
        _add_histograms(pdf, valid_df, stim, rows)
        _add_correlation(pdf, valid_df)

    return pdf_path
