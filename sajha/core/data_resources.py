"""
SAJHA MCP Server — the ``sajha://data/<file>`` resources.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

One listing and one reader for the data files under ``data/duckdb`` and ``data/sqlselect``,
used by MCP resources/list and resources/read (both protocol eras) and by
``/api/resources/*``. Who may see which file is :func:`sajha.auth.access.can_read_resource`
(anonymous callers: ``mcp.anonymous.resources``, default none). A file the caller may not
read is reported exactly like a missing one.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

PREFIX = 'sajha://data/'
DATA_DIRS = ('data/duckdb', 'data/sqlselect')
_EXTENSIONS = ('.csv', '.parquet', '.json', '.xlsx')


def _allowed(session: Optional[Dict], uri: str) -> bool:
    from sajha.auth.access import can_read_resource
    return can_read_resource(session, uri)


def list_resources(session: Optional[Dict]) -> List[Dict]:
    """resources/list entries for the data files this caller may read."""
    out: List[Dict] = []
    seen = set()
    for data_dir in DATA_DIRS:
        if not os.path.isdir(data_dir):
            continue
        for fname in sorted(os.listdir(data_dir)):
            uri = PREFIX + fname
            if not fname.endswith(_EXTENSIONS) or uri in seen or not _allowed(session, uri):
                continue
            seen.add(uri)
            out.append({
                'uri': uri,
                'name': fname,
                'mimeType': 'application/octet-stream',
                'description': f'Data file: {fname}',
            })
    return out


def read_resource(uri: str, session: Optional[Dict]) -> Optional[Dict]:
    """The resources/read result for a data URI, or None (no such file, a path outside the
    data directories, or a file this caller may not read). Raises OSError on a read error."""
    if not isinstance(uri, str) or not uri.startswith(PREFIX):
        return None
    fname = uri[len(PREFIX):]
    if not fname or fname != os.path.basename(fname) or fname in ('.', '..') or '\\' in fname:
        return None                                    # no path traversal
    if not fname.endswith(_EXTENSIONS) or not _allowed(session, uri):
        return None
    for data_dir in DATA_DIRS:
        fpath = os.path.join(data_dir, fname)
        if os.path.isfile(fpath):
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
            return {
                'contents': [{
                    'uri': uri,
                    'mimeType': 'text/csv' if fname.endswith('.csv') else 'application/json',
                    'text': content,
                }]
            }
    return None
