"""
SAJHA MCP Server — provider packs: a connected-account preset plus a reviewed API Import of the
service's bundled OpenAPI spec, installed together through the review-and-approve gate.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    manifest.py   the pack format (pack.json, the bundled spec and its licence), discovery
    service.py    catalog, plan (preview + review hash), install (the gate), uninstall
    __main__.py   python -m sajha.packs list | show | plan | install | uninstall
    bundled/      the packs shipped with SAJHA (each spec's source and licence in its pack.json)

The admin API is sajha/routes/packs_routes.py. Design: docs/architecture/Connected Accounts.md §11
"""

from sajha.packs.manifest import Pack, PackError  # noqa: F401
