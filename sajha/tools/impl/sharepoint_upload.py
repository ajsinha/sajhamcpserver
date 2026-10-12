"""
SAJHA MCP Server - SharePoint: large uploads through Graph upload sessions, and the delegated grant.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Upload sessions (https://learn.microsoft.com/graph/api/driveitem-createuploadsession): a file larger
than the simple-upload limit is sent in chunks to a pre-authenticated ``uploadUrl``:

* ``POST {item}:/createUploadSession`` (with the tool's token) returns ``uploadUrl``;
* each chunk is a ``PUT`` to that URL with ``Content-Range: bytes start-end/total`` and **no**
  ``Authorization`` header (the URL is the credential; Graph documents that sending the token there
  can fail the request); chunks are multiples of 320 KiB, at most 60 MiB;
* ``202 Accepted`` answers with ``nextExpectedRanges``; the last chunk answers ``200``/``201`` with
  the driveItem;
* a chunk that fails (network error, 5xx, 429, 416) is retried after asking the session which ranges
  it still expects (``GET uploadUrl``), so an upload resumes where Graph says it stopped. When the
  retries run out the upload is *interrupted*, not cancelled: the error carries the ``uploadUrl`` and
  a later call with ``resume_upload_url`` and the same content sends only the missing ranges. Any
  other refusal cancels the session (``DELETE uploadUrl``).

An upload URL is only ever accepted on ``https`` and on the site's own host (or ``*.sharepoint.com``
of the same tenant, or ``graph.microsoft.com``), so a caller cannot make the tool send file content
elsewhere. Sizes are capped by the tool config's ``max_upload_bytes``.

The delegated grant: with ``authentication.type: delegated`` the tools call Graph **as the caller**,
with the token of the caller's connected Microsoft account (docs/architecture/Connected Accounts.md),
instead of the app registration's client-credentials token. The config then carries
``"auth": {"connected_account": "microsoft", "scopes": [...]}`` (set from the ``authentication``
block), so every call is bound to the caller's link; a caller without one is asked to connect.

Docs: docs/tools/enterprise/SharePoint Tool Reference Guide.md
"""

import logging
import re
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

CHUNK_UNIT = 320 * 1024                     # Graph: every chunk but the last is a multiple of 320 KiB
MAX_CHUNK = 60 * 1024 * 1024                # Graph: at most 60 MiB per request
DEFAULT_CHUNK = 16 * CHUNK_UNIT             # 5 MiB
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024       # at or below: one PUT .../content
DEFAULT_MAX_UPLOAD = 100 * 1024 * 1024      # tool config max_upload_bytes overrides
UPLOAD_TIMEOUT = 120
RETRIES = 3
DELEGATED = 'delegated'
DEFAULT_DELEGATED_SCOPES = ['Sites.ReadWrite.All']


class UploadInterrupted(RuntimeError):
    """The upload stopped part-way; ``upload_url`` resumes it."""

    def __init__(self, message: str, upload_url: str, uploaded: int, total: int):
        super().__init__(message)
        self.upload_url, self.uploaded, self.total = upload_url, uploaded, total


# ── sizes ───────────────────────────────────────────────────────────

def chunk_size(config: Dict[str, Any]) -> int:
    """The tool config's ``upload_chunk_bytes``, rounded down to a multiple of 320 KiB, 320 KiB-60 MiB."""
    try:
        want = int(config.get('upload_chunk_bytes') or DEFAULT_CHUNK)
    except (TypeError, ValueError):
        want = DEFAULT_CHUNK
    return max(CHUNK_UNIT, min(MAX_CHUNK, want - want % CHUNK_UNIT))


def max_upload_bytes(config: Dict[str, Any]) -> int:
    try:
        return max(1, int(config.get('max_upload_bytes') or DEFAULT_MAX_UPLOAD))
    except (TypeError, ValueError):
        return DEFAULT_MAX_UPLOAD


# ── upload URLs ─────────────────────────────────────────────────────

def _tenant_of(site_host: str) -> str:
    """``contoso`` for contoso.sharepoint.com and contoso-my.sharepoint.com."""
    head = (site_host or '').lower().split('.', 1)[0]
    return head[:-3] if head.endswith('-my') else head


def check_upload_url(url: str, site_url: str) -> str:
    """``url`` when it may receive file content: https, on the site's host, on a sharepoint.com host of
    the same tenant, or graph.microsoft.com. Raises ValueError otherwise."""
    p = urllib.parse.urlsplit(url or '')
    host = (p.hostname or '').lower()
    if p.scheme != 'https' or not host or p.username or p.password:
        raise ValueError('an upload URL must be an https URL without credentials')
    site_host = (urllib.parse.urlsplit(site_url or '').hostname or '').lower()
    tenant = _tenant_of(site_host)
    allowed = host == site_host or host == 'graph.microsoft.com' or (
        tenant and site_host.endswith('.sharepoint.com')
        and host in (f'{tenant}.sharepoint.com', f'{tenant}-my.sharepoint.com'))
    if not allowed:
        raise ValueError(f'upload URL host {host} is not this SharePoint site\'s ({site_host})')
    return url


def _ranges_start(ranges: List[str], total: int) -> Optional[int]:
    """The first byte Graph still expects, from ``nextExpectedRanges`` (``["26-"]``, ``["0-99", ...]``)."""
    starts = []
    for r in ranges or []:
        m = re.match(r'^\s*(\d+)\s*-', str(r))
        if m:
            starts.append(int(m.group(1)))
    if not starts:
        return None
    return min(min(starts), total)


def _status(upload_url: str, http) -> Tuple[Optional[int], Optional[List[str]]]:
    """(HTTP status, nextExpectedRanges) of an upload session."""
    resp = http('GET', upload_url, headers={'Accept': 'application/json'}, timeout=UPLOAD_TIMEOUT)
    if resp.status_code >= 400:
        return resp.status_code, None
    try:
        return resp.status_code, list(resp.json().get('nextExpectedRanges') or [])
    except ValueError:
        return resp.status_code, None


def _cancel(upload_url: str, http) -> None:
    try:
        http('DELETE', upload_url, timeout=UPLOAD_TIMEOUT)
    except Exception as e:
        logger.debug(f'sharepoint: cancelling an upload session failed: {e}')


def _default_http(method: str, url: str, **kw):
    return requests.request(method, url, **kw)


def send_chunks(upload_url: str, content: bytes, *, chunk: int = DEFAULT_CHUNK, start: int = 0,
                retries: int = RETRIES, http: Callable = _default_http,
                sleep: Optional[Callable[[float], None]] = None) -> Dict[str, Any]:
    """PUT ``content[start:]`` to ``upload_url`` in chunks; returns the driveItem. Resumes from the
    session's ``nextExpectedRanges`` after a failed chunk; raises UploadInterrupted when it cannot."""
    sleep = sleep or time.sleep
    total = len(content)
    offset = start
    failures = 0
    budget = (total // max(1, chunk) + 1) * (retries + 2) + 8      # bounds a session that never moves on
    while True:
        budget -= 1
        if budget < 0:
            raise UploadInterrupted(f'upload interrupted after {offset} of {total} bytes: the session stopped '
                                    f'accepting ranges', upload_url, offset, total)
        if offset >= total:
            # nothing left to send but no driveItem yet: ask the session
            code, ranges = _status(upload_url, http)
            nxt = _ranges_start(ranges or [], total)
            if nxt is None or nxt >= total:
                raise UploadInterrupted('Graph has every byte but did not return the file; check the folder',
                                        upload_url, total, total)
            offset = nxt
        end = min(offset + chunk, total) - 1
        piece = content[offset:end + 1]
        headers = {'Content-Length': str(len(piece)), 'Content-Range': f'bytes {offset}-{end}/{total}'}
        try:
            resp = http('PUT', upload_url, data=piece, headers=headers, timeout=UPLOAD_TIMEOUT)
            code = resp.status_code
        except requests.RequestException as e:
            resp, code = None, None
            logger.info(f'sharepoint: chunk {offset}-{end} failed: {e}')
        if code in (200, 201):
            try:
                return resp.json()
            except ValueError:
                return {}
        if code == 202:
            failures = 0
            try:
                nxt = _ranges_start(resp.json().get('nextExpectedRanges') or [], total)
            except ValueError:
                nxt = None
            offset = end + 1 if nxt is None else nxt
            continue
        if code == 404:
            raise RuntimeError('the upload session has expired or was cancelled; start the upload again')
        if code is None or code >= 500 or code in (408, 416, 429):
            failures += 1
            if failures > retries:
                raise UploadInterrupted(
                    f'upload interrupted after {offset} of {total} bytes (HTTP {code or "connection error"}); '
                    f'call upload again with resume_upload_url and the same content to send the rest',
                    upload_url, offset, total)
            retry_after = 0.0
            if resp is not None:
                try:
                    retry_after = float(resp.headers.get('Retry-After') or 0)
                except (TypeError, ValueError):
                    retry_after = 0.0
            sleep(min(30.0, max(retry_after, 0.5 * 2 ** (failures - 1))))
            status, ranges = _status(upload_url, http)
            if status == 404:
                raise RuntimeError('the upload session has expired; start the upload again')
            nxt = _ranges_start(ranges or [], total)
            if nxt is not None:
                offset = nxt
            continue
        # any other refusal (400, 401, 403, 409 name conflict, 413 ...): give the session back
        detail = ''
        try:
            detail = (resp.json().get('error') or {}).get('message', '')
        except Exception:
            detail = (getattr(resp, 'text', '') or '')[:200]
        _cancel(upload_url, http)
        raise RuntimeError(f'Microsoft Graph refused the upload: HTTP {code} {detail}'.rstrip())


def upload_large(tool, target: str, file_name: str, content: bytes, conflict: str,
                 resume_url: str = '', http: Callable = _default_http,
                 sleep: Optional[Callable[[float], None]] = None) -> Dict[str, Any]:
    """Upload ``content`` to ``target`` (a library-relative path) through an upload session."""
    size = chunk_size(tool.config)
    if resume_url:
        upload_url = check_upload_url(resume_url, tool.site_url)
        status, ranges = _status(upload_url, http)
        if status == 404 or status is None or ranges is None:
            raise RuntimeError('the upload session to resume has expired or is unknown; start the upload again')
        start = _ranges_start(ranges, len(content))
        start = 0 if start is None else start
    else:
        session = tool._graph('POST', f'{tool.item_ref(target)}/createUploadSession',
                              json_body={'item': {'@microsoft.graph.conflictBehavior': conflict, 'name': file_name}})
        upload_url = check_upload_url(str(session.get('uploadUrl') or ''), tool.site_url)
        start = 0
    return send_chunks(upload_url, content, chunk=size, start=start, http=http, sleep=sleep)


# ── reading a file from the storage backend ─────────────────────────

def read_source(config: Dict[str, Any], source_path: str, limit: int) -> bytes:
    """A file under one of the tool config's ``upload_roots`` (storage-backend folders; ``{user}`` is the
    caller). Empty roots (the default) refuse every path: content then travels inline only."""
    roots = config.get('upload_roots') or []
    if isinstance(roots, str):
        roots = [r.strip() for r in roots.split(',') if r.strip()]
    if not roots:
        raise ValueError("'source_path' is not enabled: the tool config has no upload_roots")
    path = (source_path or '').strip().replace('\\', '/')
    parts = [p for p in path.split('/') if p and p != '.']
    if path.startswith('/') or not parts or '..' in parts:
        raise ValueError("'source_path' must be a relative path without '..'")
    rel = '/'.join(parts)
    user = ''
    try:
        from sajha.observability.caller import current
        user = current().user_id or ''
    except Exception:
        pass
    for root in roots:
        root = str(root).strip().strip('/')
        if '{user}' in root:
            if not user or user == 'anonymous' or '/' in user:
                continue
            root = root.replace('{user}', user)
        if rel == root or rel.startswith(root + '/'):
            from sajha.core.storage import get_storage
            st = get_storage()
            if not st.exists(rel):
                raise ValueError(f"'source_path' {rel} does not exist")
            data = st.read_bytes(rel)
            if len(data) > limit:
                raise ValueError(f'file too large: {len(data)} bytes (limit {limit}, max_upload_bytes)')
            return data
    raise ValueError(f"'source_path' {rel} is not under one of the upload roots")


# ── the delegated grant ─────────────────────────────────────────────

def delegated_auth_block(authentication: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The ``auth`` block (connected-account binding) for a delegated ``authentication`` block, else None."""
    a = authentication or {}
    if (a.get('type') or a.get('auth_type')) != DELEGATED:
        return None
    scopes = a.get('scopes') or DEFAULT_DELEGATED_SCOPES
    if isinstance(scopes, str):
        scopes = scopes.replace(',', ' ').split()
    return {'connected_account': str(a.get('connected_account') or 'microsoft'), 'scopes': [str(s) for s in scopes]}


def delegated_token(provider: str) -> str:
    """The caller's access token for ``provider``, bound to this call by sajha.accounts.injection."""
    from sajha.accounts.injection import current_token
    return current_token(provider).access_token


def refresh_delegated(provider: str, tool_name: str, final: bool) -> str:
    """After Graph refused the caller's token: refresh it once (``final`` False), or mark the link for
    re-connection and raise ConnectedAccountRequired (``final`` True)."""
    from sajha.accounts.injection import current_token, replace_token
    from sajha.accounts.service import get_service
    token = current_token(provider)
    svc = get_service()
    if not final:
        token = svc.refresh_after_rejection(token, tool=tool_name)
        replace_token(token)
        return token.access_token
    svc.mark_rejected(token)
    raise svc.required(provider, 'reauth_required', token.user_id, tool=tool_name)
