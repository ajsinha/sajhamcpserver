"""
``sajha`` — the SAJHA command line (console script ``sajha``; ``python -m sajhaclient.cli``).

    pip install 'sajhaclient[cli]'
    sajha login && sajha tools list --group

Guide: docs/clients/Command Line.md.  The MCP stdio server it can launch
(``sajha serve --stdio``) lives in the server package: ``sajha/cli/stdio.py``.
"""


def main(argv=None) -> int:
    from sajhaclient.cli.main import main as _main
    return _main(argv)


__all__ = ["main"]
