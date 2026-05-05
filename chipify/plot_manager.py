import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import scipy.stats as stats
from chipify import settings

class PlotManager:
    @staticmethod
    def draw_histogram(fig, ax, canvas, valid_df, current_stim, param, dist_type, group_col, bins_val, do_zoom, comp_run):
        ax.clear()
        ax.grid(True, linestyle='--', alpha=0.3)
        title_suffix = f" grouped by {group_col}" if group_col != "None" else ""
        ax.set_title(f"Distribution of: {param}{title_suffix}", color="white", pad=10)
        ax.set_xlabel("Simulated Value")
        ax.set_ylabel("Density")
        
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

            counts, bins_plot, patches = ax.hist(grp_data, bins=b, density=True, color=c, alpha=0.5, edgecolor='white', linewidth=0.5, label=label_text)
            max_hist_height = max(counts) if len(counts) > 0 else 1.0

            if fit_x is not None and fit_y is not None:
                fit_y_safe = np.nan_to_num(fit_y, nan=0.0, posinf=0.0, neginf=0.0)
                fit_y_safe = np.clip(fit_y_safe, 0.0, max_hist_height * 1.5)
                ax.plot(fit_x, fit_y_safe, color=c, linewidth=2)
        
        if comp_run != "None" and comp_run != "-" and group_col == "None": 
            try:
                c_path = os.path.join(settings.OUT_DIR, "history", comp_run) if "run_" in comp_run else os.path.join(settings.OUT_DIR, "simulation_results.csv")
                c_df = pd.read_csv(c_path)
                c_valid = c_df[c_df['sim_error'] == 'None'] if 'sim_error' in c_df.columns else c_df
                if param in c_valid.columns:
                    c_data = c_valid[param].dropna()
                    if not c_data.empty:
                        if min(c_data) < data_min: data_min = min(c_data)
                        if max(c_data) > data_max: data_max = max(c_data)
                        ax.hist(c_data, bins=b, density=True, color='#e67e22', alpha=0.5, edgecolor='#d35400', linewidth=0.5, label=f"Ref: {comp_run.replace('.csv', '')}")
            except Exception as e: print(f"Could not overlay comparison run: {e}")

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
            ax.legend(loc='best', facecolor='#2b2b2b', edgecolor='gray')

        fig.tight_layout()
        canvas.draw()

    @staticmethod
    def draw_adv_plot(fig, ax_dummy, canvas, valid_df, current_stim, mode, x_col, y_col, target, bg_color="#2b2b2b"):
        fig.clf()
        ax = fig.add_subplot(111)
        ax.set_facecolor(bg_color)
        sc_plot, scatter_df = None, None

        if mode == "Scatter Plot":
            if x_col not in valid_df.columns or y_col not in valid_df.columns: return None, None
            pass_mask = valid_df['global_pass'] == True
            colors = np.where(pass_mask, '#2ecc71', '#e74c3c')
            
            sc_plot = ax.scatter(valid_df[x_col], valid_df[y_col], c=colors, alpha=0.7, edgecolors='white', linewidths=0.5, picker=5)
            scatter_df = valid_df.copy()
            
            ax.set_xlabel(x_col, color='white')
            ax.set_ylabel(y_col, color='white')
            ax.set_title(f"Interactive Shmoo Plot: {y_col} vs {x_col}", color='white', pad=10)
            ax.grid(True, linestyle='--', alpha=0.3)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            
            legend_elements = [Line2D([0], [0], marker='o', color='w', markerfacecolor='#2ecc71', label='Pass', markersize=8),
                               Line2D([0], [0], marker='o', color='w', markerfacecolor='#e74c3c', label='Fail', markersize=8)]
            ax.legend(handles=legend_elements, facecolor="#2b2b2b", edgecolor='gray')

        elif mode == "Corner Yield Matrix":
            if x_col not in valid_df.columns or y_col not in valid_df.columns: return None, None
            if len(valid_df[x_col].unique()) > 50 or len(valid_df[y_col].unique()) > 50:
                ax.text(0.5, 0.5, "Zu viele X/Y Werte!\nBitte wähle diskrete Sweep-Parameter.", color='white', ha='center', va='center')
                canvas.draw()
                return None, None
                
            # Berechne den prozentualen Anteil von 'True' (Pass) pro Block
            pivot = valid_df.pivot_table(index=y_col, columns=x_col, values='global_pass', aggfunc='mean')
            
            cax = ax.matshow(pivot, cmap='RdYlGn', vmin=0, vmax=1)
            cbar = fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04)
            cbar.ax.yaxis.set_tick_params(color='white')
            cbar.outline.set_edgecolor('gray')
            plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')
            
            for i in range(len(pivot.index)):
                for j in range(len(pivot.columns)):
                    val = pivot.iloc[i, j]
                    if not pd.isna(val):
                        ax.text(j, i, f"{val*100:.0f}%", ha='center', va='center', color='black' if 0.3 < val < 0.7 else 'white')
                    
            ax.set_xticks(range(len(pivot.columns)))
            ax.set_yticks(range(len(pivot.index)))
            ax.set_xticklabels(pivot.columns, color='white')
            ax.set_yticklabels(pivot.index, color='white')
            ax.xaxis.set_ticks_position('bottom')
            ax.set_xlabel(x_col, color='white')
            ax.set_ylabel(y_col, color='white')
            ax.set_title(f"Corner Yield Matrix: {y_col} vs {x_col}", color='white', pad=20)

        elif mode == "Correlation Heatmap":
            numeric_cols = valid_df.select_dtypes(include=[np.number]).columns.tolist()
            plot_cols = [c for c in numeric_cols if not c.endswith('_pass')]
            active_cols = [c for c in plot_cols if valid_df[c].nunique() > 1]
            
            if len(active_cols) < 2:
                ax.text(0.5, 0.5, "Not enough varying data for correlation map.", color='white', ha='center', va='center', transform=ax.transAxes)
            else:
                corr = valid_df[active_cols].corr()
                cax = ax.matshow(corr, cmap='coolwarm', vmin=-1, vmax=1)
                cbar = fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04)
                cbar.ax.yaxis.set_tick_params(color='white')
                cbar.outline.set_edgecolor('gray')
                plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')
                ax.set_xticks(range(len(active_cols)))
                ax.set_yticks(range(len(active_cols)))
                ax.set_xticklabels(active_cols, rotation=45, ha='left', color='white', fontsize=9)
                ax.set_yticklabels(active_cols, color='white', fontsize=9)
                ax.xaxis.set_ticks_position('bottom')
                ax.set_title("Parameter Correlation Matrix", color='white', pad=20)
                
        elif mode == "Sensitivity (Tornado)":
            if target == "-" or target not in valid_df.columns or current_stim is None:
                ax.text(0.5, 0.5, "Select a target measurement first.", color='white', ha='center', va='center')
            else:
                correlations = []
                for p in list(current_stim.params.keys()):
                    if p in valid_df.columns and valid_df[p].nunique() > 1:
                        if pd.api.types.is_numeric_dtype(valid_df[p]): corr = valid_df[p].corr(valid_df[target])
                        else: corr = pd.Series(pd.factorize(valid_df[p])[0]).corr(valid_df[target])
                        if not np.isnan(corr): correlations.append((p, corr))
                        
                if not correlations:
                    ax.text(0.5, 0.5, "No varied parameters found.", color='white', ha='center', va='center')
                else:
                    correlations.sort(key=lambda x: abs(x[1]))
                    labels, values = [x[0] for x in correlations], [x[1] for x in correlations]
                    colors = ['#2ecc71' if v >= 0 else '#e74c3c' for v in values]
                    ax.barh(labels, values, color=colors, edgecolor='black', linewidth=0.5, alpha=0.8)
                    ax.axvline(0, color='gray', linestyle='-', linewidth=1)
                    ax.set_xlabel("Correlation Impact (Sensitivity)", color='white')
                    ax.set_title(f"Sensitivity Analysis for: {target}", color='white', pad=15)
                    ax.tick_params(colors='white')
            
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
                patches, texts, autotexts = ax.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140, textprops={'color': 'white', 'fontsize': 10}, wedgeprops={'edgecolor': 'gray', 'linewidth': 1})
                for autotext in autotexts: autotext.set_color('black'); autotext.set_weight('bold')
                ax.set_title("Fail Breakdown: Which constraints caused failures?", color='white', pad=20)
                ax.axis('equal') 

        fig.tight_layout()
        canvas.draw()
        return sc_plot, scatter_df