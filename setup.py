from setuptools import setup, find_packages

setup(
    name="chipify",
    version="0.2.0",
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
        "scipy",
        "asteval",
    ],
    extras_require={
        # pip install chipify[vacask]  → pulls in PyOPUS for VACASK engine support
        "vacask": ["PyOPUS>=0.11"],
        # pip install chipify[fast]  → numexpr accelerates transient equation eval
        "fast": ["numexpr"],
        # pip install chipify[remote] → httpx client for the HTTPS dispatcher
        # (TLS fingerprint pinning uses stdlib ssl/hashlib — no extra deps).
        "remote": ["httpx>=0.27"],
        # pip install chipify[server] → FastAPI + uvicorn + multipart + cryptography
        # for the `chipify-cli serve` HTTPS server (installed inside the
        # iic-osic-tools container).
        "server": [
            "fastapi>=0.110",
            "uvicorn[standard]>=0.27",
            "python-multipart>=0.0.9",
            "cryptography>=42",
        ],
    },
    entry_points={
        "console_scripts": [
            "chipify-cli=chipify.cli:main",
            "chipify=chipify.cli:run_gui",
        ]
    }
)
