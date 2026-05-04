from setuptools import setup, find_packages

setup(
    name="chipify",
    version="0.1.0",
    description="High-Performance Mismatch Simulation Wrapper",
    author="Santiago Hofwimmer",
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
            "chipify-cli=chipify.cli:main", 
            "chipify=chipify.cli:run_gui", 
        ]
    }
)