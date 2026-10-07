"""
SAJHA MCP Server — snapshots: what is collected, how a snapshot file is written, chained,
signed, rotated, verified, compared and restored from.

A snapshot is one JSON file (optionally gzip-compressed) in ``snapshots.dir``::

    {"snapshot": {"format": "sajha-snapshot/1", "seq": 12, "created": "...Z",
                  "prev": {"name": "...", "sha256": "..."} | null,
                  "instance": {...}, "users": [...], "roles": [...], "api_keys": [...], "tools": [...]},
     "sha256": "<SHA-256 of the canonical JSON of snapshot>",
     "signature": {"alg": "RS256", "kid": "...", "value": "<RS256 over the same canonical JSON>"}}

``prev.sha256`` is the previous snapshot's ``sha256``, so a deleted, reordered or edited
snapshot breaks the chain; the signature (the server key in ``data/oauth/``, the one that signs
the audit chain's anchors) shows who wrote it. No password hashes are ever collected; API key
hashes only for persistent keys, so a snapshot alone cannot verify an ordinary key.

Owner guide: docs/architecture/Policy and Audit.md (Snapshots).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import secrets
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

FORMAT = 'sajha-snapshot/1'
NAME_RE = re.compile(r'^snapshot-(\d{8}T\d{6}Z)-(\d{6})\.json(\.gz)?$')
SECTIONS = {'users': 'user_id', 'roles': 'name', 'api_keys': 'id', 'tools': 'name'}


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')     # naive UTC, as the models store it


# ── what is collected ───────────────────────────────────────────────

def contract_hash(tool) -> str:
    """SHA-256 of a tool's contract: its input and output schemas, canonical JSON."""
    try:
        inp = tool.input_schema
    except Exception:
        inp = None
    try:
        out = tool.output_schema
    except Exception:
        out = None
    return sha256(canonical({'inputSchema': inp or {}, 'outputSchema': out or {}}))


def _is_local(tool) -> bool:
    try:
        from sajha.federation.tool import FederatedTool
        return not isinstance(tool, FederatedTool)
    except Exception:
        return True


def collect_tools(registry) -> List[Dict[str, Any]]:
    if registry is None:
        return []
    out = []
    for name, tool in sorted(dict(getattr(registry, 'tools', {}) or {}).items()):
        if not _is_local(tool):
            continue
        out.append({'name': name, 'version': str(getattr(tool, 'version', '') or ''),
                    'contract_sha256': contract_hash(tool), 'enabled': bool(getattr(tool, 'enabled', True))})
    return out


def _key_is_persistent(key) -> bool:
    """A persistent key (SAJHA Net §20.3) is also kept, hashed, in ``config.apikeys.path``."""
    return bool(getattr(key, 'persistent', False))


def collect_db(db) -> Dict[str, List[Dict[str, Any]]]:
    """Users (no password hashes), roles with permissions, and API key records."""
    from sajha.db.models import ApiKey, Role, User
    users = []
    for u in db.query(User).order_by(User.user_id).all():
        users.append({'id': u.id, 'user_id': u.user_id, 'user_name': u.user_name,
                      'roles': sorted(r.name for r in u.roles), 'enabled': bool(u.enabled)})
    roles = []
    for r in db.query(Role).order_by(Role.name).all():
        roles.append({'name': r.name, 'description': r.description or '', 'is_system': bool(r.is_system),
                      'permissions': sorted(({'resource_type': p.resource_type, 'resource_name': p.resource_name,
                                              'actions': p.actions} for p in r.permissions),
                                             key=lambda p: (p['resource_type'], p['resource_name'], p['actions']))})
    by_pk = {u['id']: u for u in users}
    keys = []
    for k in db.query(ApiKey).order_by(ApiKey.created_at, ApiKey.id).all():
        owner = by_pk.get(k.owner_id) if k.owner_id else None
        try:
            access = json.loads(k.tool_access_list) if k.tool_access_list else []
        except (TypeError, ValueError):
            access = []
        persistent = _key_is_persistent(k)
        rec = {'id': k.id, 'prefix': k.key_prefix, 'name': k.name, 'description': k.description or '',
               'owner': owner['user_id'] if owner else None, 'owner_roles': owner['roles'] if owner else [],
               'enabled': bool(k.enabled), 'created_at': _iso(k.created_at), 'expires_at': _iso(k.expires_at),
               'tool_access_mode': k.tool_access_mode, 'tool_access_list': access,
               'persistent': persistent}
        for extra in ('created_by', 'is_default', 'revoked_by'):   # never secret_ciphertext
            if hasattr(k, extra):
                rec[extra] = getattr(k, extra)
        for extra in ('rotated_at', 'revoked_at'):
            if hasattr(k, extra):
                rec[extra] = _iso(getattr(k, extra))
        if persistent:
            rec['key_hash'] = k.key_hash
        keys.append(rec)
    return {'users': users, 'roles': roles, 'api_keys': keys}


def instance_info() -> Dict[str, Any]:
    try:
        from sajha.core.config import get_settings
        version = get_settings().app_version
    except Exception:
        version = ''
    try:
        from sajha.core.state import WORKER_ID
    except Exception:
        WORKER_ID = ''
    return {'host': socket.gethostname(), 'version': version, 'worker': WORKER_ID}


# ── signing ─────────────────────────────────────────────────────────

def default_signer():
    """The instance's signing key: a net key once SAJHA Net exists; today the server key
    (sajha/auth/oauth/keys.py, data/oauth/) that also signs the audit chain's anchors."""
    from sajha.audit.chain import Signer
    return Signer()


def load_public_keys(path: Optional[str] = None) -> Dict[str, Any]:
    """``{kid: public key}``: the current server key, plus a PEM or JWKS file when given."""
    keys: Dict[str, Any] = {}
    try:
        s = default_signer()
        keys[s.kid] = s.public_key()
    except Exception as e:
        logger.debug(f'server key unavailable: {e}')
    if path:
        from cryptography.hazmat.primitives import serialization
        raw = Path(path).read_bytes()
        if raw.lstrip().startswith(b'{'):
            from jose import jwk
            for k in json.loads(raw).get('keys', []):
                pem = jwk.construct(k, algorithm='RS256').to_pem()
                keys[k.get('kid', '')] = serialization.load_pem_public_key(pem)
        else:
            try:
                key = serialization.load_pem_public_key(raw)
            except ValueError:
                key = serialization.load_pem_private_key(raw, password=None).public_key()
            keys.setdefault('*', key)
    return keys


# ── the store ───────────────────────────────────────────────────────

class SnapshotStore:
    """The snapshot files in one directory (owner-only permissions)."""

    def __init__(self, directory, keep: int = 20, compress: bool = False):
        self.dir = Path(directory)
        self.keep = max(1, int(keep))
        self.compress = bool(compress)

    # files
    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError as e:                     # pragma: no cover - e.g. a mount that ignores modes
            logger.debug(f'chmod {self.dir}: {e}')

    def names(self) -> List[str]:
        """Snapshot file names, oldest first (by sequence number)."""
        if not self.dir.is_dir():
            return []
        found = [(int(m.group(2)), p.name) for p in self.dir.iterdir() if (m := NAME_RE.match(p.name))]
        return [n for _, n in sorted(found)]

    def path(self, name: str) -> Path:
        if not NAME_RE.match(name):
            raise ValueError(f'not a snapshot name: {name!r}')
        return self.dir / name

    def resolve(self, ref: str) -> str:
        """A name, a path, ``latest`` or ``previous`` → a name in this store."""
        names = self.names()
        if ref in ('latest', 'previous'):
            need = 1 if ref == 'latest' else 2
            if len(names) < need:
                raise FileNotFoundError(f'no {ref} snapshot in {self.dir}')
            return names[-need]
        name = Path(ref).name
        if name not in names:
            raise FileNotFoundError(f'snapshot {ref} not found in {self.dir}')
        return name

    def load(self, name: str) -> Dict[str, Any]:
        raw = self.path(name).read_bytes()
        if name.endswith('.gz'):
            raw = gzip.decompress(raw)
        return json.loads(raw.decode('utf-8'))

    def latest(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        names = self.names()
        return (names[-1], self.load(names[-1])) if names else None

    # writing
    def write(self, content: Dict[str, Any], signer, now: Optional[datetime] = None) -> Tuple[str, Dict[str, Any]]:
        """Write the next snapshot (chained to the latest) and return ``(name, envelope)``."""
        self._ensure_dir()
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        last = self.latest()
        seq = int(last[1]['snapshot']['seq']) + 1 if last else 1
        prev = {'name': last[0], 'sha256': last[1]['sha256']} if last else None
        body = {'format': FORMAT, 'seq': seq, 'created': now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'), 'prev': prev}
        body.update(content)
        text = canonical(body)
        envelope = {'snapshot': body, 'sha256': sha256(text),
                    'signature': {'alg': signer.alg, 'kid': signer.kid, 'value': signer.sign(text.encode('utf-8'))}}
        name = f'snapshot-{now.strftime("%Y%m%dT%H%M%SZ")}-{seq:06d}.json' + ('.gz' if self.compress else '')
        data = json.dumps(envelope, indent=1, sort_keys=True, ensure_ascii=False).encode('utf-8')
        if self.compress:
            data = gzip.compress(data)
        fd, tmp = tempfile.mkstemp(prefix='.snapshot-', dir=str(self.dir))
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.dir / name)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return name, envelope

    def rotate(self) -> List[Dict[str, str]]:
        """Delete the oldest snapshots beyond ``keep``; returns ``[{name, sha256}]`` deleted."""
        names = self.names()
        gone = []
        for name in names[:max(0, len(names) - self.keep)]:
            try:
                h = self.load(name).get('sha256', '')
            except Exception:
                h = ''
            try:
                self.path(name).unlink()
                gone.append({'name': name, 'sha256': h})
            except FileNotFoundError:
                pass
        return gone

    # checking
    def verify(self, public_keys: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Check every snapshot's hash and signature, and the chain between them."""
        from sajha.audit.chain import verify_signature
        keys = public_keys if public_keys is not None else load_public_keys()
        report: Dict[str, Any] = {'dir': str(self.dir), 'ok': True, 'snapshots': [], 'problems': [], 'notes': []}
        prev_env: Optional[Dict[str, Any]] = None
        prev_name = ''
        for i, name in enumerate(self.names()):
            entry: Dict[str, Any] = {'name': name, 'ok': True, 'problems': []}
            report['snapshots'].append(entry)

            def bad(msg: str) -> None:
                entry['ok'] = report['ok'] = False
                entry['problems'].append(msg)
                report['problems'].append(f'{name}: {msg}')
            try:
                env = self.load(name)
                body = env['snapshot']
            except Exception as e:
                bad(f'unreadable ({e})')
                prev_env, prev_name = None, name
                continue
            entry['seq'] = body.get('seq')
            entry['created'] = body.get('created')
            if body.get('format') != FORMAT:
                bad(f'unknown format {body.get("format")!r}')
            text = canonical(body)
            if sha256(text) != env.get('sha256'):
                bad('edited: its content does not match its SHA-256')
            sig = env.get('signature') or {}
            key = keys.get(sig.get('kid', '')) or keys.get('*')
            if key is None:
                bad(f'signed with key {sig.get("kid")!r}, which is not available (--public-key)')
            elif not verify_signature(key, text.encode('utf-8'), sig.get('value', '')):
                bad('the signature does not verify')
            m = NAME_RE.match(name)
            if m and int(m.group(2)) != body.get('seq'):
                bad(f'renamed: the file name says sequence {int(m.group(2))}, the content {body.get("seq")}')
            prev = body.get('prev')
            if i == 0:
                if prev:
                    report['notes'].append(f'the retained chain starts at {name}; its predecessor '
                                           f'{prev.get("name")} is no longer kept (rotation)')
            elif prev_env is not None:
                pb = prev_env['snapshot']
                if not prev or prev.get('sha256') != prev_env.get('sha256'):
                    bad(f'chain broken after {prev_name}: a snapshot is missing, reordered or replaced')
                elif body.get('seq') != pb.get('seq', 0) + 1:
                    bad(f'sequence jumps from {pb.get("seq")} to {body.get("seq")}')
                if str(body.get('created', '')) < str(pb.get('created', '')):
                    bad(f'created before {prev_name}')
            prev_env, prev_name = env, name
        report['count'] = len(report['snapshots'])
        return report


# ── comparing ───────────────────────────────────────────────────────

def diff(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """What changed from snapshot ``a`` to snapshot ``b`` (envelopes or bodies), per section."""
    a = a.get('snapshot', a)
    b = b.get('snapshot', b)
    out: Dict[str, Dict[str, Any]] = {}
    for section, key in SECTIONS.items():
        old = {r.get(key): r for r in a.get(section) or []}
        new = {r.get(key): r for r in b.get(section) or []}
        changed = []
        for k in sorted(set(old) & set(new), key=str):
            fields = {f: [old[k].get(f), new[k].get(f)] for f in sorted(set(old[k]) | set(new[k]))
                      if old[k].get(f) != new[k].get(f)}
            if fields:
                changed.append({key: k, 'fields': fields})
        out[section] = {'added': sorted((k for k in set(new) - set(old)), key=str),
                        'removed': sorted((k for k in set(old) - set(new)), key=str),
                        'changed': changed}
    return out


def diff_lines(d: Dict[str, Dict[str, Any]]) -> List[str]:
    lines = []
    for section, parts in d.items():
        for k in parts['added']:
            lines.append(f'+ {section}: {k}')
        for k in parts['removed']:
            lines.append(f'- {section}: {k}')
        key = SECTIONS[section]
        for c in parts['changed']:
            what = ', '.join(f'{f} {v[0]!r} -> {v[1]!r}' for f, v in c['fields'].items())
            lines.append(f'~ {section}: {c[key]}: {what}')
    return lines


# ── restoring ───────────────────────────────────────────────────────

def restore(db, envelope: Dict[str, Any], keys: bool = True, dry_run: bool = False) -> Dict[str, Any]:
    """Re-create roles, users and persistent API key records from a snapshot.

    Only what is missing is created; nothing existing is changed or deleted. Users get an
    unusable random password and must change it (an administrator sets one; a snapshot carries
    no password hashes) and a new default API key. Keys come back only when they were
    persistent (only those carry a hash)."""
    from sajha.auth.password import hash_password
    from sajha.db.models import ApiKey, Permission, Role, User
    body = envelope.get('snapshot', envelope)
    report: Dict[str, List[str]] = {'roles_created': [], 'users_created': [], 'users_skipped': [],
                                    'keys_created': [], 'keys_skipped': []}
    roles = {r.name: r for r in db.query(Role).all()}
    for r in body.get('roles') or []:
        if r['name'] in roles:
            continue
        report['roles_created'].append(r['name'])
        if not dry_run:
            role = Role(name=r['name'], description=r.get('description') or None, is_system=bool(r.get('is_system')))
            for p in r.get('permissions') or []:
                role.permissions.append(Permission(resource_type=p['resource_type'],
                                                   resource_name=p.get('resource_name') or '*',
                                                   actions=p.get('actions') or '*'))
            db.add(role)
            roles[role.name] = role
    if not dry_run:
        db.flush()
    by_user_id = {u.user_id: u for u in db.query(User).all()}
    taken_ids = {u.id for u in by_user_id.values()}
    for u in body.get('users') or []:
        if u['user_id'] in by_user_id:
            report['users_skipped'].append(u['user_id'])
            continue
        report['users_created'].append(u['user_id'])
        if dry_run:
            continue
        user = User(user_id=u['user_id'], user_name=u.get('user_name') or u['user_id'],
                    password_hash=hash_password(secrets.token_urlsafe(32)), enabled=bool(u.get('enabled', True)),
                    must_change_password=True)
        if u.get('id') and u['id'] not in taken_ids:
            user.id = u['id']
        for rn in u.get('roles') or []:
            if rn in roles:
                user.roles.append(roles[rn])
        db.add(user)
        by_user_id[user.user_id] = user
    if not dry_run:
        db.flush()
    if keys:
        have = {k.key_hash for k in db.query(ApiKey).all()}
        have_ids = {k.id for k in db.query(ApiKey).all()}
        for k in body.get('api_keys') or []:
            if not (k.get('persistent') and k.get('key_hash')):
                continue
            if k['key_hash'] in have:
                report['keys_skipped'].append(k.get('prefix') or k['id'])
                continue
            report['keys_created'].append(k.get('prefix') or k['id'])
            if dry_run:
                continue
            owner = by_user_id.get(k.get('owner')) if k.get('owner') else None
            rec = ApiKey(key_hash=k['key_hash'], key_prefix=k.get('prefix') or '', name=k.get('name') or 'restored',
                         description=k.get('description') or None, owner_id=owner.id if owner else None,
                         enabled=bool(k.get('enabled', True)), expires_at=_parse_iso(k.get('expires_at')),
                         tool_access_mode=k.get('tool_access_mode') or 'all',
                         tool_access_list=json.dumps(k.get('tool_access_list') or []))
            if k.get('id') and k['id'] not in have_ids:
                rec.id = k['id']
            for extra in ('persistent', 'created_by'):        # not is_default: its sealed secret is not kept
                if hasattr(ApiKey, extra) and extra in k:
                    setattr(rec, extra, k[extra])
            if hasattr(ApiKey, 'revoked_at') and k.get('revoked_at'):
                rec.revoked_at = _parse_iso(k['revoked_at'])      # a revoked key stays revoked
            db.add(rec)
    if not dry_run:
        db.commit()
        _default_keys(db, [by_user_id[u] for u in report['users_created'] if u in by_user_id], report)
    return report


def _default_keys(db, users, report: Dict[str, List[str]]) -> None:
    """Every restored user gets a default API key, as every account does (a new key: the old
    default key's secret is not in the snapshot)."""
    try:
        from sajha.auth.apikeys import ensure_default_key
    except ImportError:                          # pragma: no cover - builds without owned keys
        return
    report.setdefault('default_keys_created', [])
    for user in users:
        try:
            if ensure_default_key(db, user, by='snapshot-restore') is not None:
                report['default_keys_created'].append(user.user_id)
        except Exception as e:
            db.rollback()
            logger.warning(f'default API key for restored user {user.user_id} not created: {e}')


def iter_sections(body: Dict[str, Any]) -> Iterable[Tuple[str, int]]:
    for s in SECTIONS:
        yield s, len(body.get(s) or [])
