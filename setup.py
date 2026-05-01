# setup.py
from setuptools import setup, find_packages

setup(
    name="simify",
    version="0.1.0",
    description="High-Performance Mismatch Simulation Wrapper für Xschem und Ngspice",
    author="Dein Name",
    packages=find_packages(), # Sucht automatisch nach dem simify/ Ordner
    install_requires=[
        "pandas",
        "numpy",
        "tqdm",
        "jinja2",
        "pyyaml"
    ],
    entry_points={
        "console_scripts": [
            # Sagt dem System: Wenn jemand "simify" ins Terminal tippt,
            # führe die Funktion "main" in der Datei "simify/cli.py" aus!
            "simify=simify.cli:main", 
        ]
    }
)