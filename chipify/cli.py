# chipify.py
import argparse
import os
import sys

from chipify import util
from chipify import settings
from chipify import simulator
from chipify.analyzer import print_summary

def main():
    parser = argparse.ArgumentParser(
        description="chipify: High-Performance Mismatch Simulation Wrapper for Xschem und Ngspice.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        "-c", "--config", 
        type=str, 
        default="datasheet.yaml", 
        help="Name of .yaml config file.\n(Wird automatisch im Ordner '../in/' gesucht).\nStandard: datasheet.yaml"
    )
    
    args = parser.parse_args()
    yaml_path = os.path.join(settings.IN_DIR, args.config)
    
    if not os.path.exists(yaml_path):
        print(f"[-] Fatal Error: configuration file '{yaml_path}' not found!")
        sys.exit(1)
        
    print(f"[*] Initialising chipify...")
    print(f"[*] Loading configuration: {args.config}")
    
    # 1. Datenmodell initialisieren
    stim = util.Stimuli(yaml_path)
    
    # 2. Simulation ausführen (Engine)
    df = simulator.run_sim(stim)
    
    # 3. Rohdaten als CSV speichern
    csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
    df.to_csv(csv_out, index=False)
    print(f"[+] Finished! Results saved to {csv_out}.")
    
    # 4. Daten analysieren und Konsolen-Dashboard ausgeben
    print_summary(df, stim)
    
def run_gui():
    """Startet die native Tkinter Desktop-App für chipify."""
    # Wir importieren hier erst, damit das CLI ohne X11-Server lauffähig bleibt
    from chipify import gui_tk
    print("[*] Starting chipify Desktop GUI...")
    gui_tk.main()

if __name__ == "__main__":
    main()