#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="qcf",
    version="0.1.0",
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
