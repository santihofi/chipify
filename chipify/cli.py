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
        description="Chipify: High-Performance Mismatch Simulation Wrapper for Xschem und Ngspice.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        "-c", "--config", 
        type=str, 
        default="datasheet.yaml", 
        help="Name of .yaml config file.\n(Automatically searched in '../in/').\nDefault: datasheet.yaml"
    )
    
    args = parser.parse_args()
    yaml_path = os.path.join(settings.IN_DIR, args.config)
    
    if not os.path.exists(yaml_path):
        print(f"[-] Fatal Error: configuration file '{yaml_path}' not found!")
        sys.exit(1)
        
    print(f"[*] Initialising Chipify...")
    print(f"[*] Loading configuration: {args.config}")
    
    # 1. Initialize Stimuli object
    stim = util.Stimuli(yaml_path)
    
    # 2. Run Simulation
    df = simulator.run_sim(stim)
    
    # 3. Save raw data as CSV for later analysis
    csv_out = os.path.join(settings.OUT_DIR, "simulation_results.csv")
    df.to_csv(csv_out, index=False)
    print(f"[+] Finished! Results saved to {csv_out}.")
    
    # 4. Analyze data and display console dashboard
    print_summary(df, stim)
    
def run_gui():
    """Starts the tkinter-based desktop GUI for chipify."""
    # Wir importieren hier erst, damit das CLI ohne X11-Server lauffähig bleibt
    from chipify import gui_tk
    print("[*] Starting Chipify Desktop GUI...")
    gui_tk.main()

if __name__ == "__main__":
    main()