"""
SAJHA Net user identity beyond API keys (design §10.2, §14; protocol §15.5, §15.9, §16).

* :class:`AssertionIdentity` (identity resolver ``assertion``). **Home:** a user assertion signed with
  this participant's certificate in the net of the call (``type: "assertion"``: ``net``, ``iss`` = this
  instance, ``user`` = ``<login>@<iss>`` from the key record, ``key_id`` of a key of that user published
  in the net key directory, ``aud`` = the host, or the origin of a re-exported tool, a lifetime of at most
  60 seconds, a ``jti`` and the call's trace id), sent in ``Sajha-Net-User-Assertion``. Only a key id
  crosses, never a key. **Host:** the assertion's schema, net, issuer (the sender on hop 1, an instance
  the chain passed otherwise), signature against a valid certificate of the issuer, audience, time window,
  one use of ``jti``, trace id, and the key record (usable, of that home, owned by ``user``); then the
  block on the user and the mapping of design §11.3, exactly as for ``api_key``.
* :class:`TokenExchangeIdentity` (``token_exchange``). **Home:** exchanges a user assertion (``aud`` =
  the host) at the host's ``/sajhanet/v1/token`` (a signed request, RFC 8693 shaped) for an opaque
  host-scoped token, caches it per host and key until shortly before it expires, and sends it in
  ``Sajha-Net-User-Token``. **Host:** verifies the assertion as above, maps the user, and issues a token
  bound to the net and to the home that asked (kept hashed in the state store, ``token_exchange.ttl_seconds``);
  on each call it re-checks the key record, the block and the mapping. An unknown or expired token is
  ``-32013 token_invalid``, after which the home exchanges again once.
* :class:`NetIdentity`: the resolver the router and the hosts use. Per net it sends the first resolver of
  ``user_identity`` (a net entry's, else ``sajhanet.user_identity``) that the host advertises, and accepts
  the resolvers it lists; a call to a re-exported tool (an ``origin``) and a bridge's call into another net
  always use ``assertion``, and a host always accepts an assertion on such a call (hop > 1, or an audience
  other than itself). Per-member keys (``sajhanet.peer_keys``) and the test admin key stay features of
  ``api_key`` (:class:`~sajha.net.integration.authz.ApiKeyIdentity`); an assertion names a key of the user
  in the key directory, never either of them.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from typing import Any, Dict, List, Optional, Tuple

from sajha.net import crypto, jcs, keydir, names, plugins, schemas
from sajha.net.errors import NetError

logger = logging.getLogger(__name__)

ASSERTION_HEADER = 'sajha-net-user-assertion'
TOKEN_HEADER = 'sajha-net-user-token'
API_KEY_HEADER = 'sajha-net-api-key'
KNOWN = ('api_key', 'assertion', 'token_exchange', 'none')
ASSERTION_MAX_LIFETIME = 60
CLOCK_SKEW = 5
TOKEN_PATH = '/sajhanet/v1/token'
GRANT = 'urn:ietf:params:oauth:grant-type:token-exchange'
SUBJECT_TYPE = 'urn:sajha:net:user-assertion'
ISSUED_TYPE = 'urn:ietf:params:oauth:token-type:access_token'


def _authz_of(obj) -> Any:
    if getattr(obj, '_authz', None) is not None:
        return obj._authz
    try:
        from sajha.net.integration import get_service
        svc = get_service()
        return getattr(svc, 'authz', None) if svc is not None else None
    except Exception:
        return None


def _home_user(a, user: Optional[Dict[str, Any]]) -> bool:
    """False when no user travels (anonymous, allowed); raises ``anonymous`` when anonymous is refused."""
    if not user or not user.get('authenticated', True) or str(user.get('user_id') or 'anonymous') == 'anonymous':
        if a.anonymous_may_call_remote(str((user or {}).get('net') or '')):
            return False
        raise NetError('anonymous', 'the call needs a signed-in user')
    return True


def _lower(headers) -> Dict[str, str]:
    return {str(k).lower(): v for k, v in (headers or {}).items()}


# ── assertions: the home signs, the host verifies ───────────────────

def own_record(st, key_id: str) -> Optional[Dict[str, Any]]:
    """This home's published key record ``key_id`` in the net of ``st``."""
    if not key_id or st.keys is None:
        return None
    for r in st.keys.own_records():
        if r.get('key_id') == key_id:
            return r
    return None


def record_of(st, home: str, key_id: str) -> Optional[Dict[str, Any]]:
    """The key record ``key_id`` of ``home`` in the net key directory of ``st``."""
    store = st.store
    getter = getattr(store, 'by_id', None)
    if callable(getter):
        return getter(st.net, home, key_id)
    return next((r for r in store.since(st.net, home, 0, limit=10 ** 6) if r.get('key_id') == key_id), None)


def key_id_for(a, st, user: Dict[str, Any]) -> str:
    """The id of a key of ``user`` that this home publishes in the net of ``st``: the key presented on this
    request, else the user's default key, else the user's newest usable key. Never a per-member key and
    never the test admin key (those belong to the ``api_key`` resolver)."""
    own = {r['key_id']: r for r in (st.keys.own_records() if st.keys is not None else [])}
    now = st.now()

    def usable(kid: str) -> bool:
        r = own.get(kid)
        return r is not None and keydir.check_usable(r, st.me, now) is None
    uid = str(user.get('user_id') or '')
    from sajha.auth.presented_key import presented
    p = presented()
    if p is not None and p.key_id and (not uid or p.user_id == uid) and usable(p.key_id):
        return p.key_id
    if user.get('api_key'):
        kh = keydir.key_hash(str(user['api_key']))
        hit = next((k for k, r in own.items() if r.get('key_hash') == kh), '')
        if hit and usable(hit):
            return hit
    if not uid or uid.startswith('apikey:'):
        return ''
    db = a.db()
    try:
        from sajha.auth.apikeys import default_key_of, keys_of
        from sajha.db.models import User
        row = db.query(User).filter(User.user_id == uid).first()
        if row is None or not row.enabled:
            return ''
        k = default_key_of(db, row)
        if k is not None and usable(str(k.id)):
            return str(k.id)
        for k in sorted(keys_of(db, row, include_revoked=False), key=lambda k: str(getattr(k, 'created_at', '') or ''),
                        reverse=True):
            if usable(str(k.id)):
                return str(k.id)
        return ''
    finally:
        try:
            db.close()
        except Exception:
            pass


def make_assertion(a, net: str, user: Dict[str, Any], aud: str, trace_id: Optional[str] = None,
                   lifetime: Optional[int] = None, override: Optional[Dict[str, Any]] = None) -> str:
    """A signed user assertion for ``user`` toward ``aud`` in ``net``, as the header value (base64url of the
    JCS bytes). ``override`` replaces members before signing (tests)."""
    st = a.nets.get(net)
    if st is None:
        raise NetError('key_unknown', f'this server is not in net {net}')
    kid = key_id_for(a, st, user)
    if not kid and st.keys is not None:
        st.keys.publish()                                  # a key created since the last publication
        kid = key_id_for(a, st, user)
    if not kid:
        raise NetError('key_disabled', 'no usable API key of this user is published in the net key directory')
    rec = own_record(st, kid)
    login = str(((rec or {}).get('owner') or {}).get('user_name') or '')
    if not login:
        raise NetError('key_unknown', 'the key record names no owner')
    now = int(st.now())
    life = int(lifetime or st.settings.assertion_ttl_seconds)
    body = {'type': 'assertion', 'net': net, 'iss': st.me, 'user': names.net_user(login, st.me), 'key_id': kid,
            'aud': aud, 'iat': now, 'exp': now + max(1, min(ASSERTION_MAX_LIFETIME, life)),
            'jti': secrets.token_hex(16), 'trace_id': trace_id or secrets.token_hex(16)}
    body.update(override or {})
    signer = st.node.signer
    signed = dict(body, signature=crypto.sign_record('assertion', body, signer.key, signer.keyid))
    if isinstance(user, dict):
        user['key_id'] = kid
    return crypto.b64url(jcs.canonicalize(signed))


def _issuer_certificate(st, iss: str, keyid: str):
    node = st.node
    if iss == st.me:
        chain = list(node.signer.chain)
    else:
        chain_b64 = node.kv.get('cert:' + keyid) or (node.member(iss) or {}).get('certificate')
        if not chain_b64:
            raise NetError('assertion_invalid', f'no certificate of {iss} is known here')
        chain = crypto.chain_from_b64(chain_b64)
    now = st.now()
    try:
        node.trust.check_chain(chain, now)
    except crypto.CryptoError as e:
        raise NetError('assertion_invalid', f'the certificate of {iss} does not verify: {e.detail}')
    o, cn = crypto.subject_of(chain[0])
    if o != st.net or cn != iss:
        raise NetError('assertion_invalid', 'the assertion is not signed by its issuer in this net')
    from sajha.net.trust import revocation_reason
    if node.trust.revocation(crypto.serial_hex(chain[0]), cn or '') or revocation_reason(node.kv.get('rl'), '', iss):
        raise NetError('assertion_invalid', f'the certificate of {iss} is revoked')
    if crypto.thumbprint(crypto.cert_der(chain[0])) != keyid:
        raise NetError('assertion_invalid', 'keyid is not the issuer certificate thumbprint')
    return chain[0]


def verify_assertion(a, net: str, value: str, sender: str, *, audience: str, hop: int = 1,
                     visited: Optional[List[str]] = None, trace_id: Optional[str] = None,
                     consume: bool = True) -> Dict[str, Any]:
    """The verified net user (before mapping) of an assertion, or ``NetError('assertion_invalid')`` and the
    key reasons of protocol §15.3 (other than possession)."""
    st = a.nets.get(net)
    if st is None:
        raise NetError('assertion_invalid', 'this host keeps no key directory for the net')
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
    cert = _issuer_certificate(st, iss, str(sig.get('keyid') or ''))
    body = {k: v for k, v in doc.items() if k != 'signature'}
    if not crypto.verify_record('assertion', body, sig, cert.public_key()):
        raise NetError('assertion_invalid', 'the assertion signature does not verify')
    if doc['aud'] != audience:
        raise NetError('assertion_invalid', f'the assertion is for {doc["aud"]}, not {audience}')
    now = st.now()
    if doc['exp'] - doc['iat'] > ASSERTION_MAX_LIFETIME or doc['exp'] <= now - CLOCK_SKEW or \
            doc['iat'] > now + CLOCK_SKEW:
        raise NetError('assertion_invalid', 'the assertion has expired or is not valid yet')
    if trace_id and doc['trace_id'] != trace_id:
        raise NetError('assertion_invalid', 'the assertion belongs to another trace')
    if consume and not st.node.kv.add(f'jti:{iss}:{doc["jti"]}', 1, ttl=ASSERTION_MAX_LIFETIME * 2 + CLOCK_SKEW):
        raise NetError('assertion_invalid', 'the assertion was already used')
    rec = record_of(st, iss, doc['key_id'])
    why = keydir.check_usable(rec, iss, now, st.keys.home_usable if st.keys else None)
    if why is not None:
        raise NetError(why)
    owner = rec.get('owner') or {}
    login = str(owner.get('user_name') or '')
    if doc['user'] != names.net_user(login, iss):
        raise NetError('assertion_invalid', 'the assertion names a user who does not own the key')
    return {'name': doc['user'], 'net': net, 'home': iss, 'user_name': login,
            'home_user_id': str(owner.get('user_id') or ''), 'display_name': str(owner.get('display_name') or login),
            'remote_roles': [str(r) for r in owner.get('roles') or []], 'key_id': rec['key_id'],
            'key_prefix': rec.get('key_prefix', ''), 'tool_access_mode': rec.get('tool_access_mode') or 'all',
            'tool_access_list': list(rec.get('tool_access_list') or []), 'identity': 'assertion'}


# ── the resolvers ───────────────────────────────────────────────────

@plugins.register('identity')
class AssertionIdentity(plugins.IdentityResolver):
    """``assertion``: a home-signed user assertion (see the module docstring)."""
    name = 'assertion'

    def __init__(self, authz=None):
        self._authz = authz

    @property
    def authz(self):
        return _authz_of(self)

    def outbound_headers(self, user):
        a = self.authz
        if a is None:
            return {}
        if not _home_user(a, user):
            return {}
        net, host = (user.get('_target') or ('', ''))
        aud = str(user.get('_origin') or host)
        user['_identity'] = 'assertion'
        return {'Sajha-Net-User-Assertion': make_assertion(a, net, user, aud, user.get('_trace_id'))}

    def resolve(self, headers, sender, **kw):
        h = _lower(headers)
        raw = h.get(ASSERTION_HEADER, '')
        if not raw:
            return None
        a = self.authz
        net = str(h.get('sajha-net-name', '') or '')
        if a is None or net not in a.nets:
            raise NetError('assertion_invalid', 'this host keeps no key directory for the net')
        st = a.nets[net]
        v = verify_assertion(a, net, raw, sender, audience=str(kw.get('audience') or st.me),
                             hop=int(kw.get('hop') or 1), visited=kw.get('visited'), trace_id=kw.get('trace_id'))
        return a.finish(st, v)


@plugins.register('identity')
class TokenExchangeIdentity(plugins.IdentityResolver):
    """``token_exchange``: a host-scoped token obtained with a user assertion (see the module docstring)."""
    name = 'token_exchange'
    REFRESH_MARGIN = 10

    def __init__(self, authz=None):
        self._authz = authz
        self._cache: Dict[Tuple[str, str, str], Tuple[str, float]] = {}
        self._lock = threading.Lock()
        self.exchanges = 0

    @property
    def authz(self):
        return _authz_of(self)

    # home
    def outbound_headers(self, user):
        a = self.authz
        if a is None:
            return {}
        if not _home_user(a, user):
            return {}
        net, host = (user.get('_target') or ('', ''))
        st = a.nets.get(net)
        if st is None:
            raise NetError('token_invalid', f'this server is not in net {net}')
        kid = key_id_for(a, st, user)
        if not kid:
            raise NetError('key_disabled', 'no usable API key of this user is published in the net key directory')
        k = (net, host, kid)
        now = st.now()
        with self._lock:
            hit = self._cache.get(k)
        user['_identity'] = 'token_exchange'
        user['key_id'] = kid
        if hit and hit[1] - self.REFRESH_MARGIN > now:
            return {'Sajha-Net-User-Token': hit[0]}
        token, expires = self.exchange(a, st, host, user)
        with self._lock:
            self._cache[k] = (token, expires)
        return {'Sajha-Net-User-Token': token}

    def exchange(self, a, st, host: str, user: Dict[str, Any]) -> Tuple[str, float]:
        from sajha.net.node import PeerRefused
        m = st.node.member(host)
        if m is None:
            raise NetError('unavailable', f'{host} is not a member of {st.net}')
        body = {'grant_type': GRANT, 'subject_token': make_assertion(a, st.net, user, host, user.get('_trace_id')),
                'subject_token_type': SUBJECT_TYPE, 'audience': host}
        try:
            x = st.node.request(m['record']['url'], TOKEN_PATH, body, host)
        except PeerRefused as e:
            reason = str((e.body or {}).get('reason') or 'token_invalid')
            from sajha.net.routing import CODES
            raise NetError(reason if reason in CODES else 'token_invalid', 'the host refused the token exchange')
        except plugins.PeerUnreachable as e:
            raise NetError('unreachable', f'the token endpoint of {host} could not be reached: {e}')
        data = x.body if isinstance(x.body, dict) else {}
        if schemas.errors('token_response', data):
            raise NetError('token_invalid', f'{host} answered the token exchange with an invalid body')
        self.exchanges += 1
        return str(data['access_token']), st.now() + int(data['expires_in'])

    def forget(self, net: str, host: str, user: Optional[Dict[str, Any]] = None) -> None:
        kid = str((user or {}).get('key_id') or '')
        with self._lock:
            for k in [k for k in self._cache if k[0] == net and k[1] == host and (not kid or k[2] == kid)]:
                self._cache.pop(k, None)

    # host
    @staticmethod
    def _key(token: str) -> str:
        return 'tok:' + hashlib.sha256(token.encode('utf-8')).hexdigest()

    def serve_token(self, st, data: Dict[str, Any], v) -> Dict[str, Any]:
        """``POST /sajhanet/v1/token`` at the host (protocol §15.9)."""
        a = self.authz
        if data.get('audience') != st.me:
            raise NetError('assertion_invalid', f'the token exchange is for {data.get("audience")}, not {st.me}')
        verified = verify_assertion(a, st.net, data['subject_token'], v.sender, audience=st.me, hop=1)
        mapped = a.finish(st, verified)                       # refuse now: blocked, no account
        token = secrets.token_urlsafe(32)
        ttl = int(max(1, min(3600, st.settings.token_ttl_seconds)))
        st.node.kv.set(self._key(token), {'net': st.net, 'home': v.sender, 'verified': verified,
                                          'issued_at': crypto.rfc3339(st.now())}, ttl=ttl)
        from sajha.net.integration.authz import linked_audit
        linked_audit('net.token_issued', {'net': st.net, 'peer': v.sender, 'user': verified['name'],
                                          'key_id': verified['key_id'], 'mapping': mapped.get('mapping'),
                                          'expires_in': ttl, 'outcome': 'issued'})
        return {'access_token': token, 'issued_token_type': ISSUED_TYPE, 'token_type': 'N_A', 'expires_in': ttl}

    def resolve(self, headers, sender, **kw):
        h = _lower(headers)
        token = h.get(TOKEN_HEADER, '')
        if not token:
            return None
        a = self.authz
        net = str(h.get('sajha-net-name', '') or '')
        if a is None or net not in a.nets:
            raise NetError('token_invalid', 'this host keeps no tokens for the net')
        st = a.nets[net]
        held = st.node.kv.get(self._key(str(token)))
        del token
        if not isinstance(held, dict) or held.get('net') != net or held.get('home') != sender:
            raise NetError('token_invalid', 'the token is unknown here, expired, or was issued to another instance')
        v = dict(held['verified'])
        rec = record_of(st, v['home'], v['key_id'])
        why = keydir.check_usable(rec, v['home'], st.now(), st.keys.home_usable if st.keys else None)
        if why is not None:
            raise NetError(why)
        v['identity'] = 'token_exchange'
        return a.finish(st, v)


class NetIdentity(plugins.IdentityResolver):
    """The per-net choice of resolvers (see the module docstring). Not registered: SAJHA builds it."""
    name = 'per_net'

    def __init__(self, authz):
        self._authz = authz
        from sajha.net.integration.authz import ApiKeyIdentity
        self.resolvers: Dict[str, plugins.IdentityResolver] = {
            'api_key': ApiKeyIdentity(authz), 'assertion': AssertionIdentity(authz),
            'token_exchange': TokenExchangeIdentity(authz), 'none': plugins.NoIdentity()}

    def resolver(self, name: str) -> plugins.IdentityResolver:
        r = self.resolvers.get(name)
        if r is None:
            try:
                cls = plugins.plugin_class('identity', name)
                try:
                    r = cls(authz=self._authz)
                except TypeError:
                    r = cls()
            except Exception as e:
                logger.warning(f'SAJHA Net identity resolver {name!r}: {e}; using none')
                r = plugins.NoIdentity()
            self.resolvers[name] = r
        return r

    def listed(self, net: str) -> List[str]:
        st = self._authz.nets.get(net)
        return st.settings.identities() if st is not None else ['api_key']

    # home
    def outbound_headers(self, user):
        target = (user or {}).get('_target') if isinstance(user, dict) else None
        net, host = target or ('', '')
        if isinstance(user, dict) and (user.get('_origin') or user.get('_bridge')):
            return self.resolvers['assertion'].outbound_headers(user)      # §16: re-export and bridges
        mine = self.listed(net)
        choice = mine[0] if mine else 'api_key'
        st = self._authz.nets.get(net)
        m = st.node.member(host) if st is not None and host else None
        theirs = list((((m or {}).get('record') or {}).get('user_identity')) or [])
        if theirs:
            choice = next((i for i in mine if i in theirs), choice)
        if isinstance(user, dict):
            user['_identity'] = choice
        return self.resolver(choice).outbound_headers(user)

    def forget(self, net: str, host: str, user=None) -> None:
        self.resolvers['token_exchange'].forget(net, host, user)

    # host
    def resolve(self, headers, sender, **kw):
        h = _lower(headers)
        net = str(h.get('sajha-net-name', '') or '')
        listed = self.listed(net)
        present = [n for n, hd in (('api_key', API_KEY_HEADER), ('assertion', ASSERTION_HEADER),
                                   ('token_exchange', TOKEN_HEADER)) if h.get(hd)]
        if len(present) > 1:
            raise NetError('ambiguous_credentials', 'a forwarded call carries one user credential')
        a = self._authz
        me = a.nets[net].me if net in a.nets else ''
        if not present:
            custom = [n for n in listed if n not in KNOWN]
            if custom:
                return self.resolver(custom[0]).resolve(headers, sender, **kw)
            return None
        which = present[0]
        relayed = int(kw.get('hop') or 1) > 1 or (kw.get('audience') not in (None, '', me))
        if which == 'assertion' and 'assertion' not in listed and not relayed:
            raise NetError('assertion_invalid', 'this host does not accept the assertion identity in this net')
        if which == 'token_exchange' and 'token_exchange' not in listed:
            raise NetError('token_invalid', 'this host does not accept the token_exchange identity in this net')
        if which == 'api_key' and 'api_key' not in listed:
            raise NetError('key_unknown', 'this host does not accept the api_key identity in this net')
        if which == 'api_key' and kw.get('audience') not in (None, '', me):
            raise NetError('assertion_invalid', 'a call to a re-exported tool carries a user assertion')
        r = self.resolvers[which]
        if which == 'api_key':
            return r.resolve(headers, sender, **{k: v for k, v in kw.items() if k == 'secure'})
        return r.resolve(headers, sender, **kw)
