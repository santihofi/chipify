import copy
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import scipy.stats as stats
from chipify import settings


# Default palette used when no theme dict is supplied (preserves the
# pre-theming behaviour: dark axes with white text).
_DEFAULT_THEME: dict = {
    "bg":          "#1a1a1a",
    "fg":          "white",
    "grid":        "gray",
    "spine":       "white",
    "legend_bg":   "#2b2b2b",
    "legend_edge": "gray",
    "legend_text": "white",
    "accent":      "#3484F0",
}


def _resolve_theme(theme: dict | None, bg_color: str | None = None) -> dict:
    """Return a complete theme dict, filling missing keys from defaults.

    If *bg_color* is supplied (legacy callers), it overrides ``theme["bg"]``.
    """
    base = dict(_DEFAULT_THEME)
    if theme:
        base.update({k: v for k, v in theme.items() if v is not None})
    if bg_color is not None:
        base["bg"] = bg_color
    return base


class PlotManager:
    @staticmethod
    def draw_histogram(fig, ax, canvas, valid_df, current_stim, param, dist_type, group_col, bins_val, do_zoom, comp_run, theme=None):
        th = _resolve_theme(theme)
        ax.clear()
        ax.set_facecolor(th["bg"])
        ax.grid(True, linestyle='--', alpha=0.3, color=th["grid"])
        for spine in ax.spines.values():
            spine.set_edgecolor(th["spine"])
        ax.tick_params(colors=th["fg"])
        title_suffix = f" grouped by {group_col}" if group_col != "None" else ""
        ax.set_title(f"Distribution of: {param}{title_suffix}", color=th["fg"], pad=10)
        ax.set_xlabel("Simulated Value", color=th["fg"])
        ax.set_ylabel("Density", color=th["fg"])
        
        b = 'auto' if bins_val == "Auto" else int(bins_val)
        data_min, data_max = float('inf'), float('-inf')
        
        if group_col != "None" and group_col in valid_df.columns:
            unique_vals = valid_df[group_col].unique()
            groups = [(f"{group_col}={val}", valid_df[valid_df[group_col] == val][param].dropna()) for val in unique_vals]
        else:
            groups = [("Current Run", valid_df[param].dropna())]
            
        colors = plt.cm.tab10(np.linspace(0, 1, max(10, len(groups))))
        
        for i, (grp_name, grp_data) in enumerate(groups):
            if grp_data.empty: continue
            
            if min(grp_data) < data_min: data_min = min(grp_data)
            if max(grp_data) > data_max: data_max = max(grp_data)
            
            c = '#3484F0' if group_col == "None" else colors[i % 10]
            label_text, fit_x, fit_y = grp_name, None, None
            
            if len(grp_data) > 1 and dist_type != "None":
                x_fit = np.linspace(min(grp_data), max(grp_data), 100)
                try:
                    if dist_type == "Gauss (Normal)":
                        mu, std = stats.norm.fit(grp_data)
                        fit_y, fit_x = stats.norm.pdf(x_fit, mu, std), x_fit
                        label_text += f" (μ={mu:.3g}, σ={std:.3g})"
                    elif dist_type == "KDE (Smoothed)":
                        kde = stats.gaussian_kde(grp_data)
                        fit_y, fit_x = kde(x_fit), x_fit
                    elif dist_type == "Uniform":
                        loc, scale = stats.uniform.fit(grp_data)
                        fit_y, fit_x = stats.uniform.pdf(x_fit, loc, scale), x_fit
                    elif dist_type == "Log-Normal":
                        shape, loc, scale = stats.lognorm.fit(grp_data)
                        fit_y, fit_x = stats.lognorm.pdf(x_fit, shape, loc, scale), x_fit
                        label_text += f" (s={shape:.2g}, loc={loc:.2g}, scale={scale:.2g})"
                    elif dist_type == "Exponential":
                        loc, scale = stats.expon.fit(grp_data)
                        fit_y, fit_x = stats.expon.pdf(x_fit, loc, scale), x_fit
                        label_text += f" (loc={loc:.2g}, scale={scale:.2g})"
                    elif dist_type == "Chi-Squared":
                        df_stat, loc, scale = stats.chi2.fit(grp_data)
                        fit_y, fit_x = stats.chi2.pdf(x_fit, df_stat, loc=loc, scale=scale), x_fit
                        label_text += f" (df={df_stat:.2g}, loc={loc:.2g}, scale={scale:.2g})"
                except Exception: pass

            counts, bins_plot, patches = ax.hist(grp_data, bins=b, density=True, color=c, alpha=0.5, edgecolor=th["fg"], linewidth=0.5, label=label_text)
            max_hist_height = max(counts) if len(counts) > 0 else 1.0

            if fit_x is not None and fit_y is not None:
                fit_y_safe = np.nan_to_num(fit_y, nan=0.0, posinf=0.0, neginf=0.0)
                fit_y_safe = np.clip(fit_y_safe, 0.0, max_hist_height * 1.5)
                ax.plot(fit_x, fit_y_safe, color=c, linewidth=2)
        
        if comp_run != "None" and comp_run != "-" and group_col == "None":
            try:
                if comp_run == "Latest (simulation_results)":
                    c_path = os.path.join(settings.OUT_DIR, "simulation_results.csv")
                else:
                    c_path = os.path.join(settings.OUT_DIR, "history", comp_run)

                c_df = pd.read_csv(c_path)
                if 'sim_error' in c_df.columns:
                    c_df['sim_error'] = c_df['sim_error'].fillna('None').astype(str)
                    c_df.loc[c_df['sim_error'].str.lower() == 'nan', 'sim_error'] = 'None'
                    c_valid = c_df[c_df['sim_error'] == 'None']
                else:
                    c_valid = c_df

                if param in c_valid.columns:
                    c_data = c_valid[param].dropna()
                    if not c_data.empty:
                        if min(c_data) < data_min: data_min = min(c_data)
                        if max(c_data) > data_max: data_max = max(c_data)
                        # Reference histogram overlay
                        ref_label = f"Ref: {comp_run.replace('.csv', '')}"
                        ref_counts, _, _ = ax.hist(
                            c_data, bins=b, density=True,
                            color='#e67e22', alpha=0.32,
                            edgecolor='#d35400', linewidth=0.8,
                            label=ref_label
                        )

                        # Reference fit overlay (same fit type as selected for current run)
                        if len(c_data) > 1 and dist_type != "None":
                            try:
                                x_ref = np.linspace(min(c_data), max(c_data), 120)
                                y_ref = None
                                fit_name = "Ref Fit"
                                if dist_type == "Gauss (Normal)":
                                    mu_ref, std_ref = stats.norm.fit(c_data)
                                    y_ref = stats.norm.pdf(x_ref, mu_ref, std_ref)
                                    fit_name = "Ref Gauss"
                                elif dist_type == "KDE (Smoothed)":
                                    kde_ref = stats.gaussian_kde(c_data)
                                    y_ref = kde_ref(x_ref)
                                    fit_name = "Ref KDE"
                                elif dist_type == "Uniform":
                                    loc_ref, scale_ref = stats.uniform.fit(c_data)
                                    y_ref = stats.uniform.pdf(x_ref, loc_ref, scale_ref)
                                    fit_name = "Ref Uniform"
                                elif dist_type == "Log-Normal":
                                    shape_ref, loc_ref, scale_ref = stats.lognorm.fit(c_data)
                                    y_ref = stats.lognorm.pdf(x_ref, shape_ref, loc_ref, scale_ref)
                                    fit_name = "Ref LogNorm"
                                elif dist_type == "Exponential":
                                    loc_ref, scale_ref = stats.expon.fit(c_data)
                                    y_ref = stats.expon.pdf(x_ref, loc_ref, scale_ref)
                                    fit_name = "Ref Exponential"
                                elif dist_type == "Chi-Squared":
                                    df_ref, loc_ref, scale_ref = stats.chi2.fit(c_data)
                                    y_ref = stats.chi2.pdf(x_ref, df_ref, loc=loc_ref, scale=scale_ref)
                                    fit_name = "Ref Chi2"

                                if y_ref is not None:
                                    max_ref_h = max(ref_counts) if len(ref_counts) > 0 else 1.0
                                    y_ref = np.nan_to_num(y_ref, nan=0.0, posinf=0.0, neginf=0.0)
                                    y_ref = np.clip(y_ref, 0.0, max_ref_h * 1.8)
                                    ax.plot(
                                        x_ref, y_ref,
                                        color='#f39c12', linewidth=2.0,
                                        linestyle='--', alpha=0.9,
                                        label=f"{fit_name}: {comp_run.replace('.csv', '')}"
                                    )
                            except Exception:
                                pass
            except Exception as e:
                print(f"Could not overlay comparison run: {e}")

        spec_min, spec_max = None, None
        if current_stim:
            for t in current_stim.tests:
                for v in t.value_lst:
                    if v.name == param:
                        spec_min = getattr(v, 'vmin', getattr(v, 'min', None))
                        spec_max = getattr(v, 'vmax', getattr(v, 'max', None))
                        
        if spec_min is not None: ax.axvline(spec_min, color='#e74c3c', linestyle='dashed', linewidth=2, label=f'Min Spec ({spec_min:.4g})')
        if spec_max is not None: ax.axvline(spec_max, color='#e74c3c', linestyle='dashed', linewidth=2, label=f'Max Spec ({spec_max:.4g})')

        if do_zoom and data_min != float('inf') and data_max != float('-inf'):
            padding = (data_max - data_min) * 0.05
            ax.set_xlim(data_min - (padding or 0.1), data_max + (padding or 0.1))

        if len(ax.get_legend_handles_labels()[1]) > 0:
            leg = ax.legend(loc='best', facecolor=th["legend_bg"], edgecolor=th["legend_edge"])
            for txt in leg.get_texts():
                txt.set_color(th["legend_text"])

        fig.tight_layout()
        canvas.draw()

    @staticmethod
    def draw_adv_plot(fig, ax_dummy, canvas, valid_df, current_stim, mode, x_col, y_col, target, bg_color="#2b2b2b", theme=None):
        th = _resolve_theme(theme, bg_color=bg_color)
        fg = th["fg"]
        if ax_dummy is None or ax_dummy not in fig.axes:
            fig.clf()
            ax = fig.add_subplot(111)
        else:
            ax = ax_dummy
            # Remove stale secondary axes (e.g. old colorbars) that survive ax.clear().
            # Otherwise corner/correlation axes accumulate when switching modes/tabs.
            for extra_ax in list(fig.axes):
                if extra_ax is not ax:
                    try:
                        fig.delaxes(extra_ax)
                    except Exception:
                        pass
            ax.clear()
        ax.set_facecolor(th["bg"])
        for spine in ax.spines.values():
            spine.set_edgecolor(th["spine"])
        ax.tick_params(colors=fg)
        sc_plot, scatter_df = None, None

        if mode == "Scatter Plot":
            if x_col not in valid_df.columns or y_col not in valid_df.columns: return None, None
            pass_mask = valid_df['global_pass'] == True
            colors = np.where(pass_mask, '#2ecc71', '#e74c3c')

            sc_plot = ax.scatter(valid_df[x_col], valid_df[y_col], c=colors, alpha=0.7, edgecolors=fg, linewidths=0.5, picker=5)
            scatter_df = valid_df.copy()

            ax.set_xlabel(x_col, color=fg)
            ax.set_ylabel(y_col, color=fg)
            ax.set_title(f"Interactive Shmoo Plot: {y_col} vs {x_col}", color=fg, pad=10)
            ax.grid(True, linestyle='--', alpha=0.3, color=th["grid"])
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)

            legend_elements = [Line2D([0], [0], marker='o', color='w', markerfacecolor='#2ecc71', label='Pass', markersize=8),
                               Line2D([0], [0], marker='o', color='w', markerfacecolor='#e74c3c', label='Fail', markersize=8)]
            leg = ax.legend(handles=legend_elements, facecolor=th["legend_bg"], edgecolor=th["legend_edge"])
            for t in leg.get_texts():
                t.set_color(th["legend_text"])

        elif mode == "Corner Yield Matrix":
            if x_col not in valid_df.columns or y_col not in valid_df.columns: return None, None
            if len(valid_df[x_col].unique()) > 50 or len(valid_df[y_col].unique()) > 50:
                ax.text(0.5, 0.5, "Too many X/Y values!\nPlease pick discrete sweep parameters.", color=fg, ha='center', va='center')
                canvas.draw()
                return None, None

            # Berechne den prozentualen Anteil von 'True' (Pass) pro Block
            pivot = valid_df.pivot_table(index=y_col, columns=x_col, values='global_pass', aggfunc='mean')

            cax = ax.matshow(pivot, cmap='RdYlGn', vmin=0, vmax=1)
            cbar = fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04)
            cbar.ax.yaxis.set_tick_params(color=fg)
            cbar.outline.set_edgecolor(th["spine"])
            plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color=fg)

            for i in range(len(pivot.index)):
                for j in range(len(pivot.columns)):
                    val = pivot.iloc[i, j]
                    if not pd.isna(val):
                        # Mid-range (yellow) cells need black text; saturated cells get fg
                        ax.text(j, i, f"{val*100:.0f}%", ha='center', va='center', color='black' if 0.3 < val < 0.7 else fg)

            ax.set_xticks(range(len(pivot.columns)))
            ax.set_yticks(range(len(pivot.index)))
            ax.set_xticklabels(pivot.columns, color=fg)
            ax.set_yticklabels(pivot.index, color=fg)
            ax.xaxis.set_ticks_position('bottom')
            ax.set_xlabel(x_col, color=fg)
            ax.set_ylabel(y_col, color=fg)
            ax.set_title(f"Corner Yield Matrix: {y_col} vs {x_col}", color=fg, pad=20)

        elif mode == "Correlation Heatmap":
            numeric_cols = valid_df.select_dtypes(include=[np.number]).columns.tolist()
            plot_cols = [c for c in numeric_cols if not c.endswith('_pass')]
            active_cols = [c for c in plot_cols if valid_df[c].nunique() > 1]

            if len(active_cols) < 2:
                ax.text(0.5, 0.5, "Not enough varying data for correlation map.", color=fg, ha='center', va='center', transform=ax.transAxes)
            else:
                corr = valid_df[active_cols].corr()
                # Mask the self-correlation diagonal (always 1.0 → deep red);
                # grey reads as "not informative" instead of "strongly correlated".
                masked = np.ma.masked_where(np.eye(len(active_cols), dtype=bool), corr.values)
                cmap = copy.copy(plt.cm.coolwarm)
                cmap.set_bad('#7f7f7f')
                cax = ax.matshow(masked, cmap=cmap, vmin=-1, vmax=1)
                cbar = fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04)
                cbar.ax.yaxis.set_tick_params(color=fg)
                cbar.outline.set_edgecolor(th["spine"])
                plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color=fg)
                ax.set_xticks(range(len(active_cols)))
                ax.set_yticks(range(len(active_cols)))
                ax.set_xticklabels(active_cols, rotation=45, ha='left', color=fg, fontsize=9)
                ax.set_yticklabels(active_cols, color=fg, fontsize=9)
                ax.xaxis.set_ticks_position('bottom')
                ax.set_title("Parameter Correlation Matrix", color=fg, pad=20)

        elif mode == "Sensitivity (Tornado)":
            if target == "-" or target not in valid_df.columns or current_stim is None:
                ax.text(0.5, 0.5, "Select a target measurement first.", color=fg, ha='center', va='center')
            else:
                correlations = []
                for p in list(current_stim.params.keys()):
                    if p in valid_df.columns and valid_df[p].nunique() > 1:
                        if pd.api.types.is_numeric_dtype(valid_df[p]): corr = valid_df[p].corr(valid_df[target])
                        else: corr = pd.Series(pd.factorize(valid_df[p])[0]).corr(valid_df[target])
                        if not np.isnan(corr): correlations.append((p, corr))

                if not correlations:
                    ax.text(0.5, 0.5, "No varied parameters found.", color=fg, ha='center', va='center')
                else:
                    correlations.sort(key=lambda x: abs(x[1]))
                    labels, values = [x[0] for x in correlations], [x[1] for x in correlations]
                    colors = ['#2ecc71' if v >= 0 else '#e74c3c' for v in values]
                    ax.barh(labels, values, color=colors, edgecolor='black', linewidth=0.5, alpha=0.8)
                    ax.axvline(0, color=th["grid"], linestyle='-', linewidth=1)
                    ax.set_xlabel("Correlation Impact (Sensitivity)", color=fg)
                    ax.set_ylabel("", color=fg)
                    ax.set_title(f"Sensitivity Analysis for: {target}", color=fg, pad=15)
                    ax.tick_params(colors=fg)

        elif mode == "Fail Breakdown (Pie Chart)":
            pass_cols = [c for c in valid_df.columns if c.endswith('_pass') and not c.endswith('_overall_pass') and c != 'global_pass']
            fail_counts = {c.replace('_pass', ''): (valid_df[c] == False).sum() for c in pass_cols if (valid_df[c] == False).sum() > 0}

            if not fail_counts:
                ax.text(0.5, 0.5, "100% Yield! No failures to analyze.", color='#2ecc71', ha='center', va='center', fontsize=14, weight='bold')
                ax.axis('off')
            else:
                labels, sizes = list(fail_counts.keys()), list(fail_counts.values())
                colors = plt.cm.Pastel1(np.linspace(0, 1, len(labels)))
                explode = [0.1 if s == max(sizes) else 0 for s in sizes]
                patches, texts, autotexts = ax.pie(
                    sizes, explode=explode, labels=labels, colors=colors,
                    autopct='%1.1f%%', startangle=140,
                    textprops={'color': fg, 'fontsize': 10},
                    wedgeprops={'edgecolor': th["spine"], 'linewidth': 1},
                )
                for autotext in autotexts:
                    # Pastel slices are light — keep autopct text black for legibility.
                    autotext.set_color('black')
                    autotext.set_weight('bold')
                ax.set_title("Fail Breakdown: Which constraints caused failures?", color=fg, pad=20)
                ax.axis('equal')

        # ── Plugin plot modes ─────────────────────────────────────────────────
        else:
            try:
                from chipify.plugin_loader import get_plot_plugins
                for cls in get_plot_plugins():
                    if cls.name == mode:
                        plugin = cls()
                        try:
                            plugin.draw(fig, ax, valid_df, current_stim, theme=th)
                        except TypeError:
                            # Older plugins without theme kwarg — fall back gracefully.
                            plugin.draw(fig, ax, valid_df, current_stim)
                        break
            except Exception as exc:
                ax.text(0.5, 0.5, f"Plugin error:\n{exc}",
                        ha="center", va="center", color="#e74c3c",
                        transform=ax.transAxes)

        if ax_dummy is None:
            fig.tight_layout()
        canvas.draw()
        return sc_plot, scatter_df

    @staticmethod
    def _draw_xy_overlay(
        fig,
        canvas,
        adir: str,
        run_ids: list,
        signals: list,
        *,
        x_col: str,
        x_axis_label: str,
        title_prefix: str,
        empty_msg: str,
        no_files_msg: str,
        time_autoscale: bool = False,
        x_log: bool = False,
        pass_map: dict | None = None,
        bg_color: str = "#1a1a1a",
        equations: list | None = None,
        theme=None,
    ) -> dict:
        """
        Overlay per-run curves from CSV files. Internal helper shared by
        ``draw_transient_plot`` and ``draw_dc_sweep``. The Bode plot uses its
        own implementation because it needs two stacked subplots.
        """
        th = _resolve_theme(theme, bg_color=bg_color)
        fg = th["fg"]
        line_map: dict = {}

        # ── Mandatory ghost-fix (Project Brief §3) ────────────────────────────
        fig.clf()
        ax = fig.add_subplot(111)
        ax.set_facecolor(th["bg"])
        fig.patch.set_facecolor(th["bg"])

        # ── Guard: nothing to plot ────────────────────────────────────────────
        if not adir or not run_ids or not signals:
            ax.text(
                0.5, 0.5, empty_msg,
                ha="center", va="center", color="gray",
                transform=ax.transAxes, fontsize=11,
            )
            ax.axis("off")
            canvas.draw()
            return line_map

        # ── Discover matching files ───────────────────────────────────────────
        run_id_set = set(run_ids)
        matched: list[tuple[str, str]] = []
        for fname in os.listdir(adir):
            if not fname.endswith(".csv") or not fname.startswith("run_"):
                continue
            rid = fname[4:].split("__", 1)[0]
            if rid in run_id_set:
                matched.append((rid, os.path.join(adir, fname)))

        if not matched:
            ax.text(0.5, 0.5, no_files_msg, ha="center", va="center", color="gray",
                    transform=ax.transAxes, fontsize=11, wrap=True)
            ax.axis("off")
            canvas.draw()
            return line_map

        # ── X-axis auto-scaling (transient only): probe first file ───────────
        x_scale, x_unit = 1.0, ""
        if time_autoscale:
            try:
                probe_full = pd.read_csv(matched[0][1], usecols=[x_col])
                t_max = probe_full[x_col].abs().max()
                if t_max >= 1.0:
                    x_scale, x_unit = 1.0, "s"
                elif t_max >= 1e-3:
                    x_scale, x_unit = 1e3, "ms"
                elif t_max >= 1e-6:
                    x_scale, x_unit = 1e6, "µs"
                else:
                    x_scale, x_unit = 1e9, "ns"
            except Exception:
                pass

        # ── Alpha auto-fade ───────────────────────────────────────────────────
        n_curves = len(matched) * len(signals)
        alpha = 1.0 if n_curves <= 50 else max(0.05, 50.0 / n_curves)

        # ── Color mode ────────────────────────────────────────────────────────
        single_signal_mode = len(signals) == 1
        fail_color = "#e74c3c"
        base_colors = plt.cm.tab10(np.linspace(0, 1, max(10, len(signals))))
        sig_color = {sig: base_colors[i % 10] for i, sig in enumerate(signals)}

        if single_signal_mode:
            sorted_rids = sorted({rid for rid, _ in matched})
            run_palette = plt.cm.viridis(np.linspace(0.1, 0.9, max(1, len(sorted_rids))))
            run_color_map = {rid: run_palette[i] for i, rid in enumerate(sorted_rids)}
        else:
            run_color_map = {}

        # ── Draw curves ───────────────────────────────────────────────────────
        first_error: str = ""
        drawn_any = False
        for run_id, fpath in matched:
            is_fail = pass_map.get(run_id, True) is False if pass_map else False
            try:
                df = pd.read_csv(fpath)
            except Exception as exc:
                if not first_error:
                    first_error = str(exc)
                continue

            if x_col not in df.columns:
                continue

            if equations:
                from chipify.expression import default_evaluator
                import logging
                for eq in equations:
                    eq_name = eq.get("name", "").strip()
                    eq_expr = eq.get("expr", "").strip()
                    if eq_name and eq_expr:
                        try:
                            df = default_evaluator.evaluate_dataframe_column(
                                df, eq_name, eq_expr
                            )
                        except Exception as exc:
                            logging.getLogger("chipify.plot").debug(
                                "Waveform equation %r skipped: %s", eq_name, exc)

            x = df[x_col] * x_scale if time_autoscale else df[x_col]
            for sig in signals:
                if sig not in df.columns:
                    continue
                if single_signal_mode:
                    color = fail_color if is_fail else run_color_map.get(run_id, sig_color[signals[0]])
                else:
                    color = fail_color if is_fail else sig_color[sig]
                lines = ax.plot(x, df[sig], color=color, alpha=alpha,
                                linewidth=0.8, rasterized=(n_curves > 200),
                                picker=4)
                if lines:
                    line_map[lines[0]] = (run_id, sig)
                drawn_any = True

        if not drawn_any:
            msg = f"Could not read any waveform data.\n({first_error})" if first_error \
                else "Waveform files exist but contain no matching signal columns."
            ax.text(0.5, 0.5, msg, ha="center", va="center", color="gray",
                    transform=ax.transAxes, fontsize=11)
            ax.axis("off")
            canvas.draw()
            return line_map

        # ── Axes labels ───────────────────────────────────────────────────────
        x_label = f"{x_axis_label} ({x_unit})" if x_unit else x_axis_label
        ax.set_xlabel(x_label, color=fg)
        ax.set_ylabel("Signal Value", color=fg)
        if x_log:
            ax.set_xscale("log")
        n_runs_drawn = len({rid for rid, _ in matched})
        ax.set_title(
            f"{title_prefix} — {n_runs_drawn} run(s) × {len(signals)} signal(s)"
            + (f"  [α={alpha:.2f}]" if n_curves > 50 else ""),
            color=fg, pad=10,
        )
        ax.tick_params(colors=fg)
        for spine in ax.spines.values():
            spine.set_edgecolor(th["spine"])
        ax.grid(True, linestyle="--", alpha=0.2, color=th["grid"])

        # ── Legend ────────────────────────────────────────────────────────────
        proxy_handles = []
        if single_signal_mode:
            proxy_handles.append(
                Line2D([0], [0], color=plt.cm.viridis(0.1), linewidth=1.5,
                       label=f"{signals[0]}  (color = run index)")
            )
        else:
            for sig in signals:
                proxy_handles.append(
                    Line2D([0], [0], color=sig_color[sig], linewidth=1.5, label=sig)
                )
        if pass_map and any(v is False for v in pass_map.values()):
            proxy_handles.append(
                Line2D([0], [0], color=fail_color, linewidth=1.5, label="Failing run")
            )
        ax.legend(handles=proxy_handles, loc="best",
                  facecolor=th["legend_bg"], edgecolor=th["legend_edge"],
                  labelcolor=th["legend_text"], fontsize=9)

        fig.tight_layout()
        canvas.draw()
        return line_map

    @staticmethod
    def draw_transient_plot(
        fig,
        canvas,
        tran_dir: str,
        run_ids: list,
        signals: list,
        *,
        pass_map: dict | None = None,
        bg_color: str = "#1a1a1a",
        equations: list | None = None,
        theme=None,
    ) -> dict:
        """Overlay time-domain waveforms from per-run CSV files."""
        return PlotManager._draw_xy_overlay(
            fig, canvas, tran_dir, run_ids, signals,
            x_col="time",
            x_axis_label="Time",
            title_prefix="Transient Overlay",
            empty_msg=("No transient data.\nRun a simulation with "
                       "transient_signals defined,\n"
                       "then select signals and click Refresh."),
            no_files_msg=("No transient CSV files found for the selected runs.\n"
                          "The simulation may not have used transient_signals, "
                          "or the files have been removed."),
            time_autoscale=True,
            pass_map=pass_map, bg_color=bg_color, equations=equations, theme=theme,
        )

    @staticmethod
    def draw_dc_sweep(
        fig,
        canvas,
        dc_dir: str,
        run_ids: list,
        signals: list,
        *,
        pass_map: dict | None = None,
        bg_color: str = "#1a1a1a",
        equations: list | None = None,
        theme=None,
    ) -> dict:
        """Overlay DC sweep curves from per-run CSV files.

        Expects CSVs with a ``sweep`` column as the X axis (the sweep
        parameter from the testbench's ``.dc`` statement).
        """
        return PlotManager._draw_xy_overlay(
            fig, canvas, dc_dir, run_ids, signals,
            x_col="sweep",
            x_axis_label="Sweep",
            title_prefix="DC Sweep Overlay",
            empty_msg=("No DC sweep data.\nRun a simulation with "
                       "dc_signals defined,\n"
                       "then select signals and click Refresh."),
            no_files_msg=("No DC sweep CSV files found for the selected runs.\n"
                          "The simulation may not have used dc_signals, "
                          "or the files have been removed."),
            time_autoscale=False,
            pass_map=pass_map, bg_color=bg_color, equations=equations, theme=theme,
        )

    @staticmethod
    def draw_bode_plot(
        fig,
        canvas,
        ac_dir: str,
        run_ids: list,
        signals: list,
        *,
        pass_map: dict | None = None,
        bg_color: str = "#1a1a1a",
        equations: list | None = None,
        theme=None,
    ) -> dict:
        """Stacked Bode plot — magnitude (dB) above, phase (deg) below.

        Each *signal* refers to the base name as declared in ``ac_signals``;
        the underlying CSV is expected to contain ``<sig>_mag`` (linear) and
        ``<sig>_phase`` (degrees) columns produced by ``ACAnalysis``.
        """
        th = _resolve_theme(theme, bg_color=bg_color)
        fg = th["fg"]
        line_map: dict = {}

        fig.clf()
        fig.patch.set_facecolor(th["bg"])

        if not ac_dir or not run_ids or not signals:
            ax = fig.add_subplot(111)
            ax.set_facecolor(th["bg"])
            ax.text(
                0.5, 0.5,
                "No AC data.\nRun a simulation with ac_signals defined,\n"
                "then select signals and click Refresh.\n\n"
                "If you did and still see nothing, check out/chipify.log for a\n"
                "'... analysis produced no data' warning (the testbench's .ac\n"
                "may not be producing data to capture).",
                ha="center", va="center", color="gray",
                transform=ax.transAxes, fontsize=11,
            )
            ax.axis("off")
            canvas.draw()
            return line_map

        run_id_set = set(run_ids)
        matched: list[tuple[str, str]] = []
        for fname in os.listdir(ac_dir):
            if not fname.endswith(".csv") or not fname.startswith("run_"):
                continue
            rid = fname[4:].split("__", 1)[0]
            if rid in run_id_set:
                matched.append((rid, os.path.join(ac_dir, fname)))

        if not matched:
            ax = fig.add_subplot(111)
            ax.set_facecolor(th["bg"])
            ax.text(
                0.5, 0.5,
                "No AC CSV files found for the selected runs.\n"
                "The AC analysis may have produced no data — check "
                "out/chipify.log for a\n'... analysis produced no data' warning, "
                "or the files have been removed.",
                ha="center", va="center", color="gray",
                transform=ax.transAxes, fontsize=11, wrap=True,
            )
            ax.axis("off")
            canvas.draw()
            return line_map

        ax_mag, ax_phase = fig.subplots(2, 1, sharex=True)
        for ax in (ax_mag, ax_phase):
            ax.set_facecolor(th["bg"])
            ax.tick_params(colors=fg)
            for spine in ax.spines.values():
                spine.set_edgecolor(th["spine"])
            ax.grid(True, which="both", linestyle="--", alpha=0.2, color=th["grid"])
            ax.set_xscale("log")

        n_curves = len(matched) * len(signals)
        alpha = 1.0 if n_curves <= 50 else max(0.05, 50.0 / n_curves)

        single_signal_mode = len(signals) == 1
        fail_color = "#e74c3c"
        base_colors = plt.cm.tab10(np.linspace(0, 1, max(10, len(signals))))
        sig_color = {sig: base_colors[i % 10] for i, sig in enumerate(signals)}

        if single_signal_mode:
            sorted_rids = sorted({rid for rid, _ in matched})
            run_palette = plt.cm.viridis(np.linspace(0.1, 0.9, max(1, len(sorted_rids))))
            run_color_map = {rid: run_palette[i] for i, rid in enumerate(sorted_rids)}
        else:
            run_color_map = {}

        drawn_any = False
        for run_id, fpath in matched:
            is_fail = pass_map.get(run_id, True) is False if pass_map else False
            try:
                df = pd.read_csv(fpath)
            except Exception:
                continue

            if "frequency" not in df.columns:
                continue

            if equations:
                from chipify.expression import default_evaluator
                for eq in equations:
                    eq_name = eq.get("name", "").strip()
                    eq_expr = eq.get("expr", "").strip()
                    if eq_name and eq_expr:
                        try:
                            df = default_evaluator.evaluate_dataframe_column(
                                df, eq_name, eq_expr
                            )
                        except Exception:
                            pass

            freq = df["frequency"]
            for sig in signals:
                mag_col = f"{sig}_mag"
                ph_col = f"{sig}_phase"
                if mag_col not in df.columns or ph_col not in df.columns:
                    continue
                if single_signal_mode:
                    color = fail_color if is_fail else run_color_map.get(run_id, sig_color[signals[0]])
                else:
                    color = fail_color if is_fail else sig_color[sig]
                mag_db = 20.0 * np.log10(np.maximum(np.abs(df[mag_col].values), 1e-30))
                lines = ax_mag.plot(freq, mag_db, color=color, alpha=alpha,
                                    linewidth=0.8, rasterized=(n_curves > 200),
                                    picker=4)
                if lines:
                    line_map[lines[0]] = (run_id, f"{sig} (mag)")
                ax_phase.plot(freq, df[ph_col], color=color, alpha=alpha,
                              linewidth=0.8, rasterized=(n_curves > 200))
                drawn_any = True

        if not drawn_any:
            for ax in (ax_mag, ax_phase):
                ax.cla()
                ax.set_facecolor(th["bg"])
                ax.axis("off")
            ax_mag.text(
                0.5, 0.5,
                "AC CSVs found but no '<sig>_mag' / '<sig>_phase' columns matched.",
                ha="center", va="center", color="gray",
                transform=ax_mag.transAxes, fontsize=11,
            )
            canvas.draw()
            return line_map

        ax_mag.set_ylabel("Magnitude (dB)", color=fg)
        ax_phase.set_ylabel("Phase (°)", color=fg)
        ax_phase.set_xlabel("Frequency (Hz)", color=fg)
        n_runs_drawn = len({rid for rid, _ in matched})
        ax_mag.set_title(
            f"Bode Plot — {n_runs_drawn} run(s) × {len(signals)} signal(s)"
            + (f"  [α={alpha:.2f}]" if n_curves > 50 else ""),
            color=fg, pad=10,
        )

        proxy_handles = []
        if single_signal_mode:
            proxy_handles.append(
                Line2D([0], [0], color=plt.cm.viridis(0.1), linewidth=1.5,
                       label=f"{signals[0]}  (color = run index)")
            )
        else:
            for sig in signals:
                proxy_handles.append(
                    Line2D([0], [0], color=sig_color[sig], linewidth=1.5, label=sig)
                )
        if pass_map and any(v is False for v in pass_map.values()):
            proxy_handles.append(
                Line2D([0], [0], color=fail_color, linewidth=1.5, label="Failing run")
            )
        ax_mag.legend(handles=proxy_handles, loc="best",
                      facecolor=th["legend_bg"], edgecolor=th["legend_edge"],
                      labelcolor=th["legend_text"], fontsize=9)

        fig.tight_layout()
        canvas.draw()
        return line_map