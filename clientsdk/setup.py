"""
SAJHA MCP Server — Client SDK Package Setup

Install: pip install .
Develop: pip install -e .
Build:   python -m build
"""

from setuptools import setup, find_packages

setup(
    name="sajhaclient",
    version="5.2.0",
    author="Ashutosh Sinha",
    author_email="ajsinha@gmail.com",
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
    },
    classifiers=[
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
