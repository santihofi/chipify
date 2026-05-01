from setuptools import setup, find_packages

setup(
    name="simify",
    version="0.1.0",
    description="High-Performance Mismatch Simulation Wrapper",
    author="Dein Name",
    packages=find_packages(), 
    install_requires=[
        "pandas",
        "numpy",
        "tqdm",
        "jinja2",
        "pyyaml",
        "customtkinter",
        "matplotlib",
        "scipy"
    ],
    entry_points={
        "console_scripts": [
            "simify=simify.cli:main", 
            "simify-gui=simify.cli:run_gui", 
        ]
    }
)