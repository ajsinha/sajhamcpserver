"""
SAJHA MCP Server — the provider-safe tool part of an imported tool's name.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

MCP allows ``.`` in tool names (``[A-Za-z0-9_.-]{1,128}``), but not every LLM provider accepts it
in a function name. An imported tool's own name therefore becomes its **tool part**: every
character outside ``[A-Za-z0-9_-]`` replaced by ``_``. Federation names an upstream's tool
``<prefix>__<tool part>`` (``config.namespaced``); SAJHA Net names a host's tool
``<net>__<safe prefix>__<tool part>`` (``sajha/net/names.py``, SAJHA Net Protocol 5.3). The
upstream or host is always called with its own, unchanged name.
"""

from __future__ import annotations

import re

_NOT_PROVIDER_SAFE = re.compile(r'[^A-Za-z0-9_-]')


def tool_part(name: str) -> str:
    """``name`` with every character outside ``[A-Za-z0-9_-]`` (``.`` included) replaced by ``_``."""
    return _NOT_PROVIDER_SAFE.sub('_', str(name or ''))
