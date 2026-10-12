"""
SAJHA MCP Server — API Import: the generic executor.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Every imported tool is an :class:`ImportedAPITool` configured by the ``api_import`` block
of its JSON config; no code is generated. ``BaseMCPTool`` validates the arguments against
``inputSchema`` before :meth:`ImportedAPITool.execute` runs; this module builds the HTTP
request (path, query, header and cookie parameters, a JSON / form / text body, the
credentials), sends it through the SSRF guard (sajha/api_import/fetch.py), and returns
the envelope ``{"status", "body", "next_page"?}`` for a 2xx answer. Anything else raises
:class:`APICallError`, which MCP reports as ``isError: true``.

``api_import`` block (written by sajha/api_import/service.py)::

    api_id, kind ('openapi' | 'graphql'), operation, method, path, server_url,
    params: [{arg, name, in, style, explode}], body: {arg, content_type} | None,
    response_content_type, security: [[scheme, ...], ...] | None,
    auth: {scheme: {type, ... *_ref secret references}}, timeout_seconds,
    rate_limit_per_minute, pagination (pager parameter names, a hint),
    paginate (opt-in page following, sajha/api_import/paging.py) | absent,
    graphql: {document, field, operation_name}, fingerprint

    body may also carry ``fields`` / ``part_types`` (multipart/form-data) or ``binary: true``;
    file values are encoded by sajha/api_import/bodies.py.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

from sajha.api_import import bodies, fetch, paging, settings
from sajha.tools.base_mcp_tool import BaseMCPTool

USER_AGENT = 'SAJHA-API-Import'
ERROR_SNIPPET = 500


class APICallError(RuntimeError):
    """The upstream call failed (HTTP error status, timeout, refused address, ...)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


# ── secrets ──────────────────────────────────────────────────────────

def resolve_secret(ref: Optional[str], what: str) -> str:
    """A secret reference (env:, file:, db:) resolved; raises APICallError when it resolves to nothing."""
    if not ref:
        raise APICallError(f'{what}: no secret reference is configured')
    from sajha.federation.security import secrets
    value = secrets().resolve(str(ref))
    if not value:
        raise APICallError(f'{what}: the secret reference {ref!r} resolves to nothing')
    return value


def is_secret_ref(value: Any) -> bool:
    return isinstance(value, str) and value.split(':', 1)[0].lower() in ('env', 'file', 'db') and ':' in value


# ── OAuth 2.0 client credentials (token cache per token URL + client + scope) ──

_TOKENS: Dict[Tuple[str, str, str], Tuple[str, float]] = {}
_TOKENS_LOCK = threading.Lock()
TOKEN_SKEW = 30


def _client_credentials_token(cfg: Dict[str, Any], timeout: float, refresh: bool = False) -> Tuple[str, str]:
    token_url = str(cfg.get('token_url') or '')
    client_id = str(cfg.get('client_id') or '')
    scope = ' '.join(cfg.get('scopes') or []) if isinstance(cfg.get('scopes'), list) else str(cfg.get('scope') or '')
    key = (token_url, client_id, scope)
    with _TOKENS_LOCK:
        cached = _TOKENS.get(key)
        if cached and not refresh and time.time() < cached[1]:
            return cached[0], ''
    secret = resolve_secret(cfg.get('client_secret_ref'), 'OAuth client secret')
    form = {'grant_type': 'client_credentials', 'client_id': client_id, 'client_secret': secret}
    if scope:
        form['scope'] = scope
    if cfg.get('audience'):
        form['audience'] = str(cfg['audience'])
    try:
        resp = fetch.request('POST', token_url, headers={'Content-Type': 'application/x-www-form-urlencoded',
                                                         'Accept': 'application/json', 'User-Agent': USER_AGENT},
                             content=urlencode(form).encode(), timeout=timeout, max_bytes=256 * 1024,
                             follow_redirects=False)
    except fetch.UnsafeURLError as e:
        raise APICallError(f'OAuth token URL refused: {e}')
    except fetch.FetchError as e:
        raise APICallError(f'OAuth token request failed: {e}')
    if resp.status != 200:
        raise APICallError(f'OAuth token request failed with HTTP {resp.status}')
    try:
        body = json.loads(resp.content)
        token = body['access_token']
        ttl = float(body.get('expires_in') or 3600)
    except (ValueError, KeyError, TypeError):
        raise APICallError('OAuth token response has no access_token')
    with _TOKENS_LOCK:
        _TOKENS[key] = (token, time.time() + max(0.0, ttl - TOKEN_SKEW))
    return token, secret


def _connected_account_token(cfg: Dict[str, Any]) -> str:
    """The calling user's ``Authorization`` value from their connected account. The tool config
    carries ``"auth": {"connected_account": <provider>}``, so BaseMCPTool binds the caller's token
    around the call (sajha/accounts/injection.py); detected at run time, so API Import works
    without that feature."""
    import importlib.util
    if importlib.util.find_spec('sajha.accounts') is None:
        raise APICallError('this tool uses a per-user connected account, and the connected-accounts '
                           'feature (sajha.accounts) is not installed')
    from sajha.accounts.injection import current_token
    provider = str(cfg.get('provider') or '')
    try:
        token = current_token(provider or None)
    except RuntimeError as e:
        raise APICallError(str(e))
    return token.authorization() if hasattr(token, 'authorization') else f'Bearer {token}'


def _requirement(security: Optional[List[List[str]]], auth: Dict[str, Any]) -> List[str]:
    """The schemes to apply: the first alternative whose schemes all have credentials, plus
    schemes the administrator added by hand (``global: true``)."""
    chosen: List[str] = []
    if security:
        for alt in security:
            if all(s in auth for s in alt):
                chosen = list(alt)
                break
    for name, cfg in auth.items():
        if isinstance(cfg, dict) and cfg.get('global') and name not in chosen:
            chosen.append(name)
    return chosen


def apply_auth(spec: Dict[str, Any], headers: Dict[str, str], query: List[Tuple[str, str]],
               cookies: Dict[str, str], timeout: float, refresh: bool = False) -> List[str]:
    """Add credentials to the request; returns the secret values used (for redaction)."""
    auth = spec.get('auth') or {}
    secrets_used: List[str] = []
    for name in _requirement(spec.get('security'), auth):
        cfg = auth.get(name) or {}
        kind = cfg.get('type')
        if kind == 'apiKey':
            value = resolve_secret(cfg.get('value_ref'), f'API key {name}')
            where, key = cfg.get('in', 'header'), str(cfg.get('name') or 'X-API-Key')
            if where == 'query':
                query.append((key, value))
            elif where == 'cookie':
                cookies[key] = value
            else:
                headers[key] = value
            secrets_used.append(value)
        elif kind == 'bearer':
            token = resolve_secret(cfg.get('token_ref'), f'bearer token {name}')
            headers['Authorization'] = f'Bearer {token}'
            secrets_used.append(token)
        elif kind == 'basic':
            password = resolve_secret(cfg.get('password_ref'), f'password {name}')
            raw = f"{cfg.get('username') or ''}:{password}".encode()
            headers['Authorization'] = 'Basic ' + base64.b64encode(raw).decode()
            secrets_used.append(password)
        elif kind == 'oauth2_client_credentials':
            token, secret = _client_credentials_token(cfg, timeout, refresh)
            headers['Authorization'] = f'Bearer {token}'
            secrets_used += [v for v in (token, secret) if v]
        elif kind == 'connected_account':
            value = _connected_account_token(cfg)
            headers['Authorization'] = value
            secrets_used.append(value.split(' ', 1)[-1])
    return secrets_used


# ── rate limit (per API, per process) ────────────────────────────────

_CALLS: Dict[str, deque] = {}
_CALLS_LOCK = threading.Lock()


def _check_rate(api_id: str, per_minute: int) -> None:
    if not per_minute or per_minute <= 0:
        return
    now = time.monotonic()
    with _CALLS_LOCK:
        q = _CALLS.setdefault(api_id, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= per_minute:
            raise APICallError(f'rate limit for API {api_id} reached ({per_minute} calls per minute); '
                               f'try again in {int(60 - (now - q[0])) + 1}s')
        q.append(now)


# ── serialisation ────────────────────────────────────────────────────

def _scalar(v: Any) -> str:
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if v is None:
        return ''
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(',', ':'))
    return str(v)


def _query_pairs(p: Dict[str, Any], value: Any) -> List[Tuple[str, str]]:
    name, style, explode = p['name'], p.get('style') or 'form', p.get('explode', True)
    if isinstance(value, list):
        if style == 'form' and explode:
            return [(name, _scalar(v)) for v in value]
        sep = {'spaceDelimited': ' ', 'pipeDelimited': '|'}.get(style, ',')
        return [(name, sep.join(_scalar(v) for v in value))]
    if isinstance(value, dict):
        if style == 'deepObject':
            return [(f'{name}[{k}]', _scalar(v)) for k, v in value.items()]
        if explode:
            return [(str(k), _scalar(v)) for k, v in value.items()]
        return [(name, ','.join(f'{k},{_scalar(v)}' for k, v in value.items()))]
    return [(name, _scalar(value))]


def _simple(value: Any, explode: bool = False) -> str:
    if isinstance(value, list):
        return ','.join(_scalar(v) for v in value)
    if isinstance(value, dict):
        return ','.join((f'{k}={_scalar(v)}' if explode else f'{k},{_scalar(v)}') for k, v in value.items())
    return _scalar(value)


def build_request(spec: Dict[str, Any], arguments: Dict[str, Any]):
    """(method, url, query pairs, headers, cookies, body bytes) for one call."""
    method = (spec.get('method') or 'GET').upper()
    base = str(spec.get('server_url') or '').rstrip('/')
    if not base:
        raise APICallError('this tool has no base URL (server_url)')
    path = spec.get('path') or ''
    query: List[Tuple[str, str]] = []
    headers: Dict[str, str] = {'User-Agent': USER_AGENT}
    cookies: Dict[str, str] = {}
    for p in spec.get('params') or []:
        if p['arg'] not in arguments or arguments[p['arg']] is None:
            continue
        value = arguments[p['arg']]
        where = p.get('in')
        if where == 'path':
            path = path.replace('{' + p['name'] + '}', quote(_simple(value, p.get('explode', False)), safe=''))
        elif where == 'query':
            query.extend(_query_pairs(p, value))
        elif where == 'header':
            headers[p['name']] = _simple(value, p.get('explode', False))
        elif where == 'cookie':
            cookies[p['name']] = _simple(value)
    if '{' in path and '}' in path:
        missing = [seg for seg in path.split('/') if seg.startswith('{')]
        raise APICallError(f"missing path parameter(s): {', '.join(missing)}")
    content: Optional[bytes] = None
    body = spec.get('body')
    if spec.get('kind') == 'graphql':
        gql = spec.get('graphql') or {}
        variables = {p['name']: arguments[p['arg']] for p in spec.get('params') or [] if p['arg'] in arguments}
        payload = {'query': gql.get('document', ''), 'variables': variables}
        if gql.get('operation_name'):
            payload['operationName'] = gql['operation_name']
        content = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    elif body and body.get('arg') in arguments:
        value = arguments[body['arg']]
        ct = body.get('content_type') or 'application/json'
        if ct == bodies.MULTIPART or body.get('binary'):
            try:
                if ct == bodies.MULTIPART:
                    content, ct = bodies.encode_multipart(value, body.get('fields') or {}, body.get('part_types'))
                else:
                    content, ct = bodies.encode_binary(value, ct)
            except bodies.BodyError as e:
                raise APICallError(f'{body["arg"]}: {e}')
        elif ct == 'application/x-www-form-urlencoded':
            pairs = []
            for k, v in (value or {}).items() if isinstance(value, dict) else []:
                pairs += [(k, _scalar(x)) for x in v] if isinstance(v, list) else [(k, _scalar(v))]
            content = urlencode(pairs).encode()
        elif ct.startswith('text/'):
            content = _scalar(value).encode()
        else:
            content = json.dumps(value).encode()
        headers['Content-Type'] = ct
    accept = spec.get('response_content_type') or 'application/json'
    headers['Accept'] = f'{accept}, */*;q=0.5' if accept != '*/*' else '*/*'
    return method, base + path, query, headers, cookies, content


def _parse_body(resp: fetch.Response) -> Any:
    if not resp.content:
        return None
    ct = resp.content_type
    if 'json' in ct or not ct:
        try:
            return json.loads(resp.content)
        except ValueError:
            if 'json' in ct:
                return resp.text()
    return resp.text()


def _redact(text: str, secrets_used: List[str]) -> str:
    from sajha.federation.security import redact
    return redact(text, secrets_used)


def _send(spec: Dict[str, Any], method: str, url: str, query: List[Tuple[str, str]], headers: Dict[str, str],
          cookies: Dict[str, str], content: Optional[bytes], timeout: float, label: str):
    """One guarded request with the credentials applied (an OAuth 401 retried once with a fresh
    token); (response, secret values used). Raises APICallError."""
    resp, secrets_used = None, []
    for attempt in (0, 1):
        send_headers, send_query, send_cookies = dict(headers), list(query), dict(cookies)
        secrets_used = apply_auth(spec, send_headers, send_query, send_cookies, timeout, refresh=attempt == 1)
        if send_cookies:
            send_headers['Cookie'] = '; '.join(f'{k}={v}' for k, v in send_cookies.items())
        try:
            resp = fetch.request(method, url, params=send_query, headers=send_headers, content=content,
                                 timeout=timeout, max_bytes=settings.max_response_bytes(),
                                 follow_redirects=method in ('GET', 'HEAD'))
        except fetch.UnsafeURLError as e:
            raise APICallError(f'{label}: refused by the SSRF guard: {e}')
        except fetch.FetchTimeout:
            raise APICallError(f'{label}: timed out after {timeout:g}s')
        except fetch.FetchError as e:
            raise APICallError(_redact(f'{label}: {e}', secrets_used))
        oauth = any((spec.get('auth') or {}).get(s, {}).get('type') == 'oauth2_client_credentials'
                    for s in _requirement(spec.get('security'), spec.get('auth') or {}))
        if resp.status == 401 and oauth and attempt == 0:
            continue                                  # token expired or revoked early: once more
        break
    if not 200 <= resp.status < 300:
        snippet = resp.text()[:ERROR_SNIPPET].strip()
        msg = f'HTTP {resp.status} {resp.reason} from {label}'.replace('  ', ' ')
        if resp.status == 429 and resp.headers.get('retry-after'):
            msg += f" (retry after {resp.headers['retry-after']}s)"
        if snippet:
            msg += f': {snippet}'
        raise APICallError(_redact(msg, secrets_used), resp.status)
    return resp, secrets_used


def call(spec: Dict[str, Any], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Make the call ``spec`` describes with ``arguments``; the envelope, or APICallError."""
    timeout = float(spec.get('timeout_seconds') or settings.timeout_seconds())
    _check_rate(str(spec.get('api_id') or ''), int(spec.get('rate_limit_per_minute') or 0))
    method, url, query, headers, cookies, content = build_request(spec, arguments or {})
    label = f"{method} {spec.get('path') or url}" if spec.get('kind') != 'graphql' else \
        f"GraphQL {(spec.get('graphql') or {}).get('field', '')}"
    resp, secrets_used = _send(spec, method, url, query, headers, cookies, content, timeout, label)
    body = _parse_body(resp)
    if spec.get('kind') == 'graphql':
        if not isinstance(body, dict):
            raise APICallError(f'{label}: the answer is not a GraphQL JSON response')
        errors = body.get('errors')
        data = body.get('data')
        field = (spec.get('graphql') or {}).get('field')
        value = data.get(field) if isinstance(data, dict) else None
        if errors and value is None:
            messages = '; '.join(str(e.get('message', e)) if isinstance(e, dict) else str(e) for e in errors)
            raise APICallError(_redact(f'{label}: {messages}', secrets_used)[:2000])
        out = {'status': resp.status, 'body': value}
        if errors:
            out['errors'] = errors
        return out
    if spec.get('paginate') and method == 'GET':
        return _follow(spec, spec['paginate'], resp, body, url, query, headers, cookies, timeout, label)
    out = {'status': resp.status, 'body': body}
    if resp.links.get('next'):
        out['next_page'] = resp.links['next']
    return out


# ── pagination following (opt-in per operation; sajha/api_import/paging.py) ──

def _replace(query: List[Tuple[str, str]], name: str, value: str) -> List[Tuple[str, str]]:
    return [(k, v) for k, v in query if k != name] + [(name, value)]


def _first(query: List[Tuple[str, str]], name: str) -> Optional[str]:
    return next((v for k, v in query if k == name), None)


def _follow(spec: Dict[str, Any], cfg: Dict[str, Any], first: fetch.Response, body: Any, url: str,
            query: List[Tuple[str, str]], headers: Dict[str, str], cookies: Dict[str, str],
            timeout: float, label: str) -> Dict[str, Any]:
    """Follow the pages after ``first`` within the caps; the merged envelope."""
    import logging
    mode = cfg.get('mode')
    max_pages, max_items = paging.caps(cfg)
    rows, path = paging.items_of(body, str(cfg.get('items') or ''))
    out: Dict[str, Any] = {'status': first.status}
    if rows is None:
        out.update(body=body, pages=1, truncated=False,
                   stopped='the answer has no row array to collect (set items to its dot path)')
        if first.links.get('next'):
            out['next_page'] = first.links['next']
        return out
    collected, pages, resp, page_body, page_rows = list(rows), 1, first, body, rows
    seen = {first.url}
    page_no = offset = 0
    if mode == 'page':
        try:
            page_no = int(_first(query, cfg['page_param']) or 1)
        except ValueError:
            page_no = 1
    elif mode == 'offset':
        try:
            offset = int(_first(query, cfg['offset_param']) or 0)
        except ValueError:
            offset = 0
    stopped, truncated = '', False
    continuation: Dict[str, Any] = {}
    while True:
        nxt_url, nxt_query = None, None
        if mode == 'link':
            nxt_url = paging.next_url(resp.url, resp.links.get('next'))
        elif mode == 'next_url':
            nxt_url = paging.next_url(resp.url, paging.dig(page_body, cfg['next_field']))
        elif mode == 'cursor':
            token = paging.dig(page_body, cfg['next_field'])
            if token not in (None, '', False):
                nxt_query = _replace(query, cfg['cursor_param'], _scalar(token))
                continuation = {cfg['cursor_param']: token}
        elif mode == 'page' and page_rows:
            nxt_query = _replace(query, cfg['page_param'], str(page_no + 1))
            continuation = {cfg['page_param']: page_no + 1}
        elif mode == 'offset' and page_rows:
            nxt_query = _replace(query, cfg['offset_param'], str(offset + len(page_rows)))
            continuation = {cfg['offset_param']: offset + len(page_rows)}
        if nxt_url is None and nxt_query is None:
            break                                     # the last page
        if nxt_url:
            continuation = {'url': nxt_url}
        if pages >= max_pages or len(collected) >= max_items:
            truncated = True
            break
        if nxt_url:
            if nxt_url in seen:
                stopped = 'the next page URL repeats an earlier one'
                break
            try:
                fetch.guard(nxt_url)
            except fetch.UnsafeURLError as e:
                logging.getLogger(__name__).warning(f'{label}: next page refused by the SSRF guard: {e}')
                stopped, truncated, continuation = f'the next page {nxt_url} was refused by the SSRF guard: {e}', True, {}
                break
            if not paging.same_origin(nxt_url, url):
                stopped, truncated = (f'the next page {nxt_url} is on another origin than {spec.get("server_url")}; '
                                      f'not followed (credentials stay with their API)'), True
                continuation = {}
                break
            send_url, send_query = nxt_url, []
        else:
            send_url, send_query = url, nxt_query
            key = url + '?' + '&'.join(f'{k}={v}' for k, v in nxt_query)
            if key in seen:
                stopped = 'the next page repeats an earlier one'
                break
            seen.add(key)
        try:
            _check_rate(str(spec.get('api_id') or ''), int(spec.get('rate_limit_per_minute') or 0))
            resp, _ = _send(spec, 'GET', send_url, send_query, headers, cookies, None, timeout, label)
        except APICallError as e:
            stopped, truncated = f'page {pages + 1}: {e}', True
            break
        seen.add(resp.url)
        page_body = _parse_body(resp)
        page_rows, _ = paging.items_of(page_body, path) if path or isinstance(page_body, list) else (None, '')
        if page_rows is None:
            stopped = f'page {pages + 1} has no row array; stopped'
            break
        pages += 1
        collected.extend(page_rows)
        if mode == 'page':
            page_no += 1
        elif mode == 'offset':
            offset += len(page_rows)
        if not page_rows:
            break
    if len(collected) > max_items:
        collected, truncated = collected[:max_items], True
    out.update(body=paging.with_items(body, path, collected), pages=pages, items=len(collected), truncated=truncated)
    if stopped:
        out['stopped'] = stopped
    if truncated and continuation:
        if 'url' in continuation:
            out['next_page'] = continuation['url']
        else:
            wire_to_arg = {p['name']: p['arg'] for p in spec.get('params') or [] if p.get('in') == 'query'}
            out['next_arguments'] = {wire_to_arg.get(k, k): v for k, v in continuation.items()}
    return out


class ImportedAPITool(BaseMCPTool):
    """A tool imported from an OpenAPI / Swagger document or a GraphQL schema."""

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config or {})
        self._spec = dict(self.config.get('api_import') or {})

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema') or {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema') or {}

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return call(self._spec, arguments or {})
