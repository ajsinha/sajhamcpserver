"""
SAJHA MCP Server — MCP Apps extension (io.modelcontextprotocol/ui), 2026-07-28 path.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A tool opts in from its JSON config:

    "_meta": {"ui": {"resourceUri": "ui://sajha/loan-amortization.html"}}

(optionally "visibility": ["model", "app"]).  On modern (2026-07-28) requests,
when ``mcp.apps.enabled`` is true:

* server/discover advertises ``capabilities.extensions["io.modelcontextprotocol/ui"]``;
* tools/list carries the tool's ``_meta.ui``;
* resources/list lists the ``ui://`` views and resources/read serves them as
  ``text/html;profile=mcp-app``.

Views: the bundled ones in sajha/core/mcp_app_views/ plus any ``*.html`` in
``mcp.apps.dir`` (default config/apps), each published as ``ui://sajha/<file>``.
Hosts render them in a sandboxed iframe; they must be self-contained (SAJHA
declares no CSP domains, so hosts block all network access from the view).
Tools still return their normal text/structured result, so clients without
Apps support are unaffected (SEP-2133 graceful degradation).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EXTENSION_ID = 'io.modelcontextprotocol/ui'
APP_MIME_TYPE = 'text/html;profile=mcp-app'
URI_PREFIX = 'ui://sajha/'
_BUNDLED_DIR = Path(__file__).parent / 'mcp_app_views'
_MAX_VIEW_BYTES = 2 * 1024 * 1024

# Titles/descriptions for bundled views (file name -> metadata)
_BUNDLED = {
    'loan_amortization.html': {
        'name': 'loan-amortization',
        'title': 'Loan amortization chart',
        'description': 'Yearly principal vs. interest chart and schedule table for calc_loan_amortization',
    },
}
_warned: set = set()


def apps_enabled() -> bool:
    from sajha.core.config import _bool
    return _bool('mcp.apps.enabled', True)


def _views_dir() -> Path:
    from sajha.core.config import _get
    return Path(_get('mcp.apps.dir', 'config/apps') or 'config/apps')


def ui_views() -> Dict[str, Dict[str, Any]]:
    """uri -> {path, name, title, description} for every available view."""
    views: Dict[str, Dict[str, Any]] = {}
    for directory in (_BUNDLED_DIR, _views_dir()):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob('*.html')):
            if not path.is_file() or path.is_symlink():
                continue
            meta = _BUNDLED.get(path.name, {}) if directory == _BUNDLED_DIR else {}
            views[URI_PREFIX + path.name.replace('_', '-')] = {
                'path': path,
                'name': meta.get('name', path.stem),
                'title': meta.get('title', path.stem.replace('_', ' ').title()),
                'description': meta.get('description', f'MCP App view {path.name}'),
            }
    return views


def tool_ui_meta(tool_config: Optional[Dict[str, Any]], tool_name: str = '?') -> Optional[Dict[str, Any]]:
    """The validated ``_meta.ui`` of a tool config, or None (invalid ones are warned about once)."""
    meta = (tool_config or {}).get('_meta')
    ui = meta.get('ui') if isinstance(meta, dict) else None
    if not isinstance(ui, dict):
        return None
    uri = ui.get('resourceUri')
    problem = None
    if not isinstance(uri, str) or not uri.startswith('ui://'):
        problem = f'resourceUri {uri!r} is not a ui:// URI'
    elif uri not in ui_views():
        problem = f'resourceUri {uri!r} names no available view'
    out: Dict[str, Any] = {'resourceUri': uri}
    visibility = ui.get('visibility')
    if visibility is not None:
        if isinstance(visibility, list) and visibility and all(v in ('model', 'app') for v in visibility):
            out['visibility'] = list(visibility)
        else:
            problem = problem or f'visibility {visibility!r} must be a list of "model"/"app"'
    if problem:
        if (tool_name, problem) not in _warned:
            _warned.add((tool_name, problem))
            logger.warning(f'Tool {tool_name!r}: ignoring _meta.ui ({problem})')
        return None
    return out


def resources() -> List[Dict[str, Any]]:
    return [{'uri': uri, 'name': v['name'], 'title': v['title'], 'description': v['description'],
             'mimeType': APP_MIME_TYPE} for uri, v in ui_views().items()]


def read(uri: str) -> Optional[Dict[str, Any]]:
    """resources/read result for a ui:// view, or None when the URI is not a view."""
    view = ui_views().get(uri)
    if view is None:
        return None
    path: Path = view['path']
    if path.stat().st_size > _MAX_VIEW_BYTES:
        raise ValueError(f'view {path.name} is larger than {_MAX_VIEW_BYTES} bytes')
    text = path.read_text(encoding='utf-8')
    return {'contents': [{'uri': uri, 'mimeType': APP_MIME_TYPE, 'text': text,
                          '_meta': {'ui': {'prefersBorder': True}}}]}
