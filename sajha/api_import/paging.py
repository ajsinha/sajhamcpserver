"""
SAJHA MCP Server — API Import: opt-in pagination following.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Off by default. An imported GET operation can be given a ``paginate`` block (per operation,
on the import request; written into the tool config's ``api_import.paginate``):

    mode       link      next URL from the ``Link: <...>; rel="next"`` header
               next_url  next URL from a field of the body (``next_field``, a dot path)
               cursor    a token from a body field (``next_field``) sent back as ``cursor_param``
               page      ``page_param`` incremented by one per page
               offset    ``offset_param`` advanced by the rows received
    items      dot path to the row array in the body ('' : the body itself, or the first of
               items/data/results/values/records/entries that is an array)
    max_pages, max_items   per-operation caps, never above ``api_import.pagination_max_pages`` /
               ``api_import.pagination_max_items``

Every page is a separate guarded request (sajha/api_import/fetch.py). A next URL is checked
against the SSRF guard before it is followed and must keep the first request's origin
(scheme, host, port), so credentials never travel to another host; one that fails either
check ends the walk with the rows collected so far and the reason in ``stopped``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from sajha.api_import import settings

MODES = ('link', 'next_url', 'cursor', 'page', 'offset')
ITEM_KEYS = ('items', 'data', 'results', 'values', 'records', 'entries')


class PaginationConfigError(ValueError):
    """A ``paginate`` block that cannot work."""


def normalize(cfg: Any, op: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A checked ``paginate`` block for ``op`` (None: off). Raises PaginationConfigError."""
    if not cfg or not isinstance(cfg, dict) or cfg.get('mode') in (None, '', 'off', 'none'):
        return None
    key = op.get('key', '')
    mode = str(cfg.get('mode'))
    if mode not in MODES:
        raise PaginationConfigError(f"{key}: pagination mode must be one of {', '.join(MODES)} (or off)")
    if op.get('graphql') or op.get('method') != 'GET':
        raise PaginationConfigError(f'{key}: pages are followed only for GET operations')
    query = {p['name'] for p in op.get('params') or [] if p.get('in') == 'query'}
    pagers = list(op.get('pagination') or [])
    out: Dict[str, Any] = {'mode': mode, 'items': str(cfg.get('items') or '').strip()}

    def param(field: str, guess: Tuple[str, ...]) -> str:
        value = str(cfg.get(field) or '').strip()
        if not value:
            value = next((p for p in pagers if p.lower().replace('_', '') in guess), '')
        if not value:
            raise PaginationConfigError(f'{key}: pagination mode {mode} needs {field}')
        if query and value not in query:
            raise PaginationConfigError(f'{key}: {field} {value!r} is not a query parameter of this operation')
        return value

    if mode in ('next_url', 'cursor'):
        out['next_field'] = str(cfg.get('next_field') or '').strip()
        if not out['next_field']:
            raise PaginationConfigError(f'{key}: pagination mode {mode} needs next_field (a dot path in the body)')
    if mode == 'cursor':
        out['cursor_param'] = param('cursor_param', ('cursor', 'pagetoken', 'nexttoken', 'after', 'marker',
                                                     'startingafter'))
    elif mode == 'page':
        out['page_param'] = param('page_param', ('page',))
    elif mode == 'offset':
        out['offset_param'] = param('offset_param', ('offset', 'skip', 'start'))
    for cap, ceiling in (('max_pages', settings.pagination_max_pages()), ('max_items', settings.pagination_max_items())):
        try:
            n = int(cfg.get(cap) or 0)
        except (TypeError, ValueError):
            raise PaginationConfigError(f'{key}: {cap} must be a whole number')
        if n < 0:
            raise PaginationConfigError(f'{key}: {cap} must not be negative')
        if n:
            out[cap] = n
    return out


def caps(cfg: Dict[str, Any]) -> Tuple[int, int]:
    """(max pages, max items) for one call: the operation's, capped by the server's."""
    pages, items = settings.pagination_max_pages(), settings.pagination_max_items()
    return min(int(cfg.get('max_pages') or pages), pages), min(int(cfg.get('max_items') or items), items)


def dig(body: Any, path: str) -> Any:
    node = body
    for part in [p for p in (path or '').split('.') if p]:
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def items_of(body: Any, path: str) -> Tuple[Optional[List[Any]], str]:
    """(the row list of a page, the path it was found at) or (None, '')."""
    if path:
        rows = dig(body, path)
        return (rows, path) if isinstance(rows, list) else (None, '')
    if isinstance(body, list):
        return body, ''
    if isinstance(body, dict):
        for k in ITEM_KEYS:
            if isinstance(body.get(k), list):
                return body[k], k
    return None, ''


def with_items(body: Any, path: str, rows: List[Any]) -> Any:
    """``body`` with the list at ``path`` replaced by ``rows``."""
    if not path:
        return rows
    parts = path.split('.')
    root = dict(body) if isinstance(body, dict) else body
    node = root
    for part in parts[:-1]:
        child = node.get(part) if isinstance(node, dict) else None
        if not isinstance(child, dict):
            return body
        child = dict(child)
        node[part] = child
        node = child
    if isinstance(node, dict):
        node[parts[-1]] = rows
    return root


def same_origin(a: str, b: str) -> bool:
    pa, pb = urlsplit(a), urlsplit(b)
    port = {'http': 80, 'https': 443}
    try:
        return (pa.scheme, (pa.hostname or '').lower(), pa.port or port.get(pa.scheme)) == \
               (pb.scheme, (pb.hostname or '').lower(), pb.port or port.get(pb.scheme))
    except ValueError:
        return False


def next_url(current: str, candidate: Any) -> Optional[str]:
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    return urljoin(current, candidate.strip())
