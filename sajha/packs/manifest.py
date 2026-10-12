"""
SAJHA MCP Server — provider packs: the pack format.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A pack is a folder::

    <id>/pack.json        the manifest (below)
    <id>/<spec file>      the service's OpenAPI 3.x or Swagger 2.0 document, bundled (never fetched)
    <id>/<licence file>   the licence the spec is published under

``pack.json``::

    {
      "format": 1,
      "id": "box",                         # [a-z][a-z0-9_-]{0,31}
      "title": "Box", "version": "1.0.0", "description": "...",
      "provider": {                        # the connected-account preset
        "id": "box",                       # the provider id users link (default: the pack id)
        "template": "",                    # a built-in template, or empty for a custom provider
        ... provider fields: authorize_url, token_url, scopes, api_hosts, ...
      },
      "install_fields": ["client_id", "client_secret_ref"],   # what the administrator supplies
      "api": {
        "spec": "openapi.json", "spec_sha256": "<hex>",
        "prefix": "box", "base_url": "https://api.box.com/2.0", "folder": "box",
        "security_scheme": "OAuth2Security",   # the spec's scheme bound to the account ('' -> added globally)
        "scopes": ["root_readwrite"],          # scopes each tool asks of the user's link
        "operations": ["GET /users/me", ...]   # the reviewed selection (API Import operation keys)
      },
      "source": {"url": "...", "revision": "<commit>", "retrieved": "YYYY-MM-DD",
                 "licence": "Apache-2.0", "licence_file": "LICENSE", "changes": "..."}
    }

Secrets never appear in a manifest: the client id and the client-secret *reference*
(``env:NAME``, ``file:/path``, ``db:...``) are install inputs.

Design: docs/architecture/Connected Accounts.md §11
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

FORMAT = 1
PACK_ID = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
OP_KEY = re.compile(r'^(GET|PUT|POST|DELETE|PATCH|HEAD|OPTIONS|TRACE) /\S*$')
#: Fields an administrator may supply when installing (everything else comes from the manifest).
INSTALL_FIELDS = ('client_id', 'client_secret_ref', 'tenant', 'redirect_uri')
#: Provider fields a manifest may not set: the install inputs, and switches that belong to the operator.
MANIFEST_FORBIDDEN = ('client_id', 'client_secret_ref', 'client_secret', 'redirect_uri', 'enabled')
#: Licences whose terms allow bundling a (trimmed) copy of the spec with SAJHA.
PERMISSIVE_LICENCES = ('MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'ISC', 'CC0-1.0', 'CC-BY-4.0')
MAX_SPEC_BYTES = 5 * 1024 * 1024


class PackError(ValueError):
    """A pack that cannot be read or installed; ``status`` is the HTTP status the API answers."""

    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


@dataclass
class Pack:
    id: str
    title: str
    version: str
    description: str
    provider: Dict[str, Any]
    install_fields: List[str]
    api: Dict[str, Any]
    source: Dict[str, Any]
    folder: Path
    spec_text: str = field(repr=False, default='')
    licence_text: str = field(repr=False, default='')

    @property
    def provider_id(self) -> str:
        return str(self.provider.get('id') or self.id)

    @property
    def provider_fields(self) -> Dict[str, Any]:
        """The preset's provider fields (without the id)."""
        return {k: v for k, v in self.provider.items() if k != 'id'}

    @property
    def operations(self) -> List[str]:
        return list(self.api.get('operations') or [])

    @property
    def spec_sha256(self) -> str:
        return hashlib.sha256(self.spec_text.encode('utf-8')).hexdigest()

    def summary(self) -> Dict[str, Any]:
        return {'id': self.id, 'title': self.title, 'version': self.version, 'description': self.description,
                'provider': self.provider_id, 'template': str(self.provider.get('template') or ''),
                'prefix': self.api.get('prefix'), 'base_url': self.api.get('base_url'),
                'operations': self.operations, 'scopes': list(self.api.get('scopes') or []),
                'install_fields': list(self.install_fields),
                'source': dict(self.source), 'spec_sha256': self.spec_sha256}


def _need(d: Dict[str, Any], key: str, where: str, kind=str):
    v = d.get(key)
    if not isinstance(v, kind) or (kind is str and not v.strip()) or (kind is list and not v):
        raise PackError(f'{where}: "{key}" is required ({kind.__name__})')
    return v


def _inside(folder: Path, name: str, where: str) -> Path:
    if not isinstance(name, str) or not name or '/' in name or '\\' in name or name.startswith('.'):
        raise PackError(f'{where}: a file name in the pack folder, got {name!r}')
    p = folder / name
    if not p.is_file():
        raise PackError(f'{where}: {name} is not in the pack')
    return p


def parse(doc: Any, folder: Path) -> Pack:
    """A Pack from a manifest document and its folder; raises PackError naming the problem."""
    from sajha.accounts.providers import PROVIDER_ID, _FIELDS
    where = f'pack {folder.name}'
    if not isinstance(doc, dict):
        raise PackError(f'{where}: pack.json must be an object')
    if doc.get('format') != FORMAT:
        raise PackError(f'{where}: "format" must be {FORMAT}')
    pid = _need(doc, 'id', where)
    if not PACK_ID.match(pid):
        raise PackError(f'{where}: id {pid!r}: a lower-case letter, then letters, digits, - or _ (at most 32)')
    if pid != folder.name:
        raise PackError(f'{where}: id {pid!r} must equal the folder name')
    where = f'pack {pid}'
    provider = doc.get('provider')
    if not isinstance(provider, dict):
        raise PackError(f'{where}: "provider" (the connected-account preset) is required')
    prov_id = str(provider.get('id') or pid)
    if not PROVIDER_ID.match(prov_id):
        raise PackError(f'{where}: provider id {prov_id!r} is not valid')
    bad = sorted(set(provider) & set(MANIFEST_FORBIDDEN))
    if bad:
        raise PackError(f'{where}: provider may not set {", ".join(bad)} (install inputs or operator switches)')
    unknown = sorted(set(provider) - set(_FIELDS) - {'id'})
    if unknown:
        raise PackError(f'{where}: unknown provider field(s) {", ".join(unknown)}')
    install_fields = doc.get('install_fields') or ['client_id', 'client_secret_ref']
    if not isinstance(install_fields, list) or set(install_fields) - set(INSTALL_FIELDS):
        raise PackError(f'{where}: install_fields must be a list of {", ".join(INSTALL_FIELDS)}')
    api = doc.get('api')
    if not isinstance(api, dict):
        raise PackError(f'{where}: "api" is required')
    from sajha.api_import.naming import valid_prefix
    prefix = _need(api, 'prefix', f'{where} api')
    if not valid_prefix(prefix):
        raise PackError(f'{where}: api.prefix {prefix!r} must be 2-31 characters: a lowercase letter, then '
                        f'lowercase letters, digits or underscores')
    base_url = _need(api, 'base_url', f'{where} api')
    if not base_url.startswith(('https://', 'http://127.0.0.1', 'http://localhost')):
        raise PackError(f'{where}: api.base_url must be https://')
    ops = _need(api, 'operations', f'{where} api', list)
    for op in ops:
        if not isinstance(op, str) or not OP_KEY.match(op):
            raise PackError(f'{where}: operation {op!r} must be "METHOD /path" (an API Import operation key)')
    if len(set(ops)) != len(ops):
        raise PackError(f'{where}: an operation is listed twice')
    scopes = api.get('scopes') or []
    if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
        raise PackError(f'{where}: api.scopes must be a list of strings')
    spec_file = _inside(folder, _need(api, 'spec', f'{where} api'), f'{where} api.spec')
    raw = spec_file.read_bytes()
    if len(raw) > MAX_SPEC_BYTES:
        raise PackError(f'{where}: the bundled spec is larger than {MAX_SPEC_BYTES} bytes')
    spec_text = raw.decode('utf-8')
    want = str(api.get('spec_sha256') or '')
    got = hashlib.sha256(spec_text.encode('utf-8')).hexdigest()
    if want != got:
        raise PackError(f'{where}: the bundled spec does not match api.spec_sha256 (have {got})')
    source = doc.get('source')
    if not isinstance(source, dict):
        raise PackError(f'{where}: "source" (where the spec came from and its licence) is required')
    licence = _need(source, 'licence', f'{where} source')
    if licence not in PERMISSIVE_LICENCES:
        raise PackError(f'{where}: source.licence {licence!r} is not one SAJHA bundles '
                        f'({", ".join(PERMISSIVE_LICENCES)})')
    _need(source, 'url', f'{where} source')
    lic_file = _inside(folder, _need(source, 'licence_file', f'{where} source'), f'{where} source.licence_file')
    return Pack(id=pid, title=str(doc.get('title') or pid), version=str(doc.get('version') or '1.0.0'),
                description=str(doc.get('description') or ''), provider={**provider, 'id': prov_id},
                install_fields=[str(x) for x in install_fields], api=dict(api), source=dict(source),
                folder=folder, spec_text=spec_text, licence_text=lic_file.read_text(encoding='utf-8'))


def load(folder: Path) -> Pack:
    mf = folder / 'pack.json'
    if not mf.is_file():
        raise PackError(f'pack {folder.name}: no pack.json')
    try:
        doc = json.loads(mf.read_text(encoding='utf-8'))
    except ValueError as e:
        raise PackError(f'pack {folder.name}: pack.json is not JSON: {e}')
    return parse(doc, folder)


def bundled_dir() -> Path:
    return Path(__file__).resolve().parent / 'bundled'


def pack_dirs(extra: Optional[List[str]] = None) -> List[Path]:
    """The folders packs are read from: the bundled ones, then ``packs.dirs``, then ``extra``."""
    dirs = [bundled_dir()]
    try:
        from sajha.core.config import _get, parse_list
        configured = parse_list(_get('packs.dirs', '') or '')
    except Exception:
        configured = []
    for d in list(configured) + list(extra or []):
        p = Path(d)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p not in dirs:
            dirs.append(p)
    return dirs


def discover(extra: Optional[List[str]] = None):
    """(packs by id, problems by folder name): every pack folder in :func:`pack_dirs`; the first
    folder that defines an id wins."""
    packs: Dict[str, Pack] = {}
    problems: Dict[str, str] = {}
    for root in pack_dirs(extra):
        if not root.is_dir():
            continue
        for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(('.', '_'))):
            if folder.name in packs:
                continue
            try:
                packs[folder.name] = load(folder)
            except PackError as e:
                problems[folder.name] = str(e)
            except Exception as e:                     # unreadable file and the like
                problems[folder.name] = f'pack {folder.name}: {e.__class__.__name__}: {e}'
    return packs, problems
