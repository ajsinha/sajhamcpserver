"""
SAJHA MCP Server — Client SDK Package Setup

Install: pip install .
Develop: pip install -e .
Build:   python -m build
"""

import os
import re

from setuptools import setup, find_packages

_here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_here, "sajhaclient", "_version.py")) as _f:
    VERSION = re.search(r'__version__ = "([^"]+)"', _f.read()).group(1)

setup(
    name="sajhaclient",
    version=VERSION,
    author="Ashutosh Sinha",
    author_email="ajsinha@gmail.com",
    license="Proprietary. Copyright (c) 2025-2030 Ashutosh Sinha. All rights reserved.",
    description="Python Client SDK for SAJHA MCP Server — REST, MCP, and A2A protocols",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/ajsinha/sajhamcpserver",
    packages=find_packages(),
    package_data={
        'sajhaclient': [
            'examples/*.py', 'examples/*.sh',
            'docs/*.md',
        ],
    },
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=[],  # Zero dependencies — uses only Python stdlib
    extras_require={
        "dev": ["pytest", "pytest-asyncio"],
        # Standard MCP client (SajhaMCPClient) — official MCP Python SDK v2
        "mcp": ["mcp>=2.3,<3"],
        # The `sajha` command line (tools/prompts go over MCP, so it needs the SDK)
        "cli": ["mcp>=2.3,<3"],
    },
    entry_points={
        "console_scripts": [
            "sajha=sajhaclient.cli:main",
        ],
    },
    classifiers=[
        "License :: Other/Proprietary License",
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
