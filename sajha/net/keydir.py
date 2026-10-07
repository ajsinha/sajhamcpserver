"""
The net key directory (protocol §11; design §10.3): key records, their acceptance, delta pulls,
digests and anti-entropy, and the usability checks a host applies to a forwarded key (§15.3).

* A home publishes one signed record (``type: "key"``, §8.10) per API key it issued, in each of
  its nets; :meth:`KeyDirectory.publish` reconciles the home's own keys (given by a callable) with
  the records it holds: a changed key gets a new ``version`` from the home's single counter, a key
  that disappeared becomes a tombstone (``revoked_at`` set, never removed), and records still
  signed by an older certificate are re-signed with the current one (same version).
* A receiver accepts a record only from its home, in the net it arrived through, signed by the
  certificate the home answered with (§11.2); older or equal versions are ignored.
* :meth:`KeyDirectory.tick` pulls changed records when a member's ``digests.keys`` passes the held
  version, runs the digest comparison (§11.4) every full-sync interval, discards records signed by
  a revoked certificate and re-pulls that home from version 0.
* :func:`check_usable` gives the §15.3 refusal reason for a record, or None.

The store is a :class:`~sajha.net.plugins.KeyDirectoryStore`; the core never sees a raw key.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Dict, List, Optional

from sajha.net import ENDPOINT, crypto, jcs, schemas
from sajha.net.errors import NetError

logger = logging.getLogger(__name__)

P = ENDPOINT.rstrip('/')
DEFAULT_PAGE = 500
MAX_PAGE = 1000
#: the fields of a record that are the key's state (a change in any of them is a new version)
STATE_FIELDS = ('key_prefix', 'name', 'key_hash', 'owner', 'enabled', 'expires_at', 'revoked_at',
                'tool_access_mode', 'tool_access_list', 'persistent')
FAILURES_BEFORE_NOTICE = 2


def key_hash(raw: str) -> str:
    """Lowercase hex SHA-256 of the raw key's UTF-8 bytes (§11.1; what SAJHA stores)."""
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def unsigned(record: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in record.items() if k != 'signature'}


def sign(record: Dict[str, Any], key, keyid: str) -> Dict[str, Any]:
    body = unsigned(record)
    return dict(body, signature=crypto.sign_record('key', body, key, keyid))


def digest_root(records: List[Dict[str, Any]]) -> str:
    """§11.4: base64url(SHA-256(JCS of the ``[key_id, version]`` pairs sorted by ``key_id``))."""
    pairs = sorted([[str(r['key_id']), int(r['version'])] for r in records], key=lambda p: p[0])
    return crypto.b64url(hashlib.sha256(jcs.canonicalize(pairs)).digest())


def acceptance_error(record: Any, net: str, sender: str, certificate) -> Optional[str]:
    """Why a record returned by ``sender`` in ``net`` must be ignored (§11.2), or None."""
    if not isinstance(record, dict) or schemas.errors('key_record', record):
        return 'schema'
    if record['net'] != net:
        return 'net_mismatch'
    if record['home_instance'] != sender:
        return 'not_home'
    sig = record.get('signature') or {}
    try:
        keyid = crypto.thumbprint(crypto.cert_der(certificate))
    except Exception:
        return 'certificate_invalid'
    if sig.get('keyid') != keyid:
        return 'signature_invalid'
    if not crypto.verify_record('key', unsigned(record), sig, certificate.public_key()):
        return 'signature_invalid'
    return None


def check_usable(record: Optional[Dict[str, Any]], sender: str, now: float,
                 home_usable: Optional[Callable[[str], bool]] = None) -> Optional[str]:
    """The §15.3 refusal reason for a forwarded key whose record is ``record``, sent by ``sender``."""
    if record is None:
        return 'key_unknown'
    if record.get('revoked_at') or record.get('unusable'):
        return 'key_revoked'                     # a revoked key is also disabled: say the stronger reason
    if not record.get('enabled'):
        return 'key_disabled'
    exp = record.get('expires_at')
    if exp:
        try:
            if crypto.parse_rfc3339(exp) <= now:
                return 'key_expired'
        except Exception:
            return 'key_expired'
    if record.get('home_instance') != sender:
        return 'key_not_from_home'
    if home_usable is not None and not home_usable(record['home_instance']):
        return 'key_revoked'                     # the home left or was revoked (§11.2)
    return None


class KeyDirectory:
    """One participant's key directory in one net: its own records and everyone else's.

    ``own()`` returns the home's current keys as record bodies without ``type``, ``net``,
    ``home_instance``, ``version``, ``updated_at`` and ``signature`` (each with ``key_id``).
    ``skip(peer)`` is True for peers whose updates are ignored (an instance blocked entirely).
    """

    def __init__(self, node, store, own: Optional[Callable[[], List[Dict[str, Any]]]] = None, *,
                 skip: Optional[Callable[[str], bool]] = None, full_sync_interval: float = 300.0,
                 page: int = DEFAULT_PAGE, sync: bool = True):
        self.node = node
        self.store = store
        self.own = own
        self.skip = skip or (lambda peer: False)
        self.full_sync_interval = float(full_sync_interval)
        self.page = max(1, min(MAX_PAGE, int(page)))
        self.sync = sync
        self._last_full = 0.0
        self._rl_version = -1

    @property
    def net(self) -> str:
        return self.node.net

    # ── wiring ──────────────────────────────────────────────────────

    def install(self) -> 'KeyDirectory':
        n = self.node
        n.handlers[P + '/keys'] = self.serve_keys
        n.handlers[P + '/keys/digest'] = self.serve_digest
        n.digest_sources['keys'] = self.own_version
        for f in ('key_directory', 'key_verification'):
            if f not in n.extra_features:
                n.extra_features.append(f)
        if self.observe not in n.observers:
            n.observers.append(self.observe)
        if self.tick not in n.tick_hooks:
            n.tick_hooks.append(self.tick)
        return self

    def observe(self, kind: str, data: Dict[str, Any]) -> None:
        if kind == 'revocations_updated':
            self.apply_revocations()

    # ── the home's own records ──────────────────────────────────────

    def own_version(self) -> int:
        return int(self.store.version(self.net, self.node.name))

    def own_records(self) -> List[Dict[str, Any]]:
        return self.store.since(self.net, self.node.name, 0, limit=10 ** 9)

    def publish(self) -> int:
        """Bring the own records in line with ``own()``; returns how many records changed (and
        re-signs the member record so gossip carries the new ``digests.keys``)."""
        if self.own is None:
            return 0
        current = {str(k['key_id']): k for k in self.own()}
        held = {r['key_id']: r for r in self.own_records()}
        version = max([int(r['version']) for r in held.values()] or [0])
        signer = self.node.signer
        now = crypto.rfc3339(self.node.clock())
        changed = 0
        for kid in sorted(set(current) | set(held)):
            old = held.get(kid)
            body = current.get(kid)
            if body is None:
                if old is None or old.get('revoked_at'):
                    continue
                state = {f: old[f] for f in STATE_FIELDS}
                state.update(enabled=False, revoked_at=now)
            else:
                state = {f: body.get(f) for f in STATE_FIELDS}
                if old is not None and old.get('revoked_at') and not state.get('revoked_at'):
                    state['revoked_at'] = old['revoked_at']      # a tombstone never comes back
            if old is not None and all(old.get(f) == state.get(f) for f in STATE_FIELDS):
                if (old.get('signature') or {}).get('keyid') != signer.keyid:
                    self.store.put(sign(old, signer.key, signer.keyid), force=True)
                continue
            version += 1
            rec = {'type': 'key', 'net': self.net, 'key_id': kid, 'home_instance': self.node.name,
                   **state, 'version': version, 'updated_at': now}
            self.store.put(sign(rec, signer.key, signer.keyid), force=True)
            changed += 1
        if changed:
            try:
                self.node.refresh_record()
            except Exception as e:
                logger.debug(f'SAJHA Net {self.net}: re-signing after a key change: {e}')
        return changed

    # ── endpoints (§11.3, §11.4) ────────────────────────────────────

    def serve_keys(self, data: Dict[str, Any], v) -> Dict[str, Any]:
        since = int(data.get('since') or 0)
        limit = max(1, min(MAX_PAGE, int(data.get('limit') or self.page)))
        recs = self.store.since(self.net, self.node.name, since, limit=limit + 1)
        more = len(recs) > limit
        recs = recs[:limit]
        out = {'home_instance': self.node.name, 'version': self.own_version(),
               'records': [self._public(r) for r in recs], 'more': more}
        if more:
            out['next_since'] = int(recs[-1]['version'])
        return out

    def serve_digest(self, data: Dict[str, Any], v) -> Dict[str, Any]:
        recs = self.own_records()
        return {'home_instance': self.node.name, 'version': self.own_version(), 'count': len(recs),
                'root': digest_root(recs)}

    @staticmethod
    def _public(r: Dict[str, Any]) -> Dict[str, Any]:
        keep = ('type', 'net', 'key_id', 'key_prefix', 'name', 'key_hash', 'home_instance', 'owner', 'enabled',
                'expires_at', 'revoked_at', 'tool_access_mode', 'tool_access_list', 'persistent', 'version',
                'updated_at', 'signature')
        return {k: r[k] for k in keep if k in r}

    # ── pulling (§11.2, §11.3) ──────────────────────────────────────

    def _member_ok(self, m: Dict[str, Any]) -> bool:
        return (m['state'] in ('alive', 'suspect') and m['name'] != self.node.name
                and 'key_directory' in (m['record'].get('features') or []) and not self.skip(m['name']))

    def pull(self, m: Dict[str, Any], since: Optional[int] = None) -> int:
        """Pull ``m``'s records changed since ``since`` (default: the held version); returns how many
        were stored. Raises the node's transport and refusal errors."""
        name = m['name']
        since = self.store.version(self.net, name) if since is None else int(since)
        stored, pages = 0, 0
        while pages < 1000:
            pages += 1
            x = self.node.request(m['record']['url'], P + '/keys', {'since': since, 'limit': self.page}, name)
            body = x.body
            if not isinstance(body, dict) or schemas.errors('keys_response', body) or body['home_instance'] != x.sender:
                raise NetError('invalid_request', f'{name}: the key delta response fails its schema')
            for rec in body['records']:
                why = acceptance_error(rec, self.net, x.sender, x.verified.certificate)
                if why is not None:
                    logger.warning(f'SAJHA Net {self.net}: key record {str(rec.get("key_id"))[:64]} from {name} '
                                   f'ignored ({why})')
                    continue
                if self.store.put(dict(rec)):
                    stored += 1
                    self.node.kv.set(f'kd:signer:{rec["signature"]["keyid"]}',
                                     crypto.serial_hex(x.verified.certificate))
            if not body.get('more'):
                break
            nxt = int(body.get('next_since') or 0)
            if nxt <= since:
                break
            since = nxt
        return stored

    def compare(self, m: Dict[str, Any]) -> bool:
        """§11.4: True when ``m``'s digest matches what this participant holds for it (else re-pull from 0)."""
        name = m['name']
        x = self.node.request(m['record']['url'], P + '/keys/digest', {}, name)
        body = x.body
        if not isinstance(body, dict) or schemas.errors('keys_digest_response', body):
            raise NetError('invalid_request', f'{name}: the key digest response fails its schema')
        held = self.store.since(self.net, name, 0, limit=10 ** 9)
        if digest_root(held) == body['root'] and len(held) == int(body['count']):
            return True
        self.pull(m, since=0)
        return False

    def apply_revocations(self) -> int:
        """§11.2: discard the records signed by a revoked certificate and re-pull those homes from 0."""
        rl = self.node.revocation_list() or {}
        revoked = {str(r.get('serial') or '').lower() for r in rl.get('revoked') or [] if r.get('serial')}
        names = {str(r.get('instance')) for r in rl.get('revoked') or [] if r.get('instance')}
        dropped = 0
        for k, serial in list(self.node.kv.scan('kd:signer:')):
            keyid = k[len('kd:signer:'):]
            if str(serial).lower() in revoked:
                for home in self.store.discard_signed(self.net, keyid):
                    self.node.kv.set(f'kd:repull:{home}', True)
                    dropped += 1
                self.node.kv.delete(k)
        for home in names:
            self.store.mark(self.net, home, 'revoked')
        return dropped

    def tick(self) -> None:
        """The key directory's share of a protocol period (the gossip agent calls it)."""
        try:
            self.publish()
        except Exception as e:
            logger.warning(f'SAJHA Net {self.net}: publishing key records failed: {e}', exc_info=True)
        if not self.sync:
            return
        rl = self.node.revocation_list() or {}
        if int(rl.get('version') or 0) != self._rl_version:
            self._rl_version = int(rl.get('version') or 0)
            self.apply_revocations()
        now = self.node.clock()
        full = now - self._last_full >= self.full_sync_interval
        for m in self.node.members():
            name = m['name']
            if m['state'] == 'left':
                self.store.mark(self.net, name, 'left')
            if not self._member_ok(m):
                continue
            if self.store.marked(self.net, name) == 'left':
                self.store.mark(self.net, name, None)            # it came back
            try:
                theirs = int((m['record'].get('digests') or {}).get('keys') or 0)
                if self.node.kv.get(f'kd:repull:{name}'):
                    self.pull(m, since=0)
                    self.node.kv.delete(f'kd:repull:{name}')
                elif theirs > self.store.version(self.net, name):
                    self.pull(m)
                if full:
                    self.compare(m)
                self._ok(name)
            except Exception as e:
                self._failed(name, e)
        if full:
            self._last_full = now

    def _ok(self, name: str) -> None:
        if self.node.kv.get(f'kd:fail:{name}'):
            self.node.kv.delete(f'kd:fail:{name}')
            self.node.event('key_sync_ok', member=name)

    def _failed(self, name: str, e: Exception) -> None:
        n = int(self.node.kv.update(f'kd:fail:{name}', lambda cur: int(cur or 0) + 1) or 0)
        logger.info(f'SAJHA Net {self.net}: key directory sync with {name} failed ({n}): {e}')
        if n >= FAILURES_BEFORE_NOTICE:
            self.node.event('key_sync_failed', member=name, failures=n, detail=str(e)[:300])

    # ── lookups ─────────────────────────────────────────────────────

    def home_usable(self, home: str) -> bool:
        """A home's records are usable while it is a member that has not left and is not revoked."""
        if home == self.node.name:
            return True
        if self.store.marked(self.net, home):
            return False
        m = self.node.member(home)
        if m is None or m['state'] == 'left':
            return False
        rl = self.node.revocation_list() or {}
        return not any(r.get('instance') == home for r in rl.get('revoked') or [])
