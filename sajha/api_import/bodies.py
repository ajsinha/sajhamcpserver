"""
SAJHA MCP Server — API Import: multipart and binary request bodies.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

An operation whose request body is ``multipart/form-data`` or binary
(``application/octet-stream``, or any other media type whose schema is a binary string) is
imported with its file content as a **file value**: an object holding exactly one of
``content_base64`` (the bytes, base64), ``text`` (UTF-8 text) or ``path`` (a file in the
storage backend under one of ``api_import.file_roots``; ``{user}`` in a root is the calling
user's id), plus an optional ``filename`` and ``content_type``.

At parse time :func:`multipart_schema` / :data:`FILE_SCHEMA` shape the tool's input schema;
at call time :func:`encode_multipart` and :func:`encode_binary` build the request body and
refuse, before any connection is made, a body larger than ``api_import.max_upload_bytes``.
"""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import posixpath
import re
import secrets
from typing import Any, Dict, List, Optional, Tuple

from sajha.api_import import settings

MULTIPART = 'multipart/form-data'

FILE_SCHEMA: Dict[str, Any] = {
    'type': 'object',
    'description': ('File content: exactly one of content_base64 (the bytes, base64), text (UTF-8 text) '
                    'or path (a file in the server storage under api_import.file_roots); filename and '
                    'content_type are optional.'),
    'properties': {
        'content_base64': {'type': 'string', 'contentEncoding': 'base64',
                           'description': 'The file bytes, base64-encoded'},
        'text': {'type': 'string', 'description': 'The file content as UTF-8 text'},
        'path': {'type': 'string', 'description': 'A storage path under one of the configured file roots'},
        'filename': {'type': 'string', 'description': 'The file name sent with the part'},
        'content_type': {'type': 'string', 'description': 'The media type of the file'},
    },
    'additionalProperties': False,
}

_SOURCES = ('content_base64', 'text', 'path')
_USER_SAFE = re.compile(r'[^A-Za-z0-9_.@-]')


class BodyError(ValueError):
    """A file argument or body cannot be sent (bad value, refused path, too large)."""


# ── parse time ───────────────────────────────────────────────────────

def is_binary_schema(schema: Any) -> bool:
    """A (converted) schema that describes raw bytes: a string with format binary/base64 or a
    contentMediaType / contentEncoding (OpenAPI 3.1)."""
    if not isinstance(schema, dict):
        return False
    t = schema.get('type')
    is_string = t == 'string' or (isinstance(t, list) and 'string' in t)
    return is_string and (schema.get('format') in ('binary', 'base64')
                          or 'contentMediaType' in schema or 'contentEncoding' in schema)


def is_binary_body(schema: Any) -> bool:
    """A binary body: no schema at all, or a binary string."""
    return not schema or (isinstance(schema, dict) and set(schema) <= {'description'}) or is_binary_schema(schema)


def file_schema(description: str = '') -> Dict[str, Any]:
    out = json.loads(json.dumps(FILE_SCHEMA))
    if description:
        out['description'] = f"{description} ({out['description']})"
    return out


def multipart_schema(schema: Dict[str, Any], encoding: Optional[Dict[str, Any]] = None
                     ) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, str]]:
    """(input schema, field kinds, part content types) for a multipart body schema.

    A binary property becomes a file value (``kind: file``), an array of binary strings an
    array of file values (``files``); everything else is sent as a text part (``value``) or,
    for objects and arrays, as JSON (``json``)."""
    out = dict(schema or {})
    out.setdefault('type', 'object')
    props = dict(out.get('properties') or {})
    kinds: Dict[str, str] = {}
    for name, prop in props.items():
        desc = prop.get('description', '') if isinstance(prop, dict) else ''
        if is_binary_schema(prop):
            props[name] = file_schema(desc)
            kinds[name] = 'file'
        elif isinstance(prop, dict) and prop.get('type') == 'array' and is_binary_schema(prop.get('items')):
            props[name] = {**{k: v for k, v in prop.items() if k != 'items'}, 'items': file_schema()}
            kinds[name] = 'files'
        elif isinstance(prop, dict) and prop.get('type') in ('object', 'array'):
            kinds[name] = 'json'
        else:
            kinds[name] = 'value'
    out['properties'] = props
    part_types = {}
    for name, enc in (encoding or {}).items():
        ct = (enc or {}).get('contentType') if isinstance(enc, dict) else None
        if isinstance(ct, str) and ct and ',' not in ct and '*' not in ct:
            part_types[str(name)] = ct.strip()
    return out, kinds, part_types


# ── call time ────────────────────────────────────────────────────────

def _caller_id() -> str:
    try:
        from sajha.observability.caller import current
        return current().user_id or 'anonymous'
    except Exception:
        return 'anonymous'


def _roots() -> List[str]:
    out = []
    user = _caller_id()
    for root in settings.file_roots():
        if '{user}' in root:
            if not user or user == 'anonymous':
                continue                          # a per-user root needs a known caller
            root = root.replace('{user}', _USER_SAFE.sub('_', user))
        out.append(posixpath.normpath(root).strip('/'))
    return out


def resolve_path(path: str) -> str:
    """The storage path ``path`` names, when it lies under a file root; raises BodyError."""
    roots = _roots()
    if not roots and settings.file_roots():
        raise BodyError('file paths are not under a folder you may send files from: the file roots are '
                        'per user and this caller is not identified (api_import.file_roots)')
    if not roots:
        raise BodyError('file paths are not enabled on this server (api_import.file_roots is empty); '
                        'send content_base64 or text instead')
    raw = str(path or '').replace('\\', '/')
    if not raw.strip() or '\0' in raw or raw.startswith('/') or '..' in raw.split('/') or re.match(r'^[A-Za-z]:', raw):
        raise BodyError(f'file path {path!r} must be a relative storage path without ".."')
    norm = posixpath.normpath(raw).strip('/')
    for root in roots:
        if norm == root or norm.startswith(root + '/'):
            return norm
    raise BodyError(f'file path {path!r} is not under a folder you may send files from '
                    f'(api_import.file_roots)')


def _read_path(path: str, budget: int) -> bytes:
    rel = resolve_path(path)
    from sajha.core.storage import LocalStorageBackend, confined_path, get_storage
    st = get_storage()
    if isinstance(st, LocalStorageBackend):        # symbolic links must not lead out of the root
        root = next(r for r in _roots() if rel == r or rel.startswith(r + '/'))
        try:
            real = confined_path(st.get_local_path(root), rel[len(root):].lstrip('/') or '.')
        except ValueError as e:
            raise BodyError(str(e))
        if not real.is_file():
            raise BodyError(f'file {path!r} does not exist')
        if real.stat().st_size > budget:
            raise BodyError(_too_large(budget))
        return real.read_bytes()
    if not st.exists(rel):
        raise BodyError(f'file {path!r} does not exist')
    data = st.read_bytes(rel)
    if len(data) > budget:
        raise BodyError(_too_large(budget))
    return data


def _too_large(budget: int) -> str:
    return (f'the request body would exceed {settings.max_upload_bytes()} bytes '
            f'(api_import.max_upload_bytes); {max(0, budget)} bytes were left for this file')


def file_bytes(value: Any, budget: int) -> Tuple[bytes, str, str]:
    """(bytes, filename, content type) of one file value, within ``budget`` bytes."""
    if isinstance(value, str):
        value = {'text': value}
    if not isinstance(value, dict):
        raise BodyError('a file value must be an object with content_base64, text or path')
    given = [k for k in _SOURCES if value.get(k) not in (None, '')]
    if len(given) != 1:
        raise BodyError('a file value needs exactly one of content_base64, text or path')
    source = given[0]
    if source == 'content_base64':
        encoded = str(value['content_base64']).strip()
        if len(encoded) * 3 // 4 > budget + 3:
            raise BodyError(_too_large(budget))
        standard = re.sub(r'\s+', '', encoded).replace('-', '+').replace('_', '/')   # the URL-safe alphabet too
        try:
            data = base64.b64decode(standard + '=' * (-len(standard) % 4), validate=True)
        except (binascii.Error, ValueError):
            raise BodyError('content_base64 is not valid base64')
    elif source == 'text':
        data = str(value['text']).encode('utf-8')
    else:
        data = _read_path(str(value['path']), budget)
    if len(data) > budget:
        raise BodyError(_too_large(budget))
    filename = str(value.get('filename') or (posixpath.basename(str(value['path'])) if source == 'path' else '') or '')
    ctype = str(value.get('content_type') or '')
    if not ctype and filename:
        ctype = mimetypes.guess_type(filename)[0] or ''
    return data, filename, ctype


def encode_binary(value: Any, declared: str) -> Tuple[bytes, str]:
    """(body, content type) of a binary body."""
    data, _, ctype = file_bytes(value, settings.max_upload_bytes())
    concrete = declared and '*' not in declared
    return data, (declared if concrete else (ctype or 'application/octet-stream'))


def _quote(text: str) -> str:
    return text.replace('\\', '\\\\').replace('"', '\\"').replace('\r', ' ').replace('\n', ' ')


def _scalar(v: Any) -> str:
    if isinstance(v, bool):
        return 'true' if v else 'false'
    return '' if v is None else str(v)


def encode_multipart(value: Any, kinds: Dict[str, str], part_types: Optional[Dict[str, str]] = None
                     ) -> Tuple[bytes, str]:
    """(body, content type with boundary) of a multipart/form-data body."""
    if not isinstance(value, dict):
        raise BodyError('a multipart body must be an object of fields')
    part_types = part_types or {}
    limit = settings.max_upload_bytes()
    boundary = 'sajha-' + secrets.token_hex(16)
    out = bytearray()

    def part(name: str, data: bytes, ctype: str = '', filename: Optional[str] = None) -> None:
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{_quote(name)}"'
        if filename is not None:
            head += f'; filename="{_quote(filename or name)}"'
        head += '\r\n'
        if ctype:
            head += f'Content-Type: {ctype}\r\n'
        out.extend(head.encode('utf-8') + b'\r\n' + data + b'\r\n')
        if len(out) > limit:
            raise BodyError(_too_large(0))

    for name, v in value.items():
        if v is None:
            continue
        kind = kinds.get(name, 'json' if isinstance(v, (dict, list)) else 'value')
        if kind in ('file', 'files'):
            for item in (v if isinstance(v, list) else [v]):
                data, filename, ctype = file_bytes(item, limit - len(out))
                part(name, data, ctype or part_types.get(name) or 'application/octet-stream', filename or name)
        elif kind == 'json':
            part(name, json.dumps(v).encode(), part_types.get(name) or 'application/json')
        elif isinstance(v, list):
            for item in v:
                part(name, _scalar(item).encode('utf-8'), part_types.get(name, ''))
        else:
            part(name, _scalar(v).encode('utf-8'), part_types.get(name, ''))
    out.extend(f'--{boundary}--\r\n'.encode())
    if len(out) > limit:
        raise BodyError(_too_large(0))
    return bytes(out), f'{MULTIPART}; boundary={boundary}'
