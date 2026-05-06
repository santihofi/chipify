"""
pdf_export.py – Professional datasheet-style PDF report for Chipify.

Layout (A4 portrait throughout):
  1. Cover page      – title, yield badge, sim summary
  2. Measurements    – styled table, PASS/FAIL colour-coded, Cpk column
  3. Histograms      – 2 per page, white background, Gauss fit + spec lines
                       + per-plot annotation box (μ, σ, Cpk, Status)
  4. Correlation     – white-background heatmap
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

# ── Shared style constants ────────────────────────────────────────────────────
BLUE    = "#1a5fa8"
LBLUE   = "#d0e4f7"
GREEN   = "#1e7d3a"
LGREEN  = "#d6f0de"
RED     = "#b71c1c"
LRED    = "#fde8e8"
AMBER   = "#c67c00"
LGRAY   = "#f4f4f4"
MGRAY   = "#d0d0d0"
DGRAY   = "#555555"

A4      = (8.27, 11.69)          # inches

mpl.rcParams.update({
    "font.family":  "DejaVu Sans",
    "font.size":    9,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "axes.linewidth":     0.8,
})


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _cpk_color(cpk):
    if math.isnan(cpk):
        return DGRAY
    if cpk >= 1.33:
        return GREEN
    if cpk >= 1.0:
        return AMBER
    return RED


def _measurement_rows(valid_df: pd.DataFrame, stim):
    rows = []
    for test in stim.tests:
        for val_obj in test.value_lst:
            p = val_obj.name
            if p not in valid_df.columns:
                continue
            data = valid_df[p].dropna()
            sim_min = data.min() if not data.empty else float("nan")
            sim_typ = data.mean() if not data.empty else float("nan")
            sim_max = data.max() if not data.empty else float("nan")
            lo, hi  = _get_spec(val_obj)
            cpk     = _compute_cpk(data, lo, hi)
            pass_col = f"{p}_pass"
            passed  = pass_col in valid_df.columns and bool(valid_df[pass_col].all())
            rows.append({
                "name":    p,
                "sim_min": sim_min,
                "sim_typ": sim_typ,
                "sim_max": sim_max,
                "spec_lo": lo,
                "spec_hi": hi,
                "cpk":     cpk,
                "passed":  passed,
            })
    return rows


# ── Section: Cover page ───────────────────────────────────────────────────────

def _add_cover(pdf: PdfPages, df: pd.DataFrame, yaml_path, rows):
    fig = plt.figure(figsize=A4)
    fig.patch.set_facecolor("white")

    # Top colour bar
    bar = fig.add_axes([0, 0.935, 1, 0.065])
    bar.set_facecolor(BLUE)
    bar.axis("off")
    bar.text(0.5, 0.5, "Chipify Statistical Report",
             color="white", fontsize=18, weight="bold",
             ha="center", va="center", transform=bar.transAxes)

    ax = fig.add_axes([0, 0, 1, 0.935])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # Sub-title
    yaml_name = os.path.basename(yaml_path) if yaml_path else "Unknown"
    ax.text(0.5, 0.89, f"Datasheet:  {yaml_name}",
            ha="center", fontsize=11, color=DGRAY)
    ax.text(0.5, 0.862,
            f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ha="center", fontsize=9, color=MGRAY)

    # Divider
    ax.axhline(0.845, xmin=0.08, xmax=0.92, color=MGRAY, linewidth=0.8)

    # Statistics
    total  = len(df)
    bad    = int((df["sim_error"] != "None").sum())
    valid  = total - bad
    passed = int(df["global_pass"].sum()) if total else 0
    yld    = passed / total * 100 if total else 0.0

    yld_color = GREEN if yld >= 99 else AMBER if yld >= 80 else RED

    # Yield badge
    badge = mpatches.FancyBboxPatch((0.30, 0.71), 0.40, 0.115,
                                    boxstyle="round,pad=0.01",
                                    linewidth=1.2, edgecolor=yld_color,
                                    facecolor="white", transform=ax.transData, clip_on=False)
    ax.add_patch(badge)
    ax.text(0.50, 0.782, f"{yld:.1f}%",
            ha="center", va="center", fontsize=30, weight="bold", color=yld_color)
    ax.text(0.50, 0.718, "Global Yield",
            ha="center", va="bottom", fontsize=10, color=DGRAY)

    # Summary list
    col1_x, col2_x = 0.14, 0.56
    ys = [0.665, 0.640, 0.615, 0.590]
    labels = ["Total Iterations", "Simulator Crashes", "Valid Runs", "Passing Runs"]
    vals   = [f"{total}", f"{bad}", f"{valid}", f"{passed}"]
    for lab, val, y in zip(labels, vals, ys):
        ax.text(col1_x, y, lab, fontsize=10, color=DGRAY)
        ax.text(col1_x + 0.30, y, val, fontsize=10, weight="bold", color="black")

    # Failing params summary
    ax.axhline(0.568, xmin=0.08, xmax=0.92, color=MGRAY, linewidth=0.8)
    ax.text(0.08, 0.548, "Measurement Results Summary", fontsize=11,
            weight="bold", color=BLUE)

    n_pass  = sum(1 for r in rows if r["passed"])
    n_fail  = len(rows) - n_pass

    ax.text(col1_x, 0.520, f"Measurements evaluated: {len(rows)}", fontsize=10, color=DGRAY)
    ax.text(col1_x, 0.497, f"PASS: {n_pass}",
            fontsize=10, weight="bold", color=GREEN)
    ax.text(col1_x, 0.474, f"FAIL: {n_fail}",
            fontsize=10, weight="bold", color=RED if n_fail else DGRAY)

    if n_fail > 0:
        failing = [r["name"] for r in rows if not r["passed"]]
        fail_str = ", ".join(failing)
        wrapped  = textwrap.fill(fail_str, width=70)
        ax.text(col1_x, 0.449, f"Failing:  {wrapped}",
                fontsize=9, color=RED, va="top")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Section: Measurements table ───────────────────────────────────────────────

def _add_table(pdf: PdfPages, rows):
    if not rows:
        return

    headers = ["Parameter", "Sim Min", "Sim Typ", "Sim Max",
                "Spec Min", "Spec Max", "Cpk", "Status"]
    rows_per_page = 24
    pages = math.ceil(len(rows) / rows_per_page)
    col_widths = [0.22, 0.09, 0.09, 0.09, 0.09, 0.09, 0.08, 0.09]

    for pg in range(pages):
        chunk = rows[pg * rows_per_page: (pg + 1) * rows_per_page]
        fig   = plt.figure(figsize=A4)
        fig.patch.set_facecolor("white")

        # Header bar
        hbar = fig.add_axes([0, 0.935, 1, 0.065])
        hbar.set_facecolor(BLUE)
        hbar.axis("off")
        hbar.text(0.5, 0.5,
                  f"Measurements  ({pg + 1} / {pages})",
                  color="white", fontsize=13, weight="bold",
                  ha="center", va="center", transform=hbar.transAxes)

        ax = fig.add_axes([0.04, 0.04, 0.92, 0.88])
        ax.axis("off")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

        row_h  = 0.870 / (rows_per_page + 1.5)
        hdr_y  = 1.0 - row_h * 0.5

        # Draw header
        x = 0.0
        for txt, w in zip(headers, col_widths):
            rect = mpatches.FancyBboxPatch((x, hdr_y - row_h * 0.5), w - 0.003, row_h,
                                           boxstyle="square,pad=0",
                                           facecolor=BLUE, edgecolor="white",
                                           linewidth=0.5, clip_on=False,
                                           transform=ax.transData)
            ax.add_patch(rect)
            ax.text(x + w / 2, hdr_y, txt,
                    ha="center", va="center", fontsize=8.5,
                    color="white", weight="bold")
            x += w

        # Draw rows
        for ri, row in enumerate(chunk):
            y     = hdr_y - row_h * (ri + 1)
            bg    = LGREEN if row["passed"] else LRED if not row["passed"] else LGRAY
            even  = ri % 2 == 0
            rowbg = bg if (row["passed"] or not row["passed"]) else (LGRAY if even else "white")
            rowbg = bg  # always show pass/fail colour

            cells = [
                row["name"],
                _fmt(row["sim_min"]),
                _fmt(row["sim_typ"]),
                _fmt(row["sim_max"]),
                _fmt(row["spec_lo"]),
                _fmt(row["spec_hi"]),
                _fmt(row["cpk"]),
                "PASS" if row["passed"] else "FAIL",
            ]
            cell_colors = ["white"] * 6 + [_cpk_cell_bg(row["cpk"])] + [LGREEN if row["passed"] else LRED]

            x = 0.0
            for ci, (txt, w) in enumerate(zip(cells, col_widths)):
                fc = rowbg if ci not in (6, 7) else cell_colors[ci]
                rect = mpatches.FancyBboxPatch((x, y - row_h * 0.5), w - 0.003, row_h,
                                               boxstyle="square,pad=0",
                                               facecolor=fc,
                                               edgecolor=MGRAY, linewidth=0.4,
                                               clip_on=False, transform=ax.transData)
                ax.add_patch(rect)
                tc = DGRAY if ci != 7 else (GREEN if row["passed"] else RED)
                weight = "bold" if ci in (0, 7) else "normal"
                ha = "left" if ci == 0 else "center"
                tx = x + 0.005 if ci == 0 else x + w / 2
                ax.text(tx, y, txt, ha=ha, va="center",
                        fontsize=8, color=tc, weight=weight)
                x += w

        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def _cpk_cell_bg(cpk):
    if math.isnan(cpk):
        return LGRAY
    if cpk >= 1.33:
        return LGREEN
    if cpk >= 1.0:
        return "#fff3cd"  # amber-light
    return LRED


# ── Section: Histograms (2-up per page) ───────────────────────────────────────

def _draw_hist_ax(ax, data, param, lo, hi, cpk, passed):
    """Render one print-quality histogram onto ax (white background)."""
    ax.set_facecolor("white")
    ax.grid(True, linestyle="--", alpha=0.45, color=MGRAY, zorder=0)

    # Histogram
    bar_color = BLUE
    counts, bins, _ = ax.hist(
        data, bins="auto", density=True,
        color=bar_color, alpha=0.55,
        edgecolor="white", linewidth=0.4,
        zorder=2, label=param,
    )

    # Gauss fit
    if len(data) > 2:
        try:
            mu, sigma = stats.norm.fit(data)
            x_fit = np.linspace(min(data), max(data), 300)
            y_fit = stats.norm.pdf(x_fit, mu, sigma)
            max_h = max(counts) if len(counts) else 1
            y_fit = np.clip(y_fit, 0, max_h * 1.6)
            ax.plot(x_fit, y_fit, color=BLUE, linewidth=2.0, zorder=3,
                    label=f"Gauss  (μ={mu:.4g}, σ={sigma:.4g})")
        except Exception:
            mu, sigma = data.mean(), data.std()
    else:
        mu, sigma = data.mean(), data.std()

    # Spec lines
    for val, label, clr in [(lo, "Min Spec", RED), (hi, "Max Spec", RED)]:
        if val is not None:
            ax.axvline(val, color=clr, linestyle="--", linewidth=1.8,
                       zorder=4, label=f"{label} ({_fmt(val)})")

    # Annotation box (top-right)
    status_clr = GREEN if passed else RED
    cpk_str    = _fmt(cpk)
    info = (
        f"μ = {_fmt(mu)}\n"
        f"σ = {_fmt(sigma)}\n"
        f"Cpk = {cpk_str}\n"
        f"{'PASS' if passed else 'FAIL'}"
    )
    ax.text(0.975, 0.975, info,
            ha="right", va="top", transform=ax.transAxes,
            fontsize=8, family="monospace",
            color=status_clr, weight="bold",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor=status_clr, linewidth=1.2, alpha=0.92),
            zorder=5)

    # Cosmetics
    ax.set_title(param, fontsize=11, weight="bold", pad=6)
    ax.set_xlabel("Simulated Value", fontsize=9, color=DGRAY)
    ax.set_ylabel("Density",         fontsize=9, color=DGRAY)
    ax.tick_params(colors=DGRAY, labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor(MGRAY)
    ax.legend(fontsize=7.5, framealpha=0.9, loc="upper left")


def _add_histograms(pdf: PdfPages, valid_df: pd.DataFrame, stim, rows_meta):
    """2-up histogram pages."""
    meta_by_name = {r["name"]: r for r in rows_meta}
    params = [r["name"] for r in rows_meta if r["name"] in valid_df.columns]
    if not params:
        return

    pairs = [params[i:i + 2] for i in range(0, len(params), 2)]
    total_pages = len(pairs)

    for pi, pair in enumerate(pairs):
        fig = plt.figure(figsize=A4)
        fig.patch.set_facecolor("white")

        # Top bar
        hbar = fig.add_axes([0, 0.935, 1, 0.065])
        hbar.set_facecolor(BLUE)
        hbar.axis("off")
        hbar.text(0.5, 0.5,
                  f"Histograms  ({pi + 1} / {total_pages})",
                  color="white", fontsize=13, weight="bold",
                  ha="center", va="center", transform=hbar.transAxes)

        n = len(pair)
        for si, p in enumerate(pair):
            meta = meta_by_name.get(p)
            if meta is None:
                continue
            data = valid_df[p].dropna()
            if data.empty:
                continue

            ax = fig.add_axes([0.10, 0.53 - si * 0.48, 0.84, 0.38])
            _draw_hist_ax(ax, data, p,
                          meta["spec_lo"], meta["spec_hi"],
                          meta["cpk"],     meta["passed"])

        fig.tight_layout(rect=[0, 0, 1, 0.93])
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


# ── Section: Correlation heatmap ──────────────────────────────────────────────

def _add_correlation(pdf: PdfPages, valid_df: pd.DataFrame):
    numeric = valid_df.select_dtypes(include=[np.number]).columns.tolist()
    cols    = [c for c in numeric if not c.endswith("_pass") and c not in ("global_pass",)
               and valid_df[c].nunique() > 1]

    if len(cols) < 2:
        return

    corr = valid_df[cols].corr()
    n    = len(cols)
    sz   = max(6.0, min(10.0, n * 0.6))

    fig, ax = plt.subplots(figsize=(sz, sz * 0.85 + 1))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    cax = ax.matshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    cbar = fig.colorbar(cax, ax=ax, fraction=0.036, pad=0.04)
    cbar.ax.tick_params(labelsize=8)
    cbar.set_label("Pearson r", fontsize=9)

    for i in range(n):
        for j in range(n):
            v = corr.iloc[i, j]
            fc = "black" if abs(v) < 0.6 else "white"
            ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                    fontsize=max(6, 10 - n // 3), color=fc)

    ticks = range(n)
    ax.set_xticks(list(ticks))
    ax.set_yticks(list(ticks))
    ax.set_xticklabels(cols, rotation=45, ha="left", fontsize=8)
    ax.set_yticklabels(cols, fontsize=8)
    ax.xaxis.set_ticks_position("bottom")
    ax.set_title("Parameter Correlation Matrix", fontsize=13, pad=14, weight="bold")

    for spine in ax.spines.values():
        spine.set_edgecolor(MGRAY)

    fig.tight_layout()
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ── Public entry point ────────────────────────────────────────────────────────

def generate_pdf_report(df, stim, yaml_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = os.path.join(out_dir, f"report_{ts}.pdf")

    prepared = _build_global_pass(df)
    valid_df = prepared[prepared["sim_error"] == "None"]
    rows     = _measurement_rows(valid_df, stim)

    with PdfPages(pdf_path) as pdf:
        _add_cover(pdf, prepared, yaml_path, rows)
        _add_table(pdf, rows)
        _add_histograms(pdf, valid_df, stim, rows)
        _add_correlation(pdf, valid_df)

    return pdf_path
