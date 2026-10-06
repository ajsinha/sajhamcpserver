"""
SAJHA MCP Server — connected_http_request: an administrator-bound provider endpoint, called as the caller.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

One implementation, many bindings.  Each tool config names a provider (``auth``) and the
part of its API the tool may reach (``http``)::

    "auth": {"connected_account": "github", "scopes": []},
    "http": {"base_url": "https://api.github.com",
             "methods": ["GET"],
             "paths": ["/user", "/user/*", "/repos/*"],
             "headers": {}}

The model supplies ``method``, ``path``, ``query`` and ``body``; the tool refuses a method
or path outside the binding, a path that tries to leave ``base_url`` (``..``, ``//``, a
scheme, a backslash), and any host outside the provider's ``api_hosts``.  Bind write
methods (POST, PATCH, DELETE) only in a tool whose config also sets
``annotations.destructiveHint: true``.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any, Dict, List

from sajha.accounts.tools.base import ConnectedAccountTool

_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")
_TEXT_LIMIT = 20000


class ConnectedHttpRequestTool(ConnectedAccountTool):

    def __init__(self, config=None):
        super().__init__(config)
        http = dict((self.config or {}).get('http') or {})
        self.base_url = str(http.get('base_url') or '').rstrip('/')
        self.methods: List[str] = [m.upper() for m in http.get('methods') or ['GET']]
        self.paths: List[str] = [str(p) for p in http.get('paths') or ['/*']]
        self.extra_headers: Dict[str, str] = {str(k): str(v) for k, v in (http.get('headers') or {}).items()}
        if not self.base_url.startswith(('https://', 'http://127.0.0.1', 'http://localhost')):
            raise ValueError(f'{self.name}: http.base_url must be an https:// URL')

    def check_path(self, path: str) -> str:
        if not isinstance(path, str) or not _SAFE_PATH.match(path) or '..' in path or '//' in path:
            raise ValueError('path must be an absolute API path such as /user/repos (no "..", "//" or scheme)')
        if not any(fnmatch.fnmatchcase(path, pat) for pat in self.paths):
            raise ValueError(f'path {path} is outside this tool\'s binding ({", ".join(self.paths)})')
        return path

    def run(self, a: Dict[str, Any]) -> Any:
        method = str(a.get('method') or 'GET').upper()
        if method not in self.methods:
            raise ValueError(f'method {method} is not allowed here (allowed: {", ".join(self.methods)})')
        path = self.check_path(a.get('path') or '')
        url = self.base_url + path
        body = a.get('body') if method not in ('GET', 'HEAD', 'DELETE') else None
        resp = self.api(method, url, params=a.get('query') or None, json_body=body, headers=self.extra_headers)
        ctype = resp.headers.get('content-type', '')
        if 'json' in ctype:
            try:
                payload: Any = resp.json()
            except ValueError:
                payload = resp.text[:_TEXT_LIMIT]
        else:
            payload = (resp.text or '')[:_TEXT_LIMIT]
        return {'status': resp.status_code, 'ok': resp.status_code < 400, 'content_type': ctype,
                'body': payload}
