# settings.py
import os

IN_DIR = "../in/"
OUT_DIR = "../out/"
WORK_DIR = "../tmp/"
TB_DIR = "../tb/"

# Fast RAM drive for Docker I/O bypass
FAST_TMP = "/tmp/sim_work/"

# Create directories if they don't exist
os.makedirs(FAST_TMP, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)