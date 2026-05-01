# gui.py
import streamlit as st
import os
import pandas as pd
import glob

# Importiere deine lokalen Module
from simify import util
from simify import settings
from simify import simulator

# --- SEITENKONFIGURATION ---
st.set_page_config(page_title="Simify EDA", page_icon="⚡", layout="wide")

def main():
    st.title("⚡ Simify EDA Dashboard")
    st.markdown("High-Performance Mismatch & Corner Simulation für Xschem/Ngspice")
    
    # 1. SIDEBAR: Einstellungen & Dateiauswahl
    with st.sidebar:
        st.header("⚙️ Konfiguration")
        
        # Suche alle YAML-Dateien im Projekt-Datasheet-Ordner
        yaml_files = glob.glob(os.path.join(settings.IN_DIR, "*.yaml"))
        yaml_names = [os.path.basename(f) for f in yaml_files]
        
        if not yaml_names:
            st.error(f"Keine .yaml Dateien im Ordner {settings.IN_DIR} gefunden!")
            st.stop()
            
        selected_yaml = st.selectbox("Wähle ein Datasheet:", yaml_names)
        yaml_path = os.path.join(settings.IN_DIR, selected_yaml)
        
        st.divider()
        start_button = st.button("🚀 Simulation Starten", use_container_width=True, type="primary")

    # 2. HAUPTBEREICH: Datasheet-Vorschau
    if not start_button and 'results_df' not in st.session_state:
        st.subheader("Aktuelles Datasheet")
        with open(yaml_path, 'r') as f:
            st.code(f.read(), language='yaml')
            
    # 3. SIMULATION AUSFÜHREN
    if start_button:
        st.subheader(f"Simuliere: {selected_yaml}")
        
        # Ein Lade-Spinner und Fortschrittsbereich
        with st.spinner("Bereite Netzlisten vor und starte Multi-Core Engine..."):
            stim = util.Stimuli(yaml_path)
            
            # WICHTIG: Streamlit verträgt Pythons Multiprocessing manchmal nicht out-of-the-box
            # wegen dem Context. Deine Engine sollte aber laufen, da sie sauber gekapselt ist.
            try:
                df = simulator.run_sim(stim)
                
                # Ergebnisse in der Session speichern, damit sie beim Klicken nicht verschwinden
                st.session_state['results_df'] = df
                st.session_state['stim'] = stim
                
                # CSV speichern (wie bisher)
                csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
                df.to_csv(csv_out, index=False)
                
            except Exception as e:
                st.error(f"Fehler bei der Simulation: {e}")
                st.stop()
                
        st.success("Simulation erfolgreich abgeschlossen!")

    # 4. AUSWERTUNG & DASHBOARD (Wird angezeigt, sobald Ergebnisse vorliegen)
    if 'results_df' in st.session_state:
        df = st.session_state['results_df']
        stim = st.session_state['stim']
        
        st.divider()
        st.header("📊 Auswertung")
        
        # Kennzahlen-Karten (Metrics) oben
        col1, col2, col3 = st.columns(3)
        total_runs = len(df)
        crashes = len(df[df['sim_error'] != 'None'])
        
        # Global Yield berechnen
        tb_pass_cols = [c for c in df.columns if c.endswith('_overall_pass')]
        global_pass_series = pd.Series([True]*len(df))
        for col in tb_pass_cols:
            global_pass_series = global_pass_series & df[col]
            
        global_yield = (global_pass_series.sum() / total_runs) * 100
        
        col1.metric("Iterationen", total_runs)
        col2.metric("Ngspice Crashes", crashes, delta_color="inverse")
        col3.metric("Global Yield", f"{global_yield:.1f} %", 
                    delta="PASS" if global_yield == 100 else "FAIL", 
                    delta_color="normal" if global_yield == 100 else "inverse")

        # Tabellen-Ansicht (Rohdaten)
        with st.expander("🔍 Rohdaten (Pandas DataFrame) ansehen"):
            st.dataframe(df, use_container_width=True)
            
        # Worst-Case Filter (Zeige nur Fails)
        st.subheader("❌ Worst-Case Analyse")
        failed_df = df[~global_pass_series]
        
        if failed_df.empty:
            st.success("Alle Simulationen liegen innerhalb der Spezifikation!")
        else:
            st.warning(f"Es gibt {len(failed_df)} Ausreißer. Hier sind die fehlerhaften Parameter-Sets:")
            # Zeigt die Tabelle an und hebt Fehlermeldungen hervor
            st.dataframe(failed_df, use_container_width=True)
            
            # Bonus: Ein Histogramm für die Streuung!
            st.subheader("📈 Mismatch Streuung (Verteilung)")
            # Finde den ersten Messwert zum Plotten
            if stim.tests and stim.tests[0].value_lst:
                first_param_name = stim.tests[0].value_lst[0].name
                if first_param_name in df.columns:
                    st.bar_chart(df[first_param_name].value_counts(bins=20).sort_index())