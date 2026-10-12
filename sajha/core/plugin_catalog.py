"""
SAJHA MCP Server — the plugin catalog: signed plugins from configured sources, installed through
review and approval.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``plugins.catalog.sources`` lists where packages come from, tried in order:

* a local folder (``/srv/sajha-catalog`` or ``catalog/plugins``): each sub-folder holding a
  ``plugin.json`` is a package, and so is each ``*.zip``;
* ``storage:<prefix>``: the same, under a prefix of the storage backend (local, S3, Azure, GCS);
* ``https://…/index.json``: a remote index ``{"plugins": [{"name", "version", "publisher",
  "description", "url"}]}`` whose ``url`` (relative to the index, or absolute) is a ``.zip``;
  the index and every package are fetched through the outbound fetch guard
  (``sajha/core/outbound.py``).

A package is listed with its signature verdict (``sajha/core/plugin_signing.py``); only a
``trusted`` one can be installed. Installing follows the review-and-approve gate of Describe a
tool (docs/architecture/Tool Generation.md §6):

    review(source, ref)   the package is fetched, verified and kept as a draft in the state store,
                          bound to its package hash; the reviewer sees the manifest and every file
    install(draft, hash, approve)
                          refused unless approve is true, the hash is the draft's, the package
                          fetched again has that same hash and is still trusted, the name is free
                          (or ``replace`` is set), and the policy engine allows the pseudo tool
                          call ``studio.deploy`` with ``{"tool": "plugin:<name>", "kind": "plugin"}``
                          (``require_approval`` sends it to the Approvals page); then the files are
                          written to ``config.plugins.dir`` and the plugin is loaded

Every review and install is audited (``plugins.catalog.review``, ``plugins.catalog.install``).
Design: docs/security/Security Model.md, "Plugins".
"""

from __future__ import annotations

import io
import json
import logging
import os
import posixpath
import re
import secrets
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from sajha.core import plugin_signing as S

logger = logging.getLogger(__name__)

DRAFT_PREFIX = 'plugins.catalog.draft:'
DEPLOY_ACTION = 'studio.deploy'
NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
MAX_FILES = 500
PREVIEW_BYTES = 64 * 1024          # per file shown on the review page
TEXT_SUFFIXES = ('.py', '.json', '.txt', '.md', '.yml', '.yaml', '.toml', '.cfg', '.ini', '.sig', '.csv')


class CatalogError(ValueError):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


# ── settings ─────────────────────────────────────────────────────────

def sources() -> List[str]:
    try:
        from sajha.core.config import _list
        return [str(s).strip() for s in _list('plugins.catalog.sources', []) if str(s).strip()]
    except Exception:
        return []


def max_package_bytes() -> int:
    try:
        from sajha.core.config import _int
        return max(1024, _int('plugins.catalog.max_package_bytes', 20 * 1024 * 1024))
    except Exception:
        return 20 * 1024 * 1024


def draft_ttl() -> int:
    try:
        from sajha.core.config import _int
        return max(300, _int('plugins.catalog.draft_ttl_seconds', 86400))
    except Exception:
        return 86400


def source_kind(src: str) -> str:
    if src.startswith('storage:'):
        return 'storage'
    if re.match(r'^https?://', src, re.I):
        return 'remote'
    return 'folder'


# ── fetching a package into a staging folder ─────────────────────────

def _safe_rel(name: str) -> str:
    rel = posixpath.normpath(name.replace('\\', '/'))
    if rel.startswith('/') or rel == '..' or rel.startswith('../') or re.match(r'^[A-Za-z]:', rel) or rel in ('', '.'):
        raise CatalogError(f'package entry {name!r} is outside the package')
    return rel


def _write_files(dest: Path, files: Dict[str, bytes]) -> None:
    if len(files) > MAX_FILES:
        raise CatalogError(f'the package has more than {MAX_FILES} files')
    total = sum(len(b) for b in files.values())
    if total > max_package_bytes():
        raise CatalogError(f'the package is larger than plugins.catalog.max_package_bytes ({max_package_bytes()})')
    for rel, data in files.items():
        p = dest / _safe_rel(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def _unzip(data: bytes) -> Dict[str, bytes]:
    cap = max_package_bytes()
    if len(data) > cap:
        raise CatalogError('the package archive is larger than plugins.catalog.max_package_bytes')
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise CatalogError('the package is not a zip archive')
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise CatalogError(f'the package has more than {MAX_FILES} files')
    out: Dict[str, bytes] = {}
    total = 0
    for i in infos:
        if (i.external_attr >> 16) & 0o170000 == 0o120000:
            raise CatalogError(f'{i.filename} is a symbolic link')
        rel = _safe_rel(i.filename)
        total += i.file_size
        if total > cap:
            raise CatalogError('the unpacked package is larger than plugins.catalog.max_package_bytes')
        with z.open(i) as f:
            blob = f.read(cap + 1)
        if len(blob) != i.file_size:
            raise CatalogError(f'{i.filename}: size does not match the archive directory')
        out[rel] = blob
    # a zip whose files sit in one top folder (name-1.0/plugin.json) is accepted too
    if 'plugin.json' not in out:
        tops = {k.split('/', 1)[0] for k in out}
        if len(tops) == 1 and all('/' in k for k in out):
            out = {k.split('/', 1)[1]: v for k, v in out.items()}
    return out


def _read_folder(path: Path) -> Dict[str, bytes]:
    root = path.resolve()
    out = {}
    for rel in S.package_files(root) + ([S.SIGNATURE_FILE] if (root / S.SIGNATURE_FILE).is_file() else []):
        p = (root / rel).resolve()
        if not p.is_relative_to(root):
            raise CatalogError(f'{rel} points outside the package')
        out[rel] = p.read_bytes()
    return out


def _fetch_url(url: str) -> bytes:
    from sajha.core import outbound
    if not re.match(r'^https?://', url, re.I):
        raise CatalogError(f'{url} is not an http(s) URL')
    try:
        r = outbound.request('GET', url, timeout=30.0, max_bytes=max_package_bytes())
    except outbound.Refused as e:
        raise CatalogError(f'refused by the outbound fetch guard: {e}', 403)
    except outbound.FetchError as e:
        raise CatalogError(f'fetching {outbound.safe_url(url)} failed: {e}', 502)
    if r.status_code != 200:
        raise CatalogError(f'fetching {outbound.safe_url(url)} answered HTTP {r.status_code}', 502)
    return r.content


def _remote_index(src: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(_fetch_url(src).decode('utf-8'))
    except CatalogError:
        raise
    except Exception as e:
        raise CatalogError(f'{src}: the index is not JSON: {e}')
    items = data.get('plugins') if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise CatalogError(f'{src}: the index has no "plugins" list')
    out = []
    for it in items:
        if isinstance(it, dict) and it.get('url') and it.get('name'):
            out.append({**{k: str(it.get(k, '')) for k in ('name', 'version', 'publisher', 'description')},
                        'ref': urljoin(src, str(it['url']))})
    return out


def _storage_prefix(src: str) -> str:
    prefix = posixpath.normpath(src[len('storage:'):].strip().strip('/'))
    if prefix in ('', '.') or prefix.startswith('..'):
        raise CatalogError(f'{src}: not a storage prefix')
    return prefix


def _refs(src: str) -> List[Dict[str, Any]]:
    """The packages a source offers: [{ref, ...hints}]."""
    kind = source_kind(src)
    if kind == 'remote':
        return _remote_index(src)
    if kind == 'storage':
        from sajha.core.storage import get_storage
        prefix = _storage_prefix(src)
        names = set()
        for path in get_storage().list_files(prefix):
            rest = path[len(prefix):].lstrip('/')
            if '/' not in rest and rest.endswith('.zip'):
                names.add(rest)
            elif rest.endswith('/plugin.json') and rest.count('/') == 1:
                names.add(rest.split('/', 1)[0])
        return [{'ref': n} for n in sorted(names)]
    root = Path(src)
    if not root.is_dir():
        raise CatalogError(f'{src}: no such folder')
    out = []
    for entry in sorted(os.listdir(root)):
        p = root / entry
        if p.is_symlink():
            continue
        if (p.is_dir() and (p / 'plugin.json').is_file()) or (p.is_file() and entry.endswith('.zip')):
            out.append({'ref': entry})
    return out


def _check_ref(src: str, ref: str) -> None:
    if src not in sources():
        raise CatalogError('that catalog source is not configured (plugins.catalog.sources)', 404)
    kind = source_kind(src)
    if kind == 'remote':
        if ref not in {r['ref'] for r in _remote_index(src)}:
            raise CatalogError('that package is not in the catalog index', 404)
    elif '/' in ref or '\\' in ref or ref in ('', '.', '..') or ref.startswith('.'):
        raise CatalogError('not a package of that source', 404)


def fetch(src: str, ref: str, dest: Path) -> None:
    """Materialise one package of ``src`` into the empty folder ``dest``."""
    kind = source_kind(src)
    if kind == 'remote':
        files = _unzip(_fetch_url(ref))
    elif kind == 'storage':
        from sajha.core.storage import get_storage
        backend = get_storage()
        prefix = _storage_prefix(src)
        if ref.endswith('.zip'):
            files = _unzip(backend.read_bytes(f'{prefix}/{ref}'))
        else:
            base = f'{prefix}/{ref}/'
            listed = [p for p in backend.list_files(f'{prefix}/{ref}') if p.startswith(base)]
            if len(listed) > MAX_FILES:
                raise CatalogError(f'the package has more than {MAX_FILES} files')
            files = {p[len(base):]: backend.read_bytes(p) for p in listed}
    else:
        p = Path(src) / ref
        if p.is_symlink():
            raise CatalogError(f'{ref} is a symbolic link')
        files = _unzip(p.read_bytes()) if ref.endswith('.zip') else _read_folder(p)
    files = {k: v for k, v in files.items() if not S._skipped(k) or k == S.SIGNATURE_FILE}
    _write_files(dest, files)


class _Staged:
    """A package fetched into a temporary folder for the duration of a ``with``."""

    def __init__(self, src: str, ref: str):
        self.src, self.ref = src, ref
        self.path: Optional[Path] = None

    def __enter__(self) -> Path:
        self.path = Path(tempfile.mkdtemp(prefix='sajha-plugin-'))
        try:
            fetch(self.src, self.ref, self.path)
        except Exception:
            shutil.rmtree(self.path, ignore_errors=True)
            raise
        return self.path

    def __exit__(self, *exc):
        if self.path is not None:
            shutil.rmtree(self.path, ignore_errors=True)


def _manifest(root: Path) -> Dict[str, Any]:
    try:
        m = json.loads((root / 'plugin.json').read_text(encoding='utf-8'))
    except Exception:
        raise CatalogError('the package has no readable plugin.json')
    if not isinstance(m, dict) or not NAME_RE.match(str(m.get('name') or '')):
        raise CatalogError('plugin.json: name must be 1-64 letters, digits, ".", "_" or "-"')
    return m


# ── listing ──────────────────────────────────────────────────────────

def installed_versions() -> Dict[str, str]:
    try:
        from sajha.core.plugins import get_plugin_manager
        pm = get_plugin_manager()
        if pm is None:
            return {}
        return {m['name']: m['version'] for m in pm.list_plugins()}
    except Exception:
        return {}


def list_available() -> Dict[str, Any]:
    """Every package of every configured source with its signature verdict (sources that fail are
    reported, not raised)."""
    installed = installed_versions()
    keys = S.trusted_keys()
    out: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    for src in sources():
        try:
            refs = _refs(src)
        except CatalogError as e:
            errors[src] = str(e)
            continue
        except Exception as e:
            errors[src] = f'{e.__class__.__name__}: {e}'
            continue
        for r in refs:
            item = {'source': src, 'source_kind': source_kind(src), 'ref': r['ref'],
                    'name': r.get('name', ''), 'version': r.get('version', ''),
                    'publisher': r.get('publisher', ''), 'description': r.get('description', ''),
                    'status': '', 'detail': ''}
            try:
                with _Staged(src, r['ref']) as root:
                    m = _manifest(root)
                    v = S.verify(root, keys)
                item.update(name=m['name'], version=str(m.get('version', '0.0.0')),
                            description=str(m.get('description', ''))[:300], author=str(m.get('author', '')),
                            publisher=v.publisher or item['publisher'], status=v.status, detail=v.detail,
                            package_hash=v.package_hash)
            except CatalogError as e:
                item.update(status='error', detail=str(e))
            except Exception as e:
                item.update(status='error', detail=f'{e.__class__.__name__}: {e}')
            item['installed_version'] = installed.get(item['name'], '')
            out.append(item)
    return {'sources': sources(), 'packages': out, 'errors': errors,
            'trusted_publishers': sorted({k.publisher for k in keys.values()}),
            'crypto': S.crypto_available(), 'allow_unsigned': S.allow_unsigned()}


# ── drafts ───────────────────────────────────────────────────────────

def _store():
    from sajha.core.state import get_state_store
    return get_state_store()


def _preview(root: Path) -> List[Dict[str, Any]]:
    files = []
    for rel in S.package_files(root) + [S.SIGNATURE_FILE]:
        p = root / rel
        if not p.is_file():
            continue
        data = p.read_bytes()
        text = None
        if rel.endswith(TEXT_SUFFIXES) or rel in ('requirements.txt', 'README'):
            try:
                text = data[:PREVIEW_BYTES].decode('utf-8')
            except UnicodeDecodeError:
                text = None
        files.append({'path': rel, 'bytes': len(data), 'text': text, 'truncated': len(data) > PREVIEW_BYTES})
    return files


def review(src: str, ref: str, user=None) -> Dict[str, Any]:
    """Fetch and verify one package and keep it as a draft for review."""
    _check_ref(src, ref)
    with _Staged(src, ref) as root:
        m = _manifest(root)
        v = S.verify(root)
        if v.status != 'trusted':
            raise CatalogError(f'only a plugin signed by a trusted publisher can be installed from the catalog: '
                               f'{v.status}: {v.detail}', 409, status_detail=v.to_dict())
        files = _preview(root)
    d = {'id': secrets.token_hex(8), 'source': src, 'ref': ref, 'hash': v.package_hash,
         'manifest': {k: m.get(k) for k in ('name', 'version', 'author', 'description', 'min_sajha_version',
                                            'dependencies', 'tools', 'config_keys')},
         'signature': v.to_dict(), 'files': files,
         'installed_version': installed_versions().get(m['name'], ''),
         'created_by': str(getattr(user, 'user_id', '') or ''), 'created_at': time.time(), 'installed': None}
    _store().set(DRAFT_PREFIX + d['id'], d, ttl=draft_ttl())
    _audit(user, 'review', {'draft': d['id'], 'plugin': m['name'], 'version': m.get('version'),
                            'publisher': v.publisher, 'hash': v.package_hash, 'source': src})
    return d


def get_draft(draft_id: str) -> Dict[str, Any]:
    if not re.match(r'^[0-9a-f]{16}$', str(draft_id or '')):
        raise CatalogError('no such review', 404)
    d = _store().get(DRAFT_PREFIX + draft_id)
    if not d:
        raise CatalogError('no such review (reviews expire after plugins.catalog.draft_ttl_seconds)', 404)
    return d


def _policy_gate(name: str, user) -> Optional[Dict[str, Any]]:
    """The policy gate of Describe a tool's deploy, for ``plugin:<name>`` of kind ``plugin``."""
    from sajha.studio.describe import DescribeError, _policy_gate as gate
    try:
        return gate({'name': f'plugin:{name}', 'kind': 'plugin'}, user)
    except DescribeError as e:
        raise CatalogError(str(e), e.status, **getattr(e, 'extra', {}))


def _plugins_dir() -> Tuple[str, bool]:
    """(the configured plugins folder, whether it is written through a cloud storage backend)."""
    from sajha.core.plugins import PluginManager, get_plugin_manager
    pm = get_plugin_manager()
    d = pm.PLUGINS_DIR if pm is not None else PluginManager.PLUGINS_DIR
    try:
        from sajha.core.storage import LocalStorageBackend, get_storage
        backend = get_storage()
        cloud = not isinstance(backend, LocalStorageBackend) and hasattr(backend, 'cache_dir') \
            and not os.path.isabs(str(d))
    except Exception:
        cloud = False
    return str(d), cloud


def _write_plugin(name: str, root: Path) -> List[str]:
    base, cloud = _plugins_dir()
    rels = S.package_files(root) + ([S.SIGNATURE_FILE] if (root / S.SIGNATURE_FILE).is_file() else [])
    written = []
    if cloud:
        from sajha.core.storage import get_storage
        backend = get_storage()
        prefix = posixpath.normpath(base.replace('\\', '/')).strip('/')
        for rel in rels:
            backend.write_bytes(f'{prefix}/{name}/{rel}', (root / rel).read_bytes())
            written.append(f'{prefix}/{name}/{rel}')
    else:
        target = Path(base) / name
        for rel in rels:
            p = target / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((root / rel).read_bytes())
            written.append(str(p))
    return written


def _remove_plugin(name: str) -> None:
    base, cloud = _plugins_dir()
    if cloud:
        from sajha.core.storage import get_storage
        backend = get_storage()
        prefix = posixpath.normpath(base.replace('\\', '/')).strip('/')
        for p in backend.list_files(f'{prefix}/{name}'):
            if p.startswith(f'{prefix}/{name}/'):
                backend.delete(p)
    else:
        shutil.rmtree(Path(base) / name, ignore_errors=True)


def _exists(name: str) -> bool:
    base, cloud = _plugins_dir()
    if cloud:
        from sajha.core.storage import get_storage
        prefix = posixpath.normpath(base.replace('\\', '/')).strip('/')
        return bool(get_storage().list_files(f'{prefix}/{name}'))
    return (Path(base) / name).exists()


def install(draft_id: str, reviewed_hash: str, approve: bool, replace: bool = False, user=None) -> Dict[str, Any]:
    """Install exactly the reviewed package. Every precondition is checked here."""
    d = get_draft(draft_id)
    name = d['manifest']['name']
    if not approve:
        raise CatalogError('an install needs explicit approval (approve: true) after you have reviewed the files')
    if d.get('installed'):
        raise CatalogError('already installed from this review', 409)
    if reviewed_hash != d['hash']:
        raise CatalogError('the package is not the one you reviewed; review it again', 409, hash=d['hash'])
    if _exists(name) and not replace:
        raise CatalogError(f'a plugin named {name} is installed; install with replace to upgrade it', 409)
    from sajha.core.plugins import get_plugin_manager
    pm = get_plugin_manager()
    if pm is None:
        raise CatalogError('the plugin manager is not running', 503)
    with _Staged(d['source'], d['ref']) as root:
        v = S.verify(root)
        if v.status != 'trusted':
            raise CatalogError(f'the package is no longer trusted: {v.status}: {v.detail}', 409)
        if v.package_hash != d['hash']:
            raise CatalogError('the package changed in the catalog since you reviewed it; review it again', 409)
        if _manifest(root)['name'] != name:
            raise CatalogError('the package name changed since the review', 409)
        grant = _policy_gate(name, user)
        backup = None
        if _exists(name):
            backup = Path(tempfile.mkdtemp(prefix='sajha-plugin-old-'))
            old_dir = _local_copy(name, backup)
            pm.unload_plugin(name)
            _remove_plugin(name)
        else:
            old_dir = None
        try:
            files = _write_plugin(name, root)
            pm.discover()
            status = pm.load_plugin(name)
            if not status.enabled:
                raise CatalogError(f'the plugin was written but did not load, so it was removed: {status.error}', 500)
        except Exception as e:
            _remove_plugin(name)
            if old_dir is not None:
                _write_plugin(name, old_dir)
                pm.discover()
                pm.load_plugin(name)
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
            if isinstance(e, CatalogError):
                raise
            raise CatalogError(f'install failed: {e.__class__.__name__}: {e}', 500)
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
    d['installed'] = {'at': time.time(), 'by': str(getattr(user, 'user_id', '') or ''), 'hash': d['hash'],
                      'files': len(files), 'tools': status.tools_registered, 'replaced': old_dir is not None,
                      'approval': (grant or {}).get('id')}
    _store().set(DRAFT_PREFIX + d['id'], d, ttl=draft_ttl())
    _audit(user, 'install', {'draft': d['id'], 'plugin': name, 'version': d['manifest'].get('version'),
                             'publisher': d['signature'].get('publisher'), 'key_id': d['signature'].get('key_id'),
                             'hash': d['hash'], 'source': d['source'], 'replaced': old_dir is not None,
                             'approval': (grant or {}).get('id')})
    return {**d, 'message': f'Installed {name} {d["manifest"].get("version")}: '
                            f'{status.tools_registered} tool(s) registered.'}


def _local_copy(name: str, dest: Path) -> Optional[Path]:
    """A copy of the installed plugin's files (to restore it if the upgrade fails)."""
    from sajha.core.plugins import get_plugin_manager
    pm = get_plugin_manager()
    try:
        src = Path(pm._local_plugins_dir()) / name
        if src.is_dir():
            shutil.copytree(src, dest / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            return dest / name
    except Exception as e:
        logger.warning(f'plugins: could not keep a copy of {name} before replacing it: {e}')
    return None


def _audit(user, what: str, details: Dict[str, Any]) -> None:
    try:
        from sajha.core.audit import AuditLogger
        AuditLogger().config_changed(f'plugins.catalog.{what}', by_user=getattr(user, 'user_id', None),
                                     details=json.dumps(details, default=str)[:2000])
    except Exception as e:
        logger.debug(f'plugin catalog audit: {e}')
