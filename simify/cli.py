# simify.py
import argparse
import os
import sys

from simify import util
from simify import settings
from simify import simulator
from simify.analyzer import print_summary

def main():
    parser = argparse.ArgumentParser(
        description="Simify: High-Performance Mismatch Simulation Wrapper für Xschem und Ngspice.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        "-c", "--config", 
        type=str, 
        default="datasheet.yaml", 
        help="Name der YAML-Konfigurationsdatei.\n(Wird automatisch im Ordner '../in/' gesucht).\nStandard: datasheet.yaml"
    )
    
    args = parser.parse_args()
    yaml_path = os.path.join(settings.IN_DIR, args.config)
    
    if not os.path.exists(yaml_path):
        print(f"[-] Fatal Error: Die Konfigurationsdatei '{yaml_path}' wurde nicht gefunden!")
        sys.exit(1)
        
    print(f"[*] Initialisiere Simify...")
    print(f"[*] Lade Konfiguration: {args.config}")
    
    # 1. Datenmodell initialisieren
    stim = util.Stimuli(yaml_path)
    
    # 2. Simulation ausführen (Engine)
    df = simulator.run_sim(stim)
    
    # 3. Rohdaten als CSV speichern
    csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
    df.to_csv(csv_out, index=False)
    print(f"[+] Fertig! Ergebnisse in {csv_out} gespeichert.")
    
    # 4. Daten analysieren und Konsolen-Dashboard ausgeben
    print_summary(df, stim)
    
def run_gui():
    """Startet die native Tkinter Desktop-App für Simify."""
    # Wir importieren hier erst, damit das CLI ohne X11-Server lauffähig bleibt
    from simify import gui_tk
    print("[*] Starte Simify Desktop GUI...")
    gui_tk.main()

if __name__ == "__main__":
    main()