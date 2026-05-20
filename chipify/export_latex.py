import glob
import os
import re

import numpy as np
import pandas as pd


_RE_NON_ID = re.compile(r"[^A-Za-z0-9]+")


def _safe_col(text: str) -> str:
    """Sanitise a string for use as a CSV column name / LaTeX \\foreach token."""
    cleaned = _RE_NON_ID.sub("_", str(text)).strip("_")
    return cleaned or "x"


def _collect_run_files(adir: str, run_ids: list[str]) -> list[tuple[str, str]]:
    """Return ``[(run_id, csv_path), …]`` for the given run IDs."""
    if not adir or not os.path.isdir(adir) or not run_ids:
        return []
    run_id_set = set(run_ids)
    matched: list[tuple[str, str]] = []
    for fname in glob.glob(os.path.join(adir, "run_*.csv")):
        rid = os.path.basename(fname)[4:].split("__", 1)[0]
        if rid in run_id_set:
            matched.append((rid, fname))
    matched.sort(key=lambda rf: rf[0])
    return matched


def _apply_equations(df: pd.DataFrame, equations: list | None) -> pd.DataFrame:
    if not equations:
        return df
    from chipify.expression import default_evaluator
    for eq in equations:
        name = (eq.get("name") or "").strip()
        expr = (eq.get("expr") or "").strip()
        if name and expr:
            try:
                df = default_evaluator.evaluate_dataframe_column(df, name, expr)
            except Exception:
                pass
    return df


def _time_autoscale(x: np.ndarray) -> tuple[float, str]:
    """Mirror PlotManager._draw_xy_overlay's time-axis autoscaling.

    Returns ``(scale, unit_suffix)`` — divide-by factor not used; data is
    multiplied by *scale* before going to the CSV, and the axis label gets
    ``"Time ({unit_suffix})"``.
    """
    t_max = float(np.nanmax(np.abs(x))) if x.size else 0.0
    if t_max >= 1.0:
        return 1.0, "s"
    if t_max >= 1e-3:
        return 1e3, "ms"
    if t_max >= 1e-6:
        return 1e6, r"\textmu s"
    return 1e9, "ns"


def _build_xy_table(
    run_files: list[tuple[str, str]],
    signals: list[str],
    x_col: str,
    *,
    y_columns_for_signal,
    equations: list | None = None,
) -> tuple[pd.DataFrame, list[tuple[str, str, str, str]]]:
    """
    Load each per-run CSV and assemble a wide LaTeX-ready DataFrame.

    *y_columns_for_signal(df, sig)* returns a list of ``(suffix, series)`` to
    emit for that signal — transient/DC supply one (``("", df[sig])``), Bode
    supplies two (``("mag", db_series), ("phase", phase_series)``).

    Returns ``(wide_df, series_keys)`` where each entry of *series_keys* is
    ``(run_id, base_signal, suffix, column_name)``. The base signal is the
    name the user picked (without mag/phase) so chipify-style colouring can
    group mag+phase of the same (rid, sig) under one colour.
    """
    cols: dict[str, np.ndarray] = {}
    series_keys: list[tuple[str, str, str, str]] = []
    x_vec: np.ndarray | None = None

    for rid, fpath in run_files:
        try:
            df = pd.read_csv(fpath)
        except Exception:
            continue
        if x_col not in df.columns:
            continue
        df = _apply_equations(df, equations)

        x = df[x_col].to_numpy()
        if x_vec is None:
            x_vec = x
            cols[x_col] = x_vec

        for sig in signals:
            for suffix, series in y_columns_for_signal(df, sig):
                if series is None:
                    continue
                rid_tok = _safe_col(rid)
                sig_tok = _safe_col(sig)
                suffix_tok = f"_{suffix}" if suffix else ""
                col_name = f"r_{rid_tok}_{sig_tok}{suffix_tok}"
                cols[col_name] = np.asarray(series, dtype=float)
                series_keys.append((rid, sig, suffix, col_name))

    if x_vec is None:
        return pd.DataFrame(), []

    # NaN-pad to the longest column so all series fit in one CSV.
    max_len = max(len(v) for v in cols.values())
    padded: dict[str, np.ndarray] = {}
    for name, vec in cols.items():
        if len(vec) < max_len:
            pad = np.full(max_len - len(vec), np.nan)
            padded[name] = np.concatenate([vec, pad])
        else:
            padded[name] = vec
    return pd.DataFrame(padded), series_keys


# ── chipify-styled colour / alpha plumbing ────────────────────────────────────
# Hard-coded palettes so export doesn't depend on matplotlib at import time.
# Values pulled from matplotlib 3.x: matplotlib.cm.viridis sampled at 11 stops
# and matplotlib.cm.tab10 at its 10 base colours.

_VIRIDIS_STOPS: list[tuple[float, float, float]] = [
    (0.267004, 0.004874, 0.329415),  # 0.0
    (0.282327, 0.094955, 0.417331),  # 0.1
    (0.253935, 0.265254, 0.529983),  # 0.2
    (0.206756, 0.371758, 0.553117),  # 0.3
    (0.163625, 0.471133, 0.558148),  # 0.4
    (0.127568, 0.566949, 0.550556),  # 0.5
    (0.134692, 0.658636, 0.517649),  # 0.6
    (0.266941, 0.748751, 0.440573),  # 0.7
    (0.477504, 0.821444, 0.318195),  # 0.8
    (0.741388, 0.873449, 0.149561),  # 0.9
    (0.993248, 0.906157, 0.143936),  # 1.0
]

_TAB10: list[tuple[float, float, float]] = [
    (0.121569, 0.466667, 0.705882),
    (1.000000, 0.498039, 0.054902),
    (0.172549, 0.627451, 0.172549),
    (0.839216, 0.152941, 0.156863),
    (0.580392, 0.403922, 0.741176),
    (0.549020, 0.337255, 0.294118),
    (0.890196, 0.466667, 0.760784),
    (0.498039, 0.498039, 0.498039),
    (0.737255, 0.741176, 0.133333),
    (0.090196, 0.745098, 0.811765),
]


def _viridis(t: float) -> tuple[float, float, float]:
    """Linearly interpolated viridis sample, t in [0, 1]."""
    t = max(0.0, min(1.0, float(t)))
    pos = t * (len(_VIRIDIS_STOPS) - 1)
    i = int(pos)
    if i >= len(_VIRIDIS_STOPS) - 1:
        return _VIRIDIS_STOPS[-1]
    frac = pos - i
    r0, g0, b0 = _VIRIDIS_STOPS[i]
    r1, g1, b1 = _VIRIDIS_STOPS[i + 1]
    return (r0 + frac * (r1 - r0),
            g0 + frac * (g1 - g0),
            b0 + frac * (b1 - b0))


def _chipify_curve_styles(
    series_keys: list[tuple[str, str, str, str]],
) -> tuple[list[tuple[str, str]], dict[tuple[str, str], str], float, bool,
           list[str]]:
    """Compute per-curve colours that mirror ``PlotManager._draw_xy_overlay``.

    Rules (lifted from plot_manager.py):
      • Single-signal mode (one unique base signal): colour by run index using
        viridis between 0.1 and 0.9. Legend gets a single "<sig> (color = run
        index)" entry.
      • Multi-signal mode: colour by signal using tab10; every run of a signal
        shares the colour. Legend gets one entry per signal.
      • Alpha auto-fade: 1.0 if ≤50 curves, else max(0.05, 50/N).

    Returns ``(color_defs, curve_color, alpha, single_mode, legend_lines)``:
      color_defs   – ``[(name, "r,g,b"), …]`` to emit as \\definecolor blocks.
      curve_color  – ``{(rid, base_sig): color_name}`` for each curve.
      alpha        – curve opacity to use.
      single_mode  – True if the legend should show "color = run index".
      legend_lines – the lines to splice in front of the data plots.
    """
    base_signals: list[str] = []
    seen_sigs: set[str] = set()
    runs_in_order: list[str] = []
    seen_runs: set[str] = set()
    for rid, base_sig, _suffix, _col in series_keys:
        if base_sig not in seen_sigs:
            seen_sigs.add(base_sig)
            base_signals.append(base_sig)
        if rid not in seen_runs:
            seen_runs.add(rid)
            runs_in_order.append(rid)

    n_runs = max(1, len(runs_in_order))
    # A "curve" is one (rid, base_sig) pair — mag+phase share it for Bode.
    n_curves = len({(rid, sig) for rid, sig, _s, _c in series_keys})
    alpha = 1.0 if n_curves <= 50 else max(0.05, 50.0 / n_curves)
    single_mode = len(base_signals) == 1

    color_defs: list[tuple[str, str]] = []
    curve_color: dict[tuple[str, str], str] = {}

    def _rgb_str(r: float, g: float, b: float) -> str:
        return f"{r:.4f},{g:.4f},{b:.4f}"

    if single_mode:
        ts = np.linspace(0.1, 0.9, n_runs)
        run_color_name: dict[str, str] = {}
        for i, rid in enumerate(runs_in_order):
            r, g, b = _viridis(float(ts[i]))
            name = f"cfRun{i}"
            color_defs.append((name, _rgb_str(r, g, b)))
            run_color_name[rid] = name
        for rid, sig, _suffix, _col in series_keys:
            curve_color[(rid, sig)] = run_color_name[rid]
        mid = run_color_name[runs_in_order[n_runs // 2]]
        sig_safe = base_signals[0].replace("_", r"\_")
        legend_lines = [
            f"    \\addlegendimage{{color={mid}, line width=1pt}}",
            f"    \\addlegendentry{{{sig_safe}  (color = run index)}}",
        ]
    else:
        sig_color_name: dict[str, str] = {}
        legend_lines = []
        for i, sig in enumerate(base_signals):
            r, g, b = _TAB10[i % len(_TAB10)]
            name = f"cfSig{i}"
            color_defs.append((name, _rgb_str(r, g, b)))
            sig_color_name[sig] = name
            sig_safe = sig.replace("_", r"\_")
            legend_lines.append(
                f"    \\addlegendimage{{color={name}, line width=1pt}}"
            )
            legend_lines.append(f"    \\addlegendentry{{{sig_safe}}}")
        for rid, sig, _suffix, _col in series_keys:
            curve_color[(rid, sig)] = sig_color_name[sig]

    return color_defs, curve_color, alpha, single_mode, legend_lines


def _emit_color_defs(color_defs: list[tuple[str, str]]) -> str:
    """Format \\definecolor blocks for the colour table at the top of the .tex."""
    if not color_defs:
        return ""
    return "\n".join(
        f"\\definecolor{{{name}}}{{rgb}}{{{rgb}}}" for name, rgb in color_defs
    ) + "\n"


def _write_overlay_tex(
    output_dir: str,
    name: str,
    csv_filename: str,
    series_keys: list[tuple[str, str, str, str]],
    *,
    x_col: str,
    xlabel: str,
    ylabel: str,
    xmode: str = "normal",
    title_prefix: str = "Overlay",
) -> str:
    """Emit a single-axis pgfplots overlay styled like chipify's GUI plot."""
    tex_filename = f"{name}_plot.tex"
    color_defs, curve_color, alpha, _single, legend_lines = \
        _chipify_curve_styles(series_keys)

    n_runs = len({rid for rid, _s, _u, _c in series_keys})
    n_sigs = len({sig for _r, sig, _u, _c in series_keys})
    title = f"{title_prefix} \\textemdash{{}} {n_runs} run(s) {n_sigs} signal(s)"
    if n_sigs > 1:
        title = (f"{title_prefix} \\textemdash{{}} {n_runs} run(s) "
                 f"$\\times$ {n_sigs} signal(s)")

    addplots: list[str] = []
    for rid, sig, _suffix, col in series_keys:
        cname = curve_color.get((rid, sig), "black")
        addplots.append(
            f"    \\addplot+ [color={cname}, no marks,"
            f" line width=0.6pt, opacity={alpha:.3f}]"
            f" table [x={x_col}, y={col}] {{\\datatable}};"
        )

    plot_block = "\n".join(legend_lines + addplots)
    xmode_line = f"    xmode={xmode},\n" if xmode and xmode != "normal" else ""
    color_block = _emit_color_defs(color_defs)

    tex_content = (
        f"% {title_prefix}\n"
        f"\\pgfplotstableread[col sep=comma]{{{csv_filename}}}\\datatable\n\n"
        f"{color_block}"
        "\\begin{center}\n"
        "\\begin{tikzpicture}\n"
        "\\begin{axis}[\n"
        f"    title={{{title}}},\n"
        f"    xlabel={{{xlabel}}},\n"
        f"    ylabel={{{ylabel}}},\n"
        f"{xmode_line}"
        "    scale only axis, width=10cm, height=6cm,\n"
        "    grid=major, grid style={solid, gray!20},\n"
        "    scaled x ticks=false, scaled y ticks=false,\n"
        "    x tick label style={/pgf/number format/.cd, fixed, precision=3},\n"
        "    y tick label style={/pgf/number format/.cd, fixed, precision=4},\n"
        "    legend cell align={left},\n"
        "    legend style={\n"
        "        align=left, fill=white, draw=black!30, rounded corners=1pt,\n"
        "        at={(0.97,0.97)}, anchor=north east, font=\\small\n"
        "    },\n"
        "    axis line style={thick}, tick style={thick, black}\n"
        "]\n"
        f"{plot_block}\n"
        "\\end{axis}\n"
        "\\end{tikzpicture}\n"
        "\\end{center}\n"
    )

    out_path = os.path.join(output_dir, tex_filename)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(tex_content)
    return out_path


# ── Analysis-overlay LaTeX export entry points ────────────────────────────────

def generate_transient_latex_export(
    out_dir: str,
    name: str,
    tran_dir: str,
    run_ids: list[str],
    signals: list[str],
    equations: list | None = None,
) -> tuple[str, str]:
    """Export a transient overlay (time vs signal) as CSV + pgfplots .tex.

    Returns ``(csv_path, tex_path)``. Raises ``ValueError`` if no data could be
    collected (no matching runs, missing 'time' column, etc.).
    """
    os.makedirs(out_dir, exist_ok=True)
    run_files = _collect_run_files(tran_dir, run_ids)

    def y_for(df, sig):
        if sig in df.columns:
            return [("", df[sig])]
        return []

    table, series_keys = _build_xy_table(
        run_files, signals, x_col="time",
        y_columns_for_signal=y_for, equations=equations,
    )
    if table.empty or not series_keys:
        raise ValueError("No transient data available for the current selection.")

    # Auto-scale time to a readable unit (s / ms / µs / ns), matching the GUI.
    t_scale, t_unit = _time_autoscale(table["time"].to_numpy())
    if t_scale != 1.0:
        table["time"] = table["time"] * t_scale

    csv_filename = f"{name}_plot.csv"
    csv_path = os.path.join(out_dir, csv_filename)
    table.to_csv(csv_path, index=False)
    tex_path = _write_overlay_tex(
        out_dir, name, csv_filename, series_keys,
        x_col="time", xlabel=f"Time ({t_unit})", ylabel="Signal Value",
        title_prefix="Transient Overlay",
    )
    return csv_path, tex_path


def generate_dc_sweep_latex_export(
    out_dir: str,
    name: str,
    dc_dir: str,
    run_ids: list[str],
    signals: list[str],
    equations: list | None = None,
) -> tuple[str, str]:
    """Export a DC sweep overlay (sweep vs signal) as CSV + pgfplots .tex."""
    os.makedirs(out_dir, exist_ok=True)
    run_files = _collect_run_files(dc_dir, run_ids)

    def y_for(df, sig):
        if sig in df.columns:
            return [("", df[sig])]
        return []

    table, series_keys = _build_xy_table(
        run_files, signals, x_col="sweep",
        y_columns_for_signal=y_for, equations=equations,
    )
    if table.empty or not series_keys:
        raise ValueError("No DC sweep data available for the current selection.")

    csv_filename = f"{name}_plot.csv"
    csv_path = os.path.join(out_dir, csv_filename)
    table.to_csv(csv_path, index=False)
    tex_path = _write_overlay_tex(
        out_dir, name, csv_filename, series_keys,
        x_col="sweep", xlabel="Sweep", ylabel="Signal Value",
        title_prefix="DC Sweep Overlay",
    )
    return csv_path, tex_path


def generate_bode_latex_export(
    out_dir: str,
    name: str,
    ac_dir: str,
    run_ids: list[str],
    signals: list[str],
    equations: list | None = None,
) -> tuple[str, str]:
    """Export a Bode overlay (frequency vs mag-in-dB and phase) as CSV + .tex.

    Uses pgfplots' ``groupplots`` library to stack magnitude (dB) above phase
    (degrees) with a shared logarithmic frequency axis.
    """
    os.makedirs(out_dir, exist_ok=True)
    run_files = _collect_run_files(ac_dir, run_ids)

    def y_for(df, sig):
        mag_col = f"{sig}_mag"
        ph_col = f"{sig}_phase"
        out: list[tuple[str, pd.Series]] = []
        if mag_col in df.columns:
            mag = np.maximum(np.abs(df[mag_col].to_numpy()), 1e-30)
            out.append(("mag", pd.Series(20.0 * np.log10(mag))))
        if ph_col in df.columns:
            out.append(("phase", df[ph_col]))
        return out

    table, series_keys = _build_xy_table(
        run_files, signals, x_col="frequency",
        y_columns_for_signal=y_for, equations=equations,
    )
    if table.empty or not series_keys:
        raise ValueError("No AC/Bode data available for the current selection.")

    csv_filename = f"{name}_plot.csv"
    csv_path = os.path.join(out_dir, csv_filename)
    table.to_csv(csv_path, index=False)

    color_defs, curve_color, alpha, _single, legend_lines = \
        _chipify_curve_styles(series_keys)

    mag_keys = [k for k in series_keys if k[2] == "mag"]
    phase_keys = [k for k in series_keys if k[2] == "phase"]

    def _plots_block(keys: list[tuple[str, str, str, str]]) -> str:
        rows: list[str] = []
        for rid, sig, _suffix, col in keys:
            cname = curve_color.get((rid, sig), "black")
            rows.append(
                f"        \\addplot+ [color={cname}, no marks,"
                f" line width=0.5pt, opacity={alpha:.3f}]"
                f" table [x=frequency, y={col}] {{\\datatable}};"
            )
        return "\n".join(rows) if rows else ""

    # Show the legend on the magnitude subplot only (it's the same colour
    # mapping for the phase plot below).
    legend_block = "\n".join("    " + ln.lstrip() for ln in legend_lines)

    n_runs = len({rid for rid, _s, _u, _c in series_keys})
    n_sigs = len({sig for _r, sig, _u, _c in series_keys})
    title = f"Bode Plot \\textemdash{{}} {n_runs} run(s) {n_sigs} signal(s)"
    if n_sigs > 1:
        title = (f"Bode Plot \\textemdash{{}} {n_runs} run(s) "
                 f"$\\times$ {n_sigs} signal(s)")

    tex_filename = f"{name}_plot.tex"
    color_block = _emit_color_defs(color_defs)
    tex_content = (
        f"% Bode plot for {name}\n"
        "% Requires: \\usepgfplotslibrary{groupplots}\n"
        f"\\pgfplotstableread[col sep=comma]{{{csv_filename}}}\\datatable\n\n"
        f"{color_block}"
        "\\begin{center}\n"
        "\\begin{tikzpicture}\n"
        "\\begin{groupplot}[\n"
        "    group style={\n"
        "        group size=1 by 2, vertical sep=12pt,\n"
        "        xticklabels at=edge bottom,\n"
        "    },\n"
        "    scale only axis, width=10cm, height=4cm,\n"
        "    xmode=log, grid=both, grid style={solid, gray!20},\n"
        "    scaled y ticks=false,\n"
        "    y tick label style={/pgf/number format/.cd, fixed, precision=2},\n"
        "    legend cell align={left},\n"
        "    legend style={\n"
        "        align=left, fill=white, draw=black!30, rounded corners=1pt,\n"
        "        at={(0.97,0.97)}, anchor=north east, font=\\small\n"
        "    },\n"
        "    axis line style={thick}, tick style={thick, black}\n"
        "]\n"
        f"    \\nextgroupplot[title={{{title}}}, ylabel={{Magnitude (dB)}}]\n"
        f"{legend_block}\n"
        f"{_plots_block(mag_keys)}\n"
        "    \\nextgroupplot[ylabel={Phase ($^\\circ$)}, xlabel={Frequency (Hz)}]\n"
        f"{_plots_block(phase_keys)}\n"
        "\\end{groupplot}\n"
        "\\end{tikzpicture}\n"
        "\\end{center}\n"
    )
    tex_path = os.path.join(out_dir, tex_filename)
    with open(tex_path, "w", encoding="utf-8") as fh:
        fh.write(tex_content)
    return csv_path, tex_path




def generate_latex_export(param_name, data_series, dist_type, bins, output_dir):
    import scipy.stats as stats  # only needed for the histogram fit path
    data = data_series.dropna().values
    if len(data) == 0:
        return

    # 1. Histogramm berechnen
    # Für 'ybar interval' in PGFPlots brauchen wir die X-Edges, nicht die Center!
    counts, edges = np.histogram(data, bins=bins, density=True)
    
    # X und Y müssen bei 'ybar interval' gleich lang sein. Das letzte Y wird ignoriert.
    x_hist = edges
    y_hist = np.append(counts, counts[-1] if len(counts)>0 else 0)

    # 2. Fit-Kurve und Parameter berechnen
    fit_x = None
    fit_y = None
    fit_params = {}
    fit_legend_latex = ""

    if dist_type != "None" and len(data) > 1:
        fit_x = np.linspace(min(data), max(data), 100)
        try:
            if dist_type == "Gauss (Normal)":
                mu, std = stats.norm.fit(data)
                fit_y = stats.norm.pdf(fit_x, mu, std)
                fit_params = {'mu': mu, 'sigma': std}
                fit_legend_latex = r"Gaussian fit \\ $\mu=\formatnum{3}{\muVal}$ \\ $\sigma=\formatnum{3}{\sigmaVal}$"
                
            elif dist_type == "KDE (Smoothed)":
                kde = stats.gaussian_kde(data)
                fit_y = kde(fit_x)
                fit_legend_latex = "KDE Smooth"
                
            elif dist_type == "Uniform":
                loc, scale = stats.uniform.fit(data)
                fit_y = stats.uniform.pdf(fit_x, loc, scale)
                fit_params = {'loc': loc, 'scale': scale}
                fit_legend_latex = r"Uniform fit \\ $loc=\formatnum{3}{\locVal}$ \\ $scale=\formatnum{3}{\scaleVal}$"
                
            elif dist_type == "Log-Normal":
                shape, loc, scale = stats.lognorm.fit(data)
                fit_y = stats.lognorm.pdf(fit_x, shape, loc, scale)
                fit_params = {'shape': shape, 'loc': loc, 'scale': scale}
                fit_legend_latex = r"Log-Normal fit \\ $s=\formatnum{3}{\shapeVal}$ \\ $loc=\formatnum{3}{\locVal}$ \\ $scale=\formatnum{3}{\scaleVal}$"
                
            elif dist_type == "Exponential":
                loc, scale = stats.expon.fit(data)
                fit_y = stats.expon.pdf(fit_x, loc, scale)
                fit_params = {'loc': loc, 'scale': scale}
                fit_legend_latex = r"Exponential fit \\ $loc=\formatnum{3}{\locVal}$ \\ $scale=\formatnum{3}{\scaleVal}$"
                
            elif dist_type == "Chi-Squared":
                df_stat, loc, scale = stats.chi2.fit(data)
                fit_y = stats.chi2.pdf(fit_x, df_stat, loc=loc, scale=scale)
                fit_params = {'df': df_stat, 'loc': loc, 'scale': scale}
                fit_legend_latex = r"$\chi^2$ fit \\ $df=\formatnum{3}{\dfVal}$ \\ $loc=\formatnum{3}{\locVal}$ \\ $scale=\formatnum{3}{\scaleVal}$"

            if fit_y is not None:
                max_h = max(counts) if len(counts) > 0 else 1.0
                fit_y = np.nan_to_num(fit_y, nan=0.0, posinf=0.0, neginf=0.0)
                fit_y = np.clip(fit_y, 0.0, max_h * 1.5)
        except Exception:
            fit_x, fit_y = None, None
            fit_legend_latex = ""

    # 3. CSV mit NaN padding generieren, damit alle Spalten gleich lang sind
    max_len = max(len(x_hist), len(fit_x) if fit_x is not None else 0)
    
    csv_dict = {
        'x_hist': np.pad(x_hist, (0, max_len - len(x_hist)), constant_values=np.nan),
        'y_hist': np.pad(y_hist, (0, max_len - len(y_hist)), constant_values=np.nan)
    }
    
    if fit_x is not None and fit_y is not None:
        csv_dict['x_curve'] = np.pad(fit_x, (0, max_len - len(fit_x)), constant_values=np.nan)
        csv_dict['y_curve'] = np.pad(fit_y, (0, max_len - len(fit_y)), constant_values=np.nan)
    else:
        csv_dict['x_curve'] = np.full(max_len, np.nan)
        csv_dict['y_curve'] = np.full(max_len, np.nan)
        
    for key, val in fit_params.items():
        arr = np.full(max_len, np.nan)
        arr[0] = val  # Wir schreiben den Wert exakt in Zeile 0!
        csv_dict[key] = arr

    df = pd.DataFrame(csv_dict)
    os.makedirs(output_dir, exist_ok=True)
    csv_filename = f"{param_name}_plot.csv"
    df.to_csv(os.path.join(output_dir, csv_filename), index=False)

    # 4. LaTeX Code generieren
    tex_filename = f"{param_name}_plot.tex"
    
    read_macros = ""
    for key in fit_params.keys():
        read_macros += f"\\pgfplotstablegetelem{{0}}{{{key}}}\\of\\datatable \\let\\{key}Val\\pgfplotsretval\n"

    # TeX String aufbauen
    safe_param_name = param_name.replace('_', r'\_')
    tex_content = f"""% Plot für {param_name}
\\pgfplotstableread[col sep=comma]{{{csv_filename}}}\\datatable

% Parameter aus Zeile 0 auslesen
{read_macros}
% Hilfsmakro definieren (falls nicht global vorhanden)
\\providecommand{{\\formatnum}}[2]{{\\pgfmathprintnumber[fixed, precision=#1, zerofill]{{#2}}}}

\\begin{{center}}
\\begin{{tikzpicture}}
\\begin{{axis}}[
    title={{Simulation: {safe_param_name}}},
    xlabel={{Simulated Value}},
    ylabel={{Probability density}},
    ymin=0, enlarge x limits=0.05,
    grid=major, grid style={{solid, gray!20}},
    legend cell align={{left}},
    legend style={{
        align=left, fill=white, draw=black!30, rounded corners=1pt,
        at={{(0.95,0.95)}}, anchor=north east
    }},
    width=10cm, height=8cm,
    axis line style={{thick}}, tick style={{thick, black}}
]
    % --- 1. Histogramm ---
    \\addplot [ybar interval, fill=blue!30, draw=blue!70] 
        table [x=x_hist, y=y_hist] {{\\datatable}};
    \\addlegendentry{{Histogram}}
"""

    if fit_x is not None:
        tex_content += f"""
    % --- 2. Fit Kurve ---
    \\addplot [color=red, very thick, no marks] 
        table [x=x_curve, y=y_curve] {{\\datatable}};
    \\addlegendentry{{{fit_legend_latex}}}
"""

    tex_content += """\\end{axis}
\\end{tikzpicture}
\\end{center}
"""

    with open(os.path.join(output_dir, tex_filename), 'w') as f:
        f.write(tex_content)