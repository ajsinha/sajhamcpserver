"""
SAJHA MCP Server — the ``mcpServers`` file (docs/architecture/Federation.md, "The mcpServers file").
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Reads the de-facto standard ``{"mcpServers": {...}}`` JSON (the shape Claude Desktop, Cursor and VS Code
use), default ``config/mcp_servers.json`` (``federation.mcp_servers_file``; git-ignored, it may hold
credentials). Each entry becomes a federation upstream whose id is the entry's key:

* standard fields: ``url``, ``headers``, ``command``, ``args``, ``env``, and ``type`` / ``transport``
  (``http``, ``streamable_http``, ``streamable-http``, ``sse``, ``stdio``; without one, ``stdio`` when
  there is a ``command``, else Streamable HTTP);
* SAJHA keys, all optional: ``vendor`` (default the key), ``prefix`` (default the vendor: tools are
  named ``<prefix>__<tool>`` here and published so in SAJHA Net), ``external`` (default **true**: the
  server is offered into SAJHA Net by this instance and is never a member; ``false`` makes it an
  ordinary internal federation upstream), ``tools`` (globs of the server's tools to take; federation's
  ``include_tools``), ``enabled`` (``false``: listed, never connected), ``cwd`` (stdio), ``title``,
  ``timeout_seconds``; a key starting with ``_`` is a comment, at any depth;
* ``${NAME}`` and ``${NAME:default}`` in ``url``, header values, ``args`` and ``env`` are read from the
  environment. A raw secret-looking header still works (the owner's intranet stance) but is reported,
  by header name only, never its value.

Pure functions; :class:`McpServersFile` keeps the parsed result and re-reads only when the file's
modification time or size changes.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_PATH = 'config/mcp_servers.json'
EXTERNAL_KEY = 'external'
_VAR = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}')
_SECRET_HEADER = re.compile(r'authorization|api[-_]?key|token|secret|cookie|password', re.I)
_TRANSPORT = {'http': 'streamable_http', 'streamable_http': 'streamable_http', 'streamable-http': 'streamable_http',
              'streamablehttp': 'streamable_http', 'sse': 'sse', 'stdio': 'stdio'}
SAJHA_KEYS = ('vendor', EXTERNAL_KEY, 'tools', 'prefix', 'enabled', 'title', 'timeout_seconds', 'cwd')
STANDARD_KEYS = ('url', 'headers', 'command', 'args', 'env', 'type', 'transport')


def expand(value: str) -> str:
    """``${NAME}`` and ``${NAME:default}`` from the environment ('' when unset and no default)."""
    return _VAR.sub(lambda m: os.environ.get(m.group(1), m.group(2) if m.group(2) is not None else ''), value)


@dataclass
class Parsed:
    upstreams: List[Dict[str, Any]] = field(default_factory=list)   # federation upstream definitions
    external: List[Dict[str, Any]] = field(default_factory=list)    # {upstream, vendor}: SAJHA Net external servers
    errors: Dict[str, str] = field(default_factory=dict)            # entry key -> why it was not used
    raw_secrets: List[str] = field(default_factory=list)            # "<entry>: <header name>" given as raw values
    vendors: Dict[str, str] = field(default_factory=dict)           # entry key -> vendor (internal entries too)


def _uncomment(v: Any) -> Any:
    """Drop every key starting with ``_`` (a comment), at any depth."""
    if isinstance(v, dict):
        return {k: _uncomment(x) for k, x in v.items() if not str(k).startswith('_')}
    if isinstance(v, list):
        return [_uncomment(x) for x in v]
    return v


def _vendor_of(key: str) -> str:
    return re.sub(r'[^a-z0-9_]', '_', key.lower()).strip('_')


def parse(data: Any) -> Parsed:
    """The upstreams and external servers of one ``{"mcpServers": {...}}`` document."""
    out = Parsed()
    if not isinstance(data, dict):
        out.errors['(file)'] = 'the file must be a JSON object with "mcpServers"'
        return out
    servers = data.get('mcpServers', data.get('servers'))
    if not isinstance(servers, dict):
        out.errors['(file)'] = 'no "mcpServers" object'
        return out
    for key, e in servers.items():
        key = str(key)
        if key.startswith('_'):
            continue                                       # a comment
        if not isinstance(e, dict):
            out.errors[key] = 'an entry must be an object'
            continue
        e = _uncomment(e)
        unknown = set(e) - set(SAJHA_KEYS) - set(STANDARD_KEYS) - {'description', 'disabled'}
        if unknown:
            out.errors[key] = f'unknown field(s): {", ".join(sorted(unknown))}'
            continue
        t = str(e.get('transport') or e.get('type') or '').strip().lower()
        if t and t not in _TRANSPORT:
            out.errors[key] = f'type {t!r} is not one of http, sse, stdio'
            continue
        transport = _TRANSPORT.get(t) or ('stdio' if e.get('command') else 'streamable_http')
        headers = e.get('headers') or {}
        env = e.get('env') or {}
        args = e.get('args') or []
        if not isinstance(headers, dict) or not isinstance(env, dict) or not isinstance(args, list):
            out.errors[key] = 'headers and env must be objects, args a list'
            continue
        for h, v in headers.items():
            if _SECRET_HEADER.search(str(h)) and '${' not in str(v):
                out.raw_secrets.append(f'{key}: {h}')
        up: Dict[str, Any] = {'id': key, 'transport': transport}
        if e.get('url'):
            up['url'] = expand(str(e['url']))
        if headers:
            up['headers'] = {str(h): expand(str(v)) for h, v in headers.items()}
        if e.get('command'):
            up['command'] = expand(str(e['command']))
        if args:
            up['args'] = [expand(str(a)) for a in args]
        if env:
            up['env'] = {str(k): expand(str(v)) for k, v in env.items()}
        if e.get('cwd'):
            up['cwd'] = expand(str(e['cwd']))
        for k in ('title', 'timeout_seconds'):
            if e.get(k) not in (None, ''):
                up[k] = e[k]
        vendor = str(e.get('vendor') or _vendor_of(key))
        out.vendors[key] = vendor
        up['prefix'] = str(e.get('prefix') or vendor)   # tools are <prefix>__<tool>, here and in SAJHA Net
        if 'enabled' in e:
            up['enabled'] = e['enabled']
        elif e.get('disabled') is True:
            up['enabled'] = False
        if e.get('tools'):
            up['include_tools'] = e['tools'] if isinstance(e['tools'], list) else \
                [x.strip() for x in str(e['tools']).split(',') if x.strip()]
        from sajha.core.config import parse_bool
        external = parse_bool(e.get(EXTERNAL_KEY), True) if EXTERNAL_KEY in e else True
        if external:
            out.external.append({'upstream': key, 'vendor': vendor, 'prefix': up['prefix']})
        out.upstreams.append(up)
    return out


class McpServersFile:
    """The parsed file, re-read when its modification time or size changes."""

    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path
        self._sig: Optional[Tuple[int, int]] = None
        self._parsed = Parsed()
        self._lock = threading.Lock()

    def _stat(self) -> Optional[Tuple[int, int]]:
        try:
            st = os.stat(self.path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def changed(self) -> bool:
        return self._stat() != self._sig

    def load(self, force: bool = False) -> Parsed:
        with self._lock:
            sig = self._stat()
            if not force and sig == self._sig:
                return self._parsed
            self._sig = sig
            if sig is None:
                self._parsed = Parsed()
                return self._parsed
            try:
                data = json.loads(Path(self.path).read_text(encoding='utf-8') or '{}')
            except (OSError, ValueError) as e:
                self._parsed = Parsed(errors={'(file)': f'{self.path} cannot be read as JSON: {e}'})
                logger.error(f'federation: {self.path} cannot be read as JSON: {e}')
                return self._parsed
            self._parsed = parse(data)
            for who in self._parsed.raw_secrets:
                logger.warning(f'federation: {self.path}: {who} is a raw value; consider ${{ENV_NAME}}')
            for k, why in self._parsed.errors.items():
                logger.error(f'federation: {self.path}: {k}: {why}')
            return self._parsed

    @property
    def parsed(self) -> Parsed:
        return self._parsed


def resolve_path() -> str:
    from sajha.core.config import _get
    return str(_get('federation.mcp_servers_file', DEFAULT_PATH) or DEFAULT_PATH)
