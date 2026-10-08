"""
SAJHA MCP Server — the reserved tool-name separator.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``__`` in a tool name is reserved for namespaced tools: a federation upstream's or an external
server's tools (``<prefix>__<tool>``, docs/architecture/Federation.md) and SAJHA Net's remote tools
(``<net>__<instance>__<tool>``). No other tool may contain it; the tools registry refuses one at
registration and every creator checks it up front (docs/architecture/Federation.md, "Names").
"""

from __future__ import annotations

from typing import Optional

SEPARATOR = '__'


def reserved_name_problem(name: str) -> Optional[str]:
    """Why ``name`` may not be the name of a tool that is not namespaced (None: it may)."""
    if isinstance(name, str) and SEPARATOR in name:
        return (f'tool name {name!r} contains "__", which is reserved for namespaced tools (federated and '
                f'external servers\' <prefix>__<tool>, and SAJHA Net\'s remote tools); use a single "_"')
    return None


def is_namespaced_tool(tool) -> bool:
    """A tool whose name may contain ``__``: it says so (``namespaced_name = True``)."""
    return bool(getattr(tool, 'namespaced_name', False))
