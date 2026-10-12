# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
User identity at the agent (protocol §15.3, §15.5, §15.9, §16): the three resolvers, on both sides, for a
participant with no accounts of its own beyond the users of its configuration file.

* **Home.** A local client presents one of the agent's keys (configuration file ``users``); the agent
  publishes a key record for every one of them in the net key directory (kept in ``own_keys.json`` in the
  data directory, so versions only grow across restarts) and, per call, sends the first resolver of its
  ``identity`` list that the host lists: ``api_key`` (the presented key, over HTTPS only), ``assertion``
  (a user assertion it signs: ``aud`` = the host, or the origin of a re-exported tool, at most 60 seconds,
  a ``jti`` and the call's trace id; only a key id crosses) or ``token_exchange`` (that assertion exchanged
  at the host's ``/sajhanet/v1/token`` for a host-scoped token, cached until shortly before it expires).
  A call to a re-exported tool always carries an assertion for its origin.
* **Host.** It accepts the resolvers of its ``identity`` list (an assertion also in the re-export cases of
  §16, as SAJHA does): the forwarded key against the key directory, the assertion's schema, net, issuer,
  signature, audience, time window, one use of ``jti``, trace id and key record, or a token it issued;
  and serves the token endpoint when it lists ``token_exchange``. The user is the key's owner at their
  home, with their roles there (mapping ``home_identity``): the agent maps nobody.

Built on the protocol core only (``tests/test_sajhanet_agent_boundary.py``); the behaviour mirrors SAJHA's
``assertion`` and ``token_exchange`` resolvers.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.net import crypto, jcs, keydir, names, schemas
from sajha.net.errors import NetError
from sajha.net.plugins import IdentityResolver, MemoryKeyDirectory, PeerUnreachable

logger = logging.getLogger('sajhanet_agent')

API_KEY_HEADER = 'sajha-net-api-key'
ASSERTION_HEADER = 'sajha-net-user-assertion'
TOKEN_HEADER = 'sajha-net-user-token'
ASSERTION_MAX_LIFETIME = 60
CLOCK_SKEW = 5
TOKEN_PATH = '/sajhanet/v1/token'
GRANT = 'urn:ietf:params:oauth:grant-type:token-exchange'
SUBJECT_TYPE = 'urn:sajha:net:user-assertion'
ISSUED_TYPE = 'urn:ietf:params:oauth:token-type:access_token'
REFRESH_MARGIN = 10


class FileKeyDirectory(MemoryKeyDirectory):
    """The key directory store of an agent: every record in memory, and this participant's own records
    also in a file, so its record versions keep growing across restarts (a receiver ignores a version it
    has seen, protocol §11.2). Other homes' records are pulled again after a restart."""
    name = 'agent_file'

    def __init__(self, path: str, me: Callable[[], str]):
        super().__init__()
        self.path = path
        self.me = me
        self._lock = threading.Lock()
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for r in json.load(f) or []:
                    if isinstance(r, dict) and r.get('key_id') and r.get('net'):
                        self._by[(r['net'], r['key_id'])] = r
        except (OSError, ValueError):
            pass

    def put(self, record, force=False):
        ok = super().put(record, force)
        if ok and self.path and record.get('home_instance') == self.me():
            self._save()
        return ok

    def _save(self) -> None:
        me = self.me()
        with self._lock:
            mine = [r for r in self._by.values() if r.get('home_instance') == me]
            d = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(d, mode=0o700, exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(mine, f, indent=1, sort_keys=True)
            os.replace(tmp, self.path)


def own_key_bodies(policy) -> List[Dict[str, Any]]:
    """Key record bodies (protocol §11.1) of every key in the configuration file."""
    out = []
    for u in policy.users:
        for k in u.keys:
            out.append({'key_id': k.id, 'key_prefix': k.key_prefix[:16], 'name': k.name[:255], 'key_hash': k.key_hash,
                        'owner': {'user_id': u.user_name, 'user_name': u.user_name,
                                  'display_name': u.display_name or u.user_name, 'roles': sorted(u.roles)},
                        'enabled': bool(k.enabled and u.enabled), 'expires_at': k.expires_at, 'revoked_at': None,
                        'tool_access_mode': k.tool_access_mode, 'tool_access_list': list(k.tool_access_list),
                        'persistent': True})
    return out


def _lower(headers) -> Dict[str, str]:
    return {str(k).lower(): v for k, v in (headers or {}).items()}


class AgentIdentity(IdentityResolver):
    """The agent's resolver on both sides (see the module docstring). ``participant`` is the
    :class:`~sajha.net.library.NetParticipant`; ``policy()`` the current configuration."""
    name = 'agent'

    def __init__(self, policy: Callable[[], Any]):
        self.policy = policy
        self.p = None                                      # set once the participant is built
        self._tokens: Dict[Tuple[str, str], Tuple[str, float]] = {}
        self._lock = threading.Lock()
        self.exchanges = 0

    # ── helpers ────────────────────────────────────────────────────

    @property
    def node(self):
        return self.p.node

    def listed(self) -> List[str]:
        return list(self.policy().identity)

    def _record(self, home: str, key_id: str) -> Optional[Dict[str, Any]]:
        kd = self.p.keys
        if kd is None:
            return None
        return kd.store.by_id(self.node.net, home, key_id)

    def _usable(self, rec, home: str) -> Optional[str]:
        kd = self.p.keys
        return keydir.check_usable(rec, home, self.node.clock(), kd.home_usable if kd else None)

    # ── home ───────────────────────────────────────────────────────

    def choose(self, host: str) -> str:
        """The first resolver of this agent's list that ``host`` lists (else the first of the list)."""
        mine = self.listed()
        m = self.node.member(host) if host else None
        theirs = list((((m or {}).get('record') or {}).get('user_identity')) or [])
        return next((i for i in mine if i in theirs), mine[0] if mine else 'api_key')

    def outbound_headers(self, user):
        if not isinstance(user, dict) or not user.get('key_id'):
            return {}                                     # a call without a user: the service identity
        net, host = user.get('_target') or (self.node.net, '')
        if user.get('_origin'):                           # §16: a re-exported tool, within one net
            user['_identity'] = 'assertion'
            return {'Sajha-Net-User-Assertion': self.make_assertion(user, str(user['_origin']), user.get('_trace_id'))}
        choice = self.choose(host)
        user['_identity'] = choice
        if choice == 'assertion':
            return {'Sajha-Net-User-Assertion': self.make_assertion(user, host, user.get('_trace_id'))}
        if choice == 'token_exchange':
            return {'Sajha-Net-User-Token': self.token_for(host, user)}
        raw = user.get('_api_key')
        if not raw:
            raise NetError('key_unknown', 'the caller presented no key that could be forwarded')
        return {'Sajha-Net-Api-Key': raw}

    def make_assertion(self, user: Dict[str, Any], aud: str, trace_id: Optional[str] = None,
                       override: Optional[Dict[str, Any]] = None) -> str:
        """A user assertion signed with this participant's certificate (protocol §15.5), as the header value."""
        node = self.node
        kid = str(user.get('key_id') or '')
        rec = self._record(node.name, kid)
        if rec is None or self._usable(rec, node.name) is not None:
            raise NetError('key_disabled', 'the caller\'s key is not published (or not usable) in the net key directory')
        login = str((rec.get('owner') or {}).get('user_name') or '')
        now = int(node.clock())
        life = max(1, min(ASSERTION_MAX_LIFETIME, int(self.policy().assertion_ttl_seconds)))
        body = {'type': 'assertion', 'net': node.net, 'iss': node.name, 'user': names.net_user(login, node.name),
                'key_id': kid, 'aud': aud, 'iat': now, 'exp': now + life, 'jti': secrets.token_hex(16),
                'trace_id': trace_id or secrets.token_hex(16)}
        body.update(override or {})
        signer = node.signer
        signed = dict(body, signature=crypto.sign_record('assertion', body, signer.key, signer.keyid))
        return crypto.b64url(jcs.canonicalize(signed))

    def token_for(self, host: str, user: Dict[str, Any]) -> str:
        k = (host, str(user.get('key_id') or ''))
        now = self.node.clock()
        with self._lock:
            hit = self._tokens.get(k)
        if hit and hit[1] - REFRESH_MARGIN > now:
            return hit[0]
        token, expires = self.exchange(host, user)
        with self._lock:
            self._tokens[k] = (token, expires)
        return token

    def exchange(self, host: str, user: Dict[str, Any]) -> Tuple[str, float]:
        from sajha.net.node import PeerRefused
        from sajha.net.routing import CODES
        node = self.node
        m = node.member(host)
        if m is None:
            raise NetError('unavailable', f'{host} is not a member of {node.net}')
        body = {'grant_type': GRANT, 'subject_token': self.make_assertion(user, host, user.get('_trace_id')),
                'subject_token_type': SUBJECT_TYPE, 'audience': host}
        try:
            x = node.request(m['record']['url'], TOKEN_PATH, body, host)
        except PeerRefused as e:
            reason = str((e.body or {}).get('reason') or 'token_invalid')
            raise NetError(reason if reason in CODES else 'token_invalid', 'the host refused the token exchange')
        except PeerUnreachable as e:
            raise NetError('unreachable', f'the token endpoint of {host} could not be reached: {e}')
        data = x.body if isinstance(x.body, dict) else {}
        if schemas.errors('token_response', data):
            raise NetError('token_invalid', f'{host} answered the token exchange with an invalid body')
        self.exchanges += 1
        return str(data['access_token']), node.clock() + int(data['expires_in'])

    def forget(self, net: str, host: str, user=None) -> None:
        kid = str((user or {}).get('key_id') or '')
        with self._lock:
            for k in [k for k in self._tokens if k[0] == host and (not kid or k[1] == kid)]:
                self._tokens.pop(k, None)

    # ── host ───────────────────────────────────────────────────────

    def resolve(self, headers, sender, **kw):
        h = _lower(headers)
        present = [n for n, hd in (('api_key', API_KEY_HEADER), ('assertion', ASSERTION_HEADER),
                                   ('token_exchange', TOKEN_HEADER)) if h.get(hd)]
        if len(present) > 1:
            raise NetError('ambiguous_credentials', 'a forwarded call carries one user credential')
        if not present:
            return None
        listed = self.listed()
        me = self.node.name
        audience = str(kw.get('audience') or me)
        which = present[0]
        if which == 'api_key':
            if 'api_key' not in listed:
                raise NetError('key_unknown', 'this host does not accept the api_key identity')
            if audience != me:
                raise NetError('assertion_invalid', 'a call to a re-exported tool carries a user assertion')
            return self._api_key(h, sender, kw.get('secure'))
        if which == 'token_exchange':
            if 'token_exchange' not in listed:
                raise NetError('token_invalid', 'this host does not accept the token_exchange identity')
            return self._token(h, sender)
        if 'assertion' not in listed and not self._reexport_case(h, sender, audience, kw):
            raise NetError('assertion_invalid', f'this host does not accept the assertion identity (it lists '
                                                f'{", ".join(listed) or "none"})')
        v = self.verify_assertion(h[ASSERTION_HEADER], sender, audience=audience, hop=int(kw.get('hop') or 1),
                                  visited=kw.get('visited'), trace_id=kw.get('trace_id'))
        return self._mapped(v)

    def _reexport_case(self, h: Dict[str, str], sender: str, audience: str, kw: Dict[str, Any]) -> bool:
        """The documented re-export case within one net (§16): an assertion for this host's origin (this
        host is the intermediary), or the caller's assertion relayed unchanged to this host (a later hop,
        issued by an instance other than the sender)."""
        if audience != self.node.name:
            return True
        if int(kw.get('hop') or 1) <= 1:
            return False
        try:
            doc = json.loads(crypto.unb64url(str(h.get(ASSERTION_HEADER) or '')).decode('utf-8'))
        except Exception:
            return False
        return isinstance(doc, dict) and bool(doc.get('iss')) and doc.get('iss') != sender

    def _api_key(self, h: Dict[str, str], sender: str, secure) -> Dict[str, Any]:
        if secure is False and self.node.cfg.require_https:
            raise NetError('https_required', 'a forwarded key is accepted only over HTTPS')
        kd = self.p.keys
        if kd is None:
            raise NetError('key_unknown', 'this host keeps no key directory')
        kh = keydir.key_hash(str(h.get(API_KEY_HEADER)))
        recs = kd.store.find(self.node.net, kh)
        rec = next((r for r in recs if r.get('home_instance') == sender), recs[0] if recs else None)
        why = self._usable(rec, sender)
        if why is not None:
            raise NetError(why)
        return self._mapped(self._verified(rec, 'api_key'))

    @staticmethod
    def _verified(rec: Dict[str, Any], identity: str) -> Dict[str, Any]:
        owner = rec.get('owner') or {}
        login = str(owner.get('user_name') or '')
        roles = [str(r) for r in owner.get('roles') or []]
        return {'name': names.net_user(login, rec['home_instance']), 'net': rec['net'], 'home': rec['home_instance'],
                'user_name': login, 'display_name': str(owner.get('display_name') or login), 'remote_roles': roles,
                'key_id': rec['key_id'], 'key_prefix': rec.get('key_prefix', ''),
                'tool_access_mode': rec.get('tool_access_mode') or 'all',
                'tool_access_list': list(rec.get('tool_access_list') or []), 'identity': identity}

    @staticmethod
    def _mapped(v: Dict[str, Any]) -> Dict[str, Any]:
        """The agent has no accounts: the user is the key's owner at their home, with their roles there."""
        return dict(v, user_id=v['name'], roles=list(v['remote_roles']), mapping='home_identity', authenticated=True)

    def _issuer_certificate(self, iss: str, keyid: str):
        node = self.node
        if iss == node.name:
            chain = list(node.signer.chain)
        else:
            chain_b64 = node.kv.get('cert:' + keyid) or (node.member(iss) or {}).get('certificate')
            if not chain_b64:
                raise NetError('assertion_invalid', f'no certificate of {iss} is known here')
            chain = crypto.chain_from_b64(chain_b64)
        try:
            node.trust.check_chain(chain, node.clock())
        except crypto.CryptoError as e:
            raise NetError('assertion_invalid', f'the certificate of {iss} does not verify: {e.detail}')
        o, cn = crypto.subject_of(chain[0])
        if o != node.net or cn != iss:
            raise NetError('assertion_invalid', 'the assertion is not signed by its issuer in this net')
        from sajha.net.trust import revocation_reason
        if node.trust.revocation(crypto.serial_hex(chain[0]), cn or '') or \
                revocation_reason(node.kv.get('rl'), '', iss):
            raise NetError('assertion_invalid', f'the certificate of {iss} is revoked')
        if crypto.thumbprint(crypto.cert_der(chain[0])) != keyid:
            raise NetError('assertion_invalid', 'keyid is not the issuer certificate thumbprint')
        return chain[0]

    def verify_assertion(self, value: str, sender: str, *, audience: str, hop: int = 1,
                         visited: Optional[List[str]] = None, trace_id: Optional[str] = None,
                         consume: bool = True) -> Dict[str, Any]:
        """The verified net user of an assertion (protocol §15.5), or ``assertion_invalid`` and the key
        reasons of §15.3."""
        node = self.node
        net = node.net
        try:
            doc = json.loads(crypto.unb64url(str(value)).decode('utf-8'))
        except Exception:
            raise NetError('assertion_invalid', 'the assertion is not base64url JSON')
        if not isinstance(doc, dict) or schemas.errors('user_assertion', doc):
            raise NetError('assertion_invalid', 'the assertion fails its schema')
        if doc['net'] != net:
            raise NetError('assertion_invalid', 'the assertion is for another net')
        iss = doc['iss']
        if hop <= 1 and iss != sender:
            raise NetError('assertion_invalid', 'on a direct call the assertion is issued by the sender')
        if hop > 1 and f'{net}/{iss}' not in (visited or []) and iss != sender:
            raise NetError('assertion_invalid', 'the issuer is not on the call chain')
        sig = doc.get('signature') or {}
        cert = self._issuer_certificate(iss, str(sig.get('keyid') or ''))
        body = {k: v for k, v in doc.items() if k != 'signature'}
        if not crypto.verify_record('assertion', body, sig, cert.public_key()):
            raise NetError('assertion_invalid', 'the assertion signature does not verify')
        if doc['aud'] != audience:
            raise NetError('assertion_invalid', f'the assertion is for {doc["aud"]}, not {audience}')
        now = node.clock()
        if doc['exp'] - doc['iat'] > ASSERTION_MAX_LIFETIME or doc['exp'] <= now - CLOCK_SKEW or \
                doc['iat'] > now + CLOCK_SKEW:
            raise NetError('assertion_invalid', 'the assertion has expired or is not valid yet')
        if trace_id and doc['trace_id'] != trace_id:
            raise NetError('assertion_invalid', 'the assertion belongs to another trace')
        if consume and not node.kv.add(f'jti:{iss}:{doc["jti"]}', 1, ttl=ASSERTION_MAX_LIFETIME * 2 + CLOCK_SKEW):
            raise NetError('assertion_invalid', 'the assertion was already used')
        rec = self._record(iss, doc['key_id'])
        why = self._usable(rec, iss)
        if why is not None:
            raise NetError(why)
        v = self._verified(rec, 'assertion')
        if doc['user'] != v['name']:
            raise NetError('assertion_invalid', 'the assertion names a user who does not own the key')
        return v

    @staticmethod
    def _token_key(token: str) -> str:
        return 'tok:' + hashlib.sha256(token.encode('utf-8')).hexdigest()

    def serve_token(self, data: Dict[str, Any], v) -> Dict[str, Any]:
        """``POST /sajhanet/v1/token`` (protocol §15.9): a valid assertion for this host, from its issuer,
        exchanged for an opaque token bound to this net and to the home that asked (kept hashed)."""
        node = self.node
        if data.get('audience') != node.name:
            raise NetError('assertion_invalid', f'the token exchange is for {data.get("audience")}, not {node.name}')
        verified = self.verify_assertion(data['subject_token'], v.sender, audience=node.name, hop=1)
        token = secrets.token_urlsafe(32)
        ttl = int(max(1, min(3600, self.policy().token_ttl_seconds)))
        node.kv.set(self._token_key(token), {'net': node.net, 'home': v.sender, 'verified': verified}, ttl=ttl)
        logger.info(f'SAJHA Net {node.net}: token issued to {v.sender} for {verified["name"]} '
                    f'(key {verified["key_id"]}, {ttl} s)')
        return {'access_token': token, 'issued_token_type': ISSUED_TYPE, 'token_type': 'N_A', 'expires_in': ttl}

    def _token(self, h: Dict[str, str], sender: str) -> Dict[str, Any]:
        node = self.node
        held = node.kv.get(self._token_key(str(h.get(TOKEN_HEADER))))
        if not isinstance(held, dict) or held.get('net') != node.net or held.get('home') != sender:
            raise NetError('token_invalid', 'the token is unknown here, expired, or was issued to another instance')
        v = dict(held['verified'])
        why = self._usable(self._record(v['home'], v['key_id']), v['home'])
        if why is not None:
            raise NetError(why)
        v['identity'] = 'token_exchange'
        return self._mapped(v)
