import os
import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

def generate_pdf_report(df, stim, yaml_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = os.path.join(out_dir, f"report_{timestamp}.pdf")

    valid_df = df[df['sim_error'] == 'None']

    with PdfPages(pdf_path) as pdf:
        # Page 1: Summary Text
        fig_text = plt.figure(figsize=(8.27, 11.69)) 
        fig_text.patch.set_facecolor('white')
        ax_text = fig_text.add_subplot(111)
        ax_text.axis('off')
        
        total = len(df)
        crashes = len(df[df['sim_error'] != 'None'])
        tb_pass_cols = [c for c in df.columns if c.endswith('_overall_pass')]
        tmp_df = df.copy()
        tmp_df['global_pass'] = True 
        for col in tb_pass_cols: tmp_df['global_pass'] = tmp_df['global_pass'] & tmp_df[col]
        global_yield = (int(tmp_df['global_pass'].sum()) / total) * 100 if total > 0 else 0
        
        yaml_name = os.path.basename(yaml_path) if yaml_path else "Unknown"
        title = f"Simify EDA Report - {yaml_name}"
        ax_text.text(0.5, 0.95, title, fontsize=18, weight='bold', ha='center', va='top', color='black')
        ax_text.text(0.5, 0.90, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", fontsize=10, ha='center', va='top', color='gray')
        
        summary = (
            f"Simulation Summary:\n"
            f"-----------------------------\n"
            f"Total Iterations: {total}\n"
            f"Simulator Crashes: {crashes}\n"
            f"Global Yield: {global_yield:.1f}%\n"
        )
        ax_text.text(0.1, 0.80, summary, fontsize=12, ha='left', va='top', family='monospace', color='black')
        pdf.savefig(fig_text)
        plt.close(fig_text)

        # Page 2+: Histograms 
        plot_cols = []
        for test in stim.tests:
            for val_obj in test.value_lst:
                if val_obj.name in valid_df.columns:
                    plot_cols.append((val_obj.name, getattr(val_obj, 'vmin', getattr(val_obj, 'min', None)), getattr(val_obj, 'vmax', getattr(val_obj, 'max', None))))
        
        for param, s_min, s_max in plot_cols:
            data = valid_df[param].dropna()
            if len(data) == 0: continue
            
            fig = plt.figure(figsize=(8, 5))
            fig.patch.set_facecolor('white')
            ax = fig.add_subplot(111)
            ax.grid(True, linestyle='--', alpha=0.5, color='gray')
            ax.set_title(f"Distribution: {param}", color='black', pad=10)
            ax.set_xlabel("Simulated Value", color='black')
            ax.set_ylabel("Density", color='black')
            
            ax.hist(data, bins='auto', density=True, color='#3498db', alpha=0.7, edgecolor='black', linewidth=0.5)
            
            if s_min is not None: ax.axvline(s_min, color='red', linestyle='dashed', linewidth=2, label=f'Min Spec ({s_min:.4g})')
            if s_max is not None: ax.axvline(s_max, color='red', linestyle='dashed', linewidth=2, label=f'Max Spec ({s_max:.4g})')
                
            ax.tick_params(colors='black')
            if len(ax.get_legend_handles_labels()[1]) > 0: ax.legend(loc='best', facecolor='white', edgecolor='gray')
            
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)

        # Page N: Tornado Plot
        target = plot_cols[0][0] if plot_cols else None
        if target:
            correlations = []
            for p in list(stim.params.keys()):
                if p in valid_df.columns and valid_df[p].nunique() > 1:
                    if pd.api.types.is_numeric_dtype(valid_df[p]):
                        corr = valid_df[p].corr(valid_df[target])
                    else:
                        factorized, _ = pd.factorize(valid_df[p])
                        corr = pd.Series(factorized).corr(valid_df[target])
                    if not np.isnan(corr):
                        correlations.append((p, corr))
                        
            if correlations:
                correlations.sort(key=lambda x: abs(x[1]))
                labels = [x[0] for x in correlations]
                values = [x[1] for x in correlations]
                colors = ['#2ecc71' if v >= 0 else '#e74c3c' for v in values]
                
                fig = plt.figure(figsize=(8, 6))
                fig.patch.set_facecolor('white')
                ax = fig.add_subplot(111)
                ax.barh(labels, values, color=colors, edgecolor='black', linewidth=0.5, alpha=0.8)
                ax.axvline(0, color='black', linestyle='-', linewidth=1)
                ax.set_xlabel("Correlation Impact (Sensitivity)", color='black')
                ax.set_title(f"Sensitivity Analysis for: {target}", color='black', pad=15)
                ax.tick_params(colors='black')
                fig.tight_layout()
                pdf.savefig(fig)
                plt.close(fig)
                
    return pdf_path