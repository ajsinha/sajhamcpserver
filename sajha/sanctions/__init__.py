"""
SAJHA MCP Server — sanctions screening against official lists held in a local index.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``sources`` (the lists and their terms), ``parse`` (the list files), ``refresh`` (download, parse,
diff), ``store`` (the index under ``sanctions.data_dir``), ``match`` (normalisation and scoring)
and ``service`` (what the ``sanctions_*`` tools do). CLI: ``python -m sajha.sanctions``.
Design: docs/architecture/Open Data Tools.md; guide: docs/tools/public-data/Sanctions Tool Reference Guide.md.
"""
