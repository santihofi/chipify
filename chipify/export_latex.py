import os
import pandas as pd
import numpy as np
import scipy.stats as stats

def generate_latex_export(param_name, data_series, dist_type, bins, output_dir):
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
    tex_content = f"""% Plot für {param_name}
\\pgfplotstableread[col sep=comma]{{{csv_filename}}}\\datatable

% Parameter aus Zeile 0 auslesen
{read_macros}
% Hilfsmakro definieren (falls nicht global vorhanden)
\\providecommand{{\\formatnum}}[2]{{\\pgfmathprintnumber[fixed, precision=#1, zerofill]{{#2}}}}

\\begin{{center}}
\\begin{{tikzpicture}}
\\begin{{axis}}[
    title={{Simulation: {param_name.replace('_', '\\_')}}},
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