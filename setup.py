from setuptools import setup, find_packages

setup(
    name="chipify",
    version="0.2.0",
    description="High-Performance Mismatch Simulation Wrapper",
    author="Santiago Hofwimmer",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        # Shipped with the wheel so `chipify-cli install-server` can drop the
        # env-aware wrapper onto an iic-osic-tools container without needing
        # a source checkout there.
        "chipify._server": ["chipify-remote.sh"],
    },
    install_requires=[
        "pandas",
        "numpy",
        "tqdm",
        "jinja2",
        "pyyaml",
        "customtkinter",
        "matplotlib",
        "scipy",
        "asteval",
    ],
    extras_require={
        # pip install chipify[vacask]  → pulls in PyOPUS for VACASK engine support
        "vacask": ["PyOPUS>=0.11"],
        # pip install chipify[fast]  → numexpr accelerates transient equation eval
        "fast": ["numexpr"],
        # pip install chipify[remote] → paramiko for SSH/SFTP remote dispatcher
        "remote": ["paramiko>=3.0"],
    },
    entry_points={
        "console_scripts": [
            "chipify-cli=chipify.cli:main",
            "chipify=chipify.cli:run_gui",
        ]
    }
)