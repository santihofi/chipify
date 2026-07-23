import re
from pathlib import Path

from setuptools import setup, find_packages

here = Path(__file__).parent
long_description = (here / "README.md").read_text(encoding="utf-8")

# Single source of truth for the version: chipify/__init__.py
_init = (here / "chipify" / "__init__.py").read_text(encoding="utf-8")
version = re.search(r'^__version__ = "([^"]+)"', _init, re.M).group(1)

setup(
    name="chipify",
    version=version,
    description="High-Performance Mismatch Simulation Wrapper for Xschem and Ngspice",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Santiago Hofwimmer",
    author_email="santiago.hofwimmer2@gmail.com",
    url="https://github.com/santihofi/chipify",
    license="Apache-2.0",
    python_requires=">=3.11",
    packages=find_packages(exclude=["tests", "tests.*"]),
    # Ship the PEP 561 marker so installed copies expose their type hints,
    # plus the GUI application/window icon assets.
    package_data={
        "chipify": ["py.typed"],
        "chipify.gui_qt": ["resources/*.ico", "resources/*.png"],
    },
    install_requires=[
        "pandas",
        "numpy",
        "tqdm",
        "jinja2",
        "pyyaml",
        # Qt GUI. Only the Essentials modules are used (QtCore/QtGui/QtWidgets),
        # so we depend on the smaller PySide6-Essentials meta-package rather than
        # the full PySide6 (which also drags in PySide6-Addons: QtWebEngine,
        # QtCharts, QtMultimedia, …, none of which chipify imports). It provides
        # the identical `PySide6.*` import namespace. >=6.7 has improved Wayland
        # popup handling; the xcb platform plugin additionally needs the
        # libxcb-cursor0 *system* library (see install.sh / README — system libs
        # can't be declared here).
        "PySide6-Essentials>=6.7",
        "matplotlib",
        "scipy",
        "asteval",
    ],
    extras_require={
        # pip install chipify[vacask]  → pulls in PyOPUS for VACASK engine support
        "vacask": ["PyOPUS>=0.11"],
        # pip install chipify[fast]  → numexpr accelerates transient equation eval.
        # >=2.8.4: first release that validates expressions before evaluating
        # them — required because SafeEvaluator feeds user-supplied equations
        # to numexpr.evaluate().
        "fast": ["numexpr>=2.8.4"],
    },
    entry_points={
        "console_scripts": [
            "chipify-cli=chipify.cli:main",
            "chipify=chipify.gui_qt.app:main",
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],
)
