# settings.py
import os

# os.getcwd() holt den Pfad, in dem du dich gerade in der Konsole befindest
PROJECT_ROOT = os.getcwd()

# Alle Pfade werden relativ zum aktuellen Projekt-Ordner aufgebaut
IN_DIR = os.path.join(PROJECT_ROOT, "datasheets") # 'in' habe ich zu 'datasheets' umbenannt, ist sprechender
OUT_DIR = os.path.join(PROJECT_ROOT, "out")
WORK_DIR = os.path.join(PROJECT_ROOT, "tmp")
TB_DIR = os.path.join(PROJECT_ROOT, "tb")

# Der flüchtige RAM-Speicher bleibt absolut im Linux-System (für Docker)
FAST_TMP = "/tmp/sim_work/"

# Erstelle die nötigen Projekt-Ordner automatisch, falls sie noch nicht existieren
os.makedirs(IN_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(TB_DIR, exist_ok=True)
os.makedirs(FAST_TMP, exist_ok=True)