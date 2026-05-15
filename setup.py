#!/usr/bin/env python3
import re
from pathlib import Path

from setuptools import find_packages, setup

here = Path(__file__).resolve().parent
version = re.search(
    r'__version__\s*=\s*"(.+?)"',
    (here / "qcf" / "__init__.py").read_text(),
).group(1)

setup(
    name="qcf",
    version=version,
    description="The Quad-Core Flow (QCF) — tech-lead → coder → reviewer → security",
    packages=find_packages(include=["qcf", "qcf.*"]),
    package_data={
        "qcf": ["prompts/*.j2", "prompts/*.md.j2", "default_config.toml"],
    },
    entry_points={
        "console_scripts": [
            "qcf = qcf.cli:main",
            "pipeline = qcf.cli:main",
        ],
    },
    install_requires=[
        "jinja2>=3",
        'tomli>=1.1; python_version < "3.11"',
    ],
    python_requires=">=3.10",
)
