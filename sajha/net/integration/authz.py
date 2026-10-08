# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA Net identity and authorization inside SAJHA (design §10, §11, §16, §17.4; protocol §11, §12,
§15.3, §15.4).

* :class:`ApiKeyIdentity` (identity resolver ``api_key``). **Home:** ``outbound_headers(user)``
  attaches ``Sajha-Net-Api-Key``: the key the caller presented on this request
  (:mod:`sajha.auth.presented_key`) or, for a caller signed in another way (console session, JWT,
  OAuth, Ask SAJHA, a workflow acting for the user), the user's default key decrypted from the
  vault. **Host:** ``resolve(headers, sender)`` hashes the key, finds its record in the net key
  directory of the request's net, refuses it unless it is enabled, unexpired, unrevoked, from a
  home still in the net and sent by that home (``key_unknown`` ... ``key_not_from_home``), checks
  the block on the remote user (``user``), maps the user to a local identity (explicit link, then
  the same ``users.user_id``, then ``sajhanet.users.unknown``: ``refuse`` or ``map_roles``;
  remote administrators per ``sajhanet.users.remote_admin``) and returns the net user. The raw key
  is dropped as soon as it is hashed: never logged, stored, traced or audited.
* :class:`NetRules` (rule evaluator ``policy_engine``): export and import rules (``export`` and
  ``import`` in each net entry), the blocks of design §11.4 (``block_peer``, ``block_user``,
  ``block_tool``), service calls (``service_call``, off) and the key's tool access as a ceiling on
  exports. The host's own access rules and policy engine (source ``sajhanet``) run when the tool
  is executed.
* :class:`NetAuthz`, one per :class:`~sajha.net.integration.SajhaNetService`: per net, the key
  directory (the ``database`` store, :mod:`sajha.net.integration.keystore`) and the block
  publication of the core, the blocks, user links, role maps and name-matching exceptions kept in
  the storage backend (``<data_dir>/<net>/blocks.json`` and ``users.json``), the operations of the
  admin API (local administrators only, never through a remote call), notices and the linked audit
  event of every cross-instance call.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sajha.net import blocks as nblocks
from sajha.net import crypto, keydir, names, plugins
from sajha.net.errors import NetError

logger = logging.getLogger(__name__)

API_KEY_HEADER = 'sajha-net-api-key'
ASSERTION_HEADER = 'sajha-net-user-assertion'
UNKNOWN_MODES = ('refuse', 'map_roles')
REMOTE_ADMIN_MODES = ('admin', 'user', 'refuse')
SEEN_TTL = 30 * 86400
CACHE_SECONDS = 1.0


# ── settings (design §19) ───────────────────────────────────────────

@dataclass
class UserSettings:
    match_by_name: bool = True
    unknown: str = 'refuse'                    # refuse | map_roles
    remote_admin: str = 'admin'                # admin | user | refuse
    exclude_names: List[str] = field(default_factory=list)          # never matched by name
    no_name_match: List[str] = field(default_factory=list)          # instances whose users are never name-matched


@dataclass
class NetAuthSettings:
    users: UserSettings = field(default_factory=UserSettings)
    export: List[Dict[str, Any]] = field(default_factory=list)
    import_: List[Dict[str, Any]] = field(default_factory=list)
    role_maps: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    service_calls: bool = False
    anonymous_may_call_remote: bool = False
    user_identity: str = 'api_key'           # one resolver, or several (comma list): the first is sent
    key_sync: bool = True
    key_full_sync_interval: float = 300.0
    assertion_ttl_seconds: float = 30.0       # lifetime of a user assertion (at most 60, protocol §15.5)
    token_ttl_seconds: float = 300.0          # lifetime of a token issued by token_exchange (at most 3600)

    def identities(self) -> List[str]:
        """The resolvers of this net: the first is what this server sends as a home, all are accepted."""
        return _list(self.user_identity) or ['api_key']


def _list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(',') if x.strip()]
    return [str(x) for x in v]


def _role_maps(v: Any) -> Dict[str, Dict[str, List[str]]]:
    out: Dict[str, Dict[str, List[str]]] = {}
    if not isinstance(v, dict):
        return out
    for inst, m in v.items():
        if isinstance(m, dict):
            out[str(inst)] = {str(r): _list(local) for r, local in m.items()}
    return out


def settings_for(net: str, entry: Optional[Dict[str, Any]] = None) -> NetAuthSettings:
    """The identity and authorization settings of one net: its entry of ``sajhanet.nets`` over the
    shared ``sajhanet.*`` defaults."""
    from sajha.net.integration.config import _bool, _g, _num, _raw
    if entry is None:
        try:
            from sajha.core.net_extension import configured_nets
            entry = next((e for e in configured_nets() if str(e.get('name') or 'default') == net), {})
        except Exception:
            entry = {}
    raw = _raw()
    shared_users = raw.get('users') if isinstance(raw.get('users'), dict) else {}
    eu = entry.get('users') if isinstance(entry.get('users'), dict) else {}
    u = UserSettings(
        match_by_name=_bool(eu.get('match_by_name', _g('users.match_by_name', 'true')), True),
        unknown=str(eu.get('unknown') or _g('users.unknown', 'refuse')).lower(),
        remote_admin=str(eu.get('remote_admin') or _g('users.remote_admin', 'admin')).lower(),
        exclude_names=_list(eu.get('exclude_names', shared_users.get('exclude_names'))),
        no_name_match=_list(eu.get('no_name_match', shared_users.get('no_name_match'))))
    if u.unknown not in UNKNOWN_MODES:
        logger.warning(f'sajhanet.users.unknown: {u.unknown!r} is not one of {UNKNOWN_MODES}; using refuse')
        u.unknown = 'refuse'
    if u.remote_admin not in REMOTE_ADMIN_MODES:
        logger.warning(f'sajhanet.users.remote_admin: {u.remote_admin!r} is not one of {REMOTE_ADMIN_MODES}; '
                       f'using admin')
        u.remote_admin = 'admin'
    kd = raw.get('key_directory') if isinstance(raw.get('key_directory'), dict) else {}
    maps = _role_maps(raw.get('role_maps'))
    maps.update(_role_maps(entry.get('role_maps')))
    return NetAuthSettings(
        users=u,
        export=[r for r in (entry.get('export') or []) if isinstance(r, dict)],
        import_=[r for r in (entry.get('import') or []) if isinstance(r, dict)],
        role_maps=maps,
        service_calls=_bool(entry.get('service_calls', _g('service_calls', 'false')), False),
        anonymous_may_call_remote=_bool(entry.get('anonymous_may_call_remote',
                                                  _g('anonymous_may_call_remote', 'false')), False),
        user_identity=','.join(_list(entry.get('user_identity') or _g('user_identity', 'api_key'))) or 'api_key',
        assertion_ttl_seconds=max(1.0, min(60.0, _num(_g('assertion.ttl_seconds', 30), 30))),
        token_ttl_seconds=max(1.0, min(3600.0, _num(_g('token_exchange.ttl_seconds', 300), 300))),
        key_sync=_bool(_g('key_directory.sync', kd.get('sync', 'true')), True),
        key_full_sync_interval=max(5.0, _num(_g('key_directory.full_sync_interval_seconds',
                                                 kd.get('full_sync_interval_seconds', 300)), 300)))


# ── matching helpers ────────────────────────────────────────────────

def _any(name: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatchcase(name or '', str(p)) for p in patterns or [])


def _roles_ok(roles: Optional[List[str]], wanted: Any) -> bool:
    w = _list(wanted)
    if not w or roles is None:          # no role condition, or catalog time (no user yet)
        return True
    return '*' in w or bool(set(w) & set(roles or []))


def export_decision(rules: List[Dict[str, Any]], peer: str, tool: str, roles: Optional[List[str]],
                    also: Optional[List[str]] = None) -> plugins.Decision:
    """Design §11.2: nothing is exported unless a rule allows it; a rule with an empty
    ``to_instances`` never exports its tools, whatever other rules say. A rule names the tool by its
    published or its local name (``also``: the tool's other names, protocol §5.5)."""
    allow = None
    every = [tool] + [n for n in also or [] if n and n != tool]
    for r in rules or []:
        if not any(_any(n, _list(r.get('tools'))) for n in every):
            continue
        to = r.get('to_instances')
        if to is not None and not _list(to):
            return plugins.Decision(False, 'export')
        if _any(peer, _list(to) or ['*']) and _roles_ok(roles, r.get('for_roles')):
            allow = allow or r
    if allow is None:
        return plugins.Decision(False, 'export')
    return plugins.Decision(True, 'approval_required' if allow.get('require_approval') else 'export')


def import_decision(rules: List[Dict[str, Any]], host: str, tool: str, roles: Optional[List[str]]) -> plugins.Decision:
    for r in rules or []:
        if not _any(tool, _list(r.get('tools'))):
            continue
        inst = r.get('instances')
        if inst is not None and not _list(inst):
            return plugins.Decision(False, 'import')
    for r in rules or []:
        if _any(tool, _list(r.get('tools'))) and _any(host, _list(r.get('instances')) or ['*']) \
                and _roles_ok(roles, r.get('for_roles')):
            return plugins.Decision(True, 'import')
    return plugins.Decision(False, 'import')


def key_allows(user: Optional[Dict[str, Any]], net: str, host: str, tool: str) -> bool:
    """The key's tool access is a ceiling (protocol §11.1): its patterns name tools as the home knows
    them, so a host tool is checked under its qualified name ``<net>__<host prefix>__<part>``."""
    if not user or (user.get('tool_access_mode') or 'all') == 'all':
        return True
    try:
        from sajha.auth.access import apikey_policy
        q = names.qualified_name(net, host, tool)
        return apikey_policy(user.get('tool_access_mode'), list(user.get('tool_access_list') or [])).can_execute(q)
    except Exception:
        return False


# ── the identity resolver ───────────────────────────────────────────

def peer_key_for(net: str, host: str) -> str:
    """The API key this server is configured to use toward ``host`` in ``net``
    (``sajhanet.peer_keys``: ``{"<net>/<instance>": key}`` or ``{"<instance>": key}``; values may be
    ``${ENV_NAME}`` references). Local configuration only; never published. '' when none."""
    from sajha.core.config import _get
    keys = _get('sajhanet.peer_keys', {}) or {}
    if isinstance(keys, str):                          # SAJHA_SAJHANET_PEER_KEYS as JSON
        import json
        try:
            keys = json.loads(keys)
        except ValueError:
            return ''
    if not isinstance(keys, dict):
        return ''
    v = keys.get(f'{net}/{host}') or keys.get(host) or ''
    v = str(v or '').strip()
    if v.startswith('${') and v.endswith('}'):
        import os
        name, _, default = v[2:-1].partition(':')
        v = os.environ.get(name, default)
    return v


@plugins.register('identity')
class ApiKeyIdentity(plugins.IdentityResolver):
    """``api_key``: the user's API key is their net identity (design §10.2, protocol §15.3)."""
    name = 'api_key'

    def __init__(self, authz: Optional['NetAuthz'] = None):
        self._authz = authz

    @property
    def authz(self) -> Optional['NetAuthz']:
        if self._authz is not None:
            return self._authz
        try:
            from sajha.net.integration import get_service
            svc = get_service()
            return getattr(svc, 'authz', None) if svc is not None else None
        except Exception:
            return None

    # home
    def outbound_headers(self, user):
        a = self.authz
        if a is None:
            return {}
        if not user or not user.get('authenticated', True) or str(user.get('user_id') or 'anonymous') == 'anonymous':
            if a.anonymous_may_call_remote(str((user or {}).get('net') or '')):
                return {}
            raise NetError('anonymous', 'the call needs a signed-in user')
        raw, key_id = a.key_for(user)
        if not raw:
            raise NetError('key_disabled', 'no usable API key of this user can travel to the host')
        if isinstance(user, dict):
            user['key_id'] = key_id                      # for the home's audit record (never the key)
        return {'Sajha-Net-Api-Key': raw}

    # host
    def resolve(self, headers, sender, **kw):
        h = {str(k).lower(): v for k, v in (headers or {}).items()}
        raw = h.get(API_KEY_HEADER, '')
        net = str(h.get('sajha-net-name', '') or '')
        a = self.authz
        if not raw:
            if h.get(ASSERTION_HEADER):
                raise NetError('assertion_invalid', 'this host accepts the api_key identity only')
            return None
        if a is None or net not in a.nets:
            raise NetError('key_unknown', 'this host keeps no key directory for the net')
        if 'authorization' in h or 'x-api-key' in h:
            raise NetError('ambiguous_credentials', 'a net request carries no other credentials')
        if kw.get('secure') is False and a.require_https(net):
            raise NetError('https_required', 'a forwarded key is accepted only over HTTPS')
        kh = keydir.key_hash(str(raw))
        del raw
        # the test admin key: accepted only when this host's own keys file has it and the switch is on
        from sajha.auth.persistent_keys import test_admin_key, record_hash
        t = test_admin_key()
        if t is not None and record_hash(t) == kh:
            st = a._state(net)
            verified = {'name': names.net_user(str(t.get('owner') or 'testadmin'), sender), 'net': net,
                        'home': sender, 'user_name': str(t.get('owner') or 'testadmin'), 'home_user_id': '',
                        'display_name': 'Test administrator', 'remote_roles': ['admin'],
                        'key_id': str(t.get('id') or 'test-admin'), 'key_prefix': 'sja_test',
                        'tool_access_mode': 'all', 'tool_access_list': [], 'identity': 'test_admin_key',
                        'test_admin_key': True}
            return a.map_user(st, verified)
        return a.resolve_key(net, kh, sender)


# ── the rule evaluator ──────────────────────────────────────────────

@plugins.register('rules')
class NetRules(plugins.RuleEvaluator):
    """``policy_engine``: export and import rules, blocks and key ceilings (design §11)."""
    name = 'policy_engine'

    def __init__(self, authz: Optional['NetAuthz'] = None):
        self._authz = authz

    @property
    def authz(self) -> Optional['NetAuthz']:
        if self._authz is not None:
            return self._authz
        try:
            from sajha.net.integration import get_service
            svc = get_service()
            return getattr(svc, 'authz', None) if svc is not None else None
        except Exception:
            return None

    def decide(self, rule, subject):
        a = self.authz
        s = subject or {}
        net = str(s.get('net') or '')
        if a is None or net not in a.nets:
            return plugins.Decision(False, rule) if rule in ('export', 'import', 'service_call', 'reexport') \
                else plugins.Decision(True, rule)
        return a.decide(net, rule, s)


# ── per net ─────────────────────────────────────────────────────────

class NetState:
    def __init__(self, authz: 'NetAuthz', cfg, node, settings: NetAuthSettings, store):
        self.authz = authz
        self.cfg = cfg
        self.node = node
        self.settings = settings
        self.store = store
        self.net = cfg.name
        self.keys: Optional[keydir.KeyDirectory] = None
        self.pub: Optional[nblocks.BlockPublication] = None
        self._cache: Dict[str, Any] = {}
        self._lock = threading.RLock()

    @property
    def me(self) -> str:
        return self.node.name

    # documents in the storage backend
    def _doc(self, what: str) -> Dict[str, Any]:
        with self._lock:
            hit = self._cache.get(what)
            if hit and time.time() - hit[0] < CACHE_SECONDS:
                return hit[1]
            r, _ = self.authz.svc._doc_io(f'{self.authz.svc.shared.data_dir}/{self.net}/{what}.json')
            doc = r() or {}
            self._cache[what] = (time.time(), doc)
            return doc

    def _save(self, what: str, doc: Dict[str, Any]) -> None:
        with self._lock:
            _, w = self.authz.svc._doc_io(f'{self.authz.svc.shared.data_dir}/{self.net}/{what}.json')
            w(doc)
            self._cache[what] = (time.time(), doc)

    def blocks(self) -> List[Dict[str, Any]]:
        return list(self._doc('blocks').get('items') or [])

    def blocks_version(self) -> int:
        return int(self._doc('blocks').get('version') or 0)

    def users_doc(self) -> Dict[str, Any]:
        return self._doc('users')

    def now(self) -> float:
        return self.node.clock()


@dataclass
class _Seen:
    mapping: str
    local: str


class NetAuthz:
    """Identity and authorization of one SAJHA Net service, every net (see the module docstring)."""

    def __init__(self, svc, db_factory: Optional[Callable[[], Any]] = None, engine=None,
                 persistent: Optional[Callable[[], List[Dict[str, Any]]]] = None,
                 settings: Optional[Dict[str, NetAuthSettings]] = None):
        self.svc = svc
        self._db_factory = db_factory
        self._engine = engine
        self._persistent = persistent
        self._settings = dict(settings or {})
        self.nets: Dict[str, NetState] = {}
        from sajha.net.integration.identity import NetIdentity
        self.identity = NetIdentity(self)            # api_key, assertion, token_exchange per net (design §10.2)
        self.rules = NetRules(self)
        self._store = None

    # ── wiring ──────────────────────────────────────────────────────

    def db(self):
        if self._db_factory is not None:
            return self._db_factory()
        from sajha.db.engine import get_db_session
        return get_db_session()

    def key_store(self):
        if self._store is None:
            from sajha.net.integration.keystore import DatabaseKeyDirectory
            spec = 'database'
            try:
                from sajha.net.integration.config import _g
                spec = str(_g('plugins.key_directory_store', 'database'))
            except Exception:
                pass
            if spec == 'database':
                self._store = DatabaseKeyDirectory(engine=self._engine, sajha_db=self._engine is None)
            else:
                self._store = plugins.create('key_directory_store', spec)
        return self._store

    def attach(self, cfg, node) -> NetState:
        """Install the key directory, block publication and observers on a node before it starts."""
        st = NetState(self, cfg, node, self._settings.get(cfg.name) or settings_for(cfg.name), self.key_store())
        self.nets[cfg.name] = st
        from sajha.net.integration.identity import KNOWN
        ids = [i for i in st.settings.identities() if i in KNOWN]
        cfg.user_identity = ids or ['none']
        if 'token_exchange' in ids:                                   # the host's token endpoint (protocol §15.9)
            if 'token_exchange' not in node.extra_features:
                node.extra_features.append('token_exchange')
            node.handlers['/sajhanet/v1/token'] = (
                lambda data, v, st=st: self.identity.resolvers['token_exchange'].serve_token(st, data, v))
        skip = (lambda peer, st=st: nblocks.blocked_entirely(st.blocks(), st.now(), peer))

        def own(st=st):
            from sajha.net.integration.keystore import own_keys
            return own_keys(self._db_factory, self._persistent)
        st.keys = keydir.KeyDirectory(node, st.store, own, skip=skip,
                                      full_sync_interval=st.settings.key_full_sync_interval,
                                      sync=st.settings.key_sync).install()
        st.pub = nblocks.BlockPublication(node, lambda st=st: (st.blocks_version(), st.blocks()), skip=skip).install()
        node.observers.append(lambda kind, data, st=st: self._observe(st, kind, data))
        if 'residency' not in node.extra_features:
            node.extra_features.append('residency')                 # honours x-sajha-data-class (protocol §5)
        return st

    def detach(self, net: str) -> None:
        self.nets.pop(net, None)

    def _state(self, net: str) -> NetState:
        st = self.nets.get(net)
        if st is None:
            from sajha.net.integration import ServiceError
            raise ServiceError(404, f'net {net!r} is not running on this server')
        return st

    def require_https(self, net: str) -> bool:
        st = self.nets.get(net)
        return bool(st.cfg.require_https) if st else True

    def anonymous_may_call_remote(self, net: str) -> bool:
        st = self.nets.get(net)
        if st is not None:
            return st.settings.anonymous_may_call_remote
        return any(s.settings.anonymous_may_call_remote for s in self.nets.values())

    # ── notices (design §17.4) ─────────────────────────────────────

    def _observe(self, st: NetState, kind: str, data: Dict[str, Any]) -> None:
        from sajha.net.integration import _clear, _notice
        net, member = st.net, data.get('member', '')
        if kind == 'key_sync_failed':
            _notice(f'sajhanet.keysync:{net}:{member}', 'warning', f'Key directory sync failing with {member} in {net}',
                    f'This server could not pull the API key records of {member} in {net} '
                    f'({data.get("failures")} attempts): {data.get("detail", "")}. Keys issued there may be '
                    f'refused here until the next sync succeeds.')
        elif kind == 'key_sync_ok':
            _clear(f'sajhanet.keysync:{net}:{member}')
        elif kind == 'blocked_by_peer':
            nid = f'sajhanet.blocked_by:{net}:{member}'
            bl = data.get('blocks') or []
            if bl:
                what = ', '.join(sorted({b.get('level', '') + (f' {b.get("tool")}' if b.get('tool') else '')
                                         + (f' {b.get("user")}' if b.get('user') else '') for b in bl}))
                reasons = '; '.join(b['reason'] for b in bl if b.get('reason'))
                _notice(nid, 'info', f'{member} blocks this server in {net}',
                        f'{member} has published blocks naming this server in {net}: {what}'
                        f'{(" (" + reasons + ")") if reasons else ""}. Only {member} enforces them.', ttl=0)
            else:
                _clear(nid)

    # ── home: the key that travels ─────────────────────────────────

    def key_for(self, user: Dict[str, Any]):
        """``(raw key, key id)`` for a forwarded call by ``user`` (a dict with ``user_id``): the key
        the caller presented on this request, else the user's default key from the vault."""
        # 1. a key configured on this server for the target member (sajhanet.peer_keys, local only)
        target = user.get('_target') if isinstance(user, dict) else None
        if target:
            pk = peer_key_for(*target)
            if pk:
                user['peer_key'] = True                    # recorded in the home's audit (never the key)
                return pk, 'peer-key:' + target[1]
        # 2. owner decision: while the test admin key is enabled, every SAJHA Net call carries it
        from sajha.auth.persistent_keys import test_admin_key
        t = test_admin_key()
        if t is not None:
            if isinstance(user, dict):
                user['test_admin_key'] = True            # recorded in the home's audit with the original caller
            return str(t['key']), str(t.get('id') or 'test-admin')
        if user.get('api_key'):
            raw = str(user['api_key'])
            return raw, str(user.get('api_key_id') or '')
        uid = str(user.get('user_id') or '')
        from sajha.auth.presented_key import presented
        p = presented()
        if p is not None and p.raw and (not uid or p.user_id == uid):
            return p.raw, p.key_id
        if not uid or uid.startswith('apikey:'):
            return '', ''
        db = self.db()
        try:
            from sajha.auth.apikeys import default_key_of, default_key_secret
            from sajha.db.models import User
            row = db.query(User).filter(User.user_id == uid).first()
            if row is None or not row.enabled:
                return '', ''
            raw = default_key_secret(db, row)
            if not raw:
                return '', ''
            k = default_key_of(db, row)
            return raw, (k.id if k is not None else '')
        finally:
            try:
                db.close()
            except Exception:
                pass

    # ── host: verify and map (protocol §15.3, §15.4 steps 5 to 7) ──

    def resolve_key(self, net: str, kh: str, sender: str) -> Dict[str, Any]:
        st = self._state(net)
        recs = st.store.find(net, kh)
        rec = next((r for r in recs if r.get('home_instance') == sender), recs[0] if recs else None)
        why = keydir.check_usable(rec, sender, st.now(), st.keys.home_usable if st.keys else None)
        if why is not None:
            raise NetError(why)
        owner = rec.get('owner') or {}
        login = str(owner.get('user_name') or '')
        verified = {
            'name': names.net_user(login, rec['home_instance']), 'net': net, 'home': rec['home_instance'],
            'user_name': login, 'home_user_id': str(owner.get('user_id') or ''),
            'display_name': str(owner.get('display_name') or login),
            'remote_roles': [str(r) for r in owner.get('roles') or []],
            'key_id': rec['key_id'], 'key_prefix': rec.get('key_prefix', ''),
            'tool_access_mode': rec.get('tool_access_mode') or 'all',
            'tool_access_list': list(rec.get('tool_access_list') or []), 'identity': 'api_key',
        }
        return self.finish(st, verified)

    def finish(self, st: NetState, verified: Dict[str, Any]) -> Dict[str, Any]:
        """Steps 6 and 7 of protocol §15.4 for a verified net user, whatever resolver verified it."""
        if nblocks.match_user(st.blocks(), st.now(), verified['name']) is not None:       # step 6
            self._seen(st, verified, 'blocked', '')
            raise NetError('user', 'calls on behalf of this user are blocked here')
        return self.map_user(st, verified)

    def map_user(self, st: NetState, v: Dict[str, Any]) -> Dict[str, Any]:
        """Design §11.3: explicit link, then the same user id, then ``unknown`` (refuse or map_roles);
        remote administrators per ``remote_admin``."""
        us = st.settings.users
        doc = st.users_doc()
        home, login = v['home'], v['user_name']
        remote_admin = 'admin' in v['remote_roles']
        if remote_admin and us.remote_admin == 'refuse':
            self._seen(st, v, 'refused', '')
            raise NetError('remote_admin', 'administrators of other instances may not call tools here')
        links = doc.get('links') or {}
        local, how = None, ''
        db = self.db()
        try:
            from sajha.db.models import User
            link = links.get(v['name'])
            if link:
                local = db.query(User).filter(User.user_id == str(link.get('local'))).first()
                how = 'link'
            no_match = set(us.no_name_match) | set(doc.get('no_name_match') or [])
            excluded = set(us.exclude_names) | set(doc.get('exclude_names') or [])
            if (local is None and us.match_by_name and home not in no_match and login not in excluded
                    and not _any(home, list(no_match))):
                local = db.query(User).filter(User.user_id == login).first()
                how = 'name'
            if local is not None and not local.enabled:
                local = None
            out = dict(v)
            if local is not None:
                roles = sorted(local.role_names)
                if remote_admin is False or us.remote_admin == 'user':
                    if how != 'link' and us.remote_admin == 'user' and remote_admin:
                        roles = [r for r in roles if r != 'admin']          # a remote admin gets no admin by name
                out.update(user_id=local.user_id, user_name_local=local.user_name, roles=roles, guest=False,
                           mapping=how)
            elif remote_admin and us.remote_admin == 'admin':
                out.update(user_id=v['name'], user_name_local=v['display_name'], roles=['admin'], guest=True,
                           mapping='admin')
            elif us.unknown == 'map_roles':
                roles = self.mapped_roles(st, home, v['remote_roles'])
                if not roles:
                    self._seen(st, v, 'refused', '')
                    raise NetError('no_account', 'none of your roles is mapped to a role here')
                out.update(user_id=v['name'], user_name_local=v['display_name'], roles=roles, guest=True,
                           mapping='role_map')
            else:
                self._seen(st, v, 'refused', '')
                raise NetError('no_account', f'you have no account on {st.me}')
            if remote_admin and us.remote_admin == 'admin' and 'admin' not in out['roles']:
                out['roles'] = sorted(set(out['roles']) | {'admin'})
            out['is_admin'] = 'admin' in out['roles']
            out['authenticated'] = True
            self._seen(st, v, out['mapping'], out['user_id'])
            return out
        finally:
            try:
                db.close()
            except Exception:
                pass

    def mapped_roles(self, st: NetState, home: str, remote_roles: List[str]) -> List[str]:
        maps: Dict[str, Dict[str, List[str]]] = {}
        for src in (st.settings.role_maps, (st.users_doc().get('role_maps') or {})):
            for inst, m in (src or {}).items():
                maps.setdefault(inst, {}).update({str(k): _list(v) for k, v in (m or {}).items()})
        out = set()
        for inst in (home, '*'):
            for r in remote_roles:
                out.update(maps.get(inst, {}).get(r) or [])
        return sorted(out)

    def _seen(self, st: NetState, v: Dict[str, Any], mapping: str, local: str) -> None:
        try:
            st.node.kv.set(f'seen:{v["name"]}', {'user': v['name'], 'home': v['home'], 'mapping': mapping,
                                                 'identity': v.get('identity') or 'api_key',
                                                 'local': local, 'key_prefix': v.get('key_prefix', ''),
                                                 'at': crypto.rfc3339(st.now())}, ttl=SEEN_TTL)
        except Exception as e:
            logger.debug(f'SAJHA Net: remote user not recorded: {e}')

    def auth_context(self, user: Dict[str, Any], db=None):
        """An :class:`~sajha.auth.AuthContext` to run a forwarded call as ``user`` (a resolved net user)."""
        from sajha.auth import AuthContext
        local = None
        if db is not None and not user.get('guest'):
            from sajha.db.models import User
            local = db.query(User).filter(User.user_id == user['user_id']).first()
        return AuthContext(authenticated=True, user_id=user['user_id'],
                           user_name=user.get('user_name_local') or user['user_id'], roles=list(user['roles']),
                           auth_type='sajhanet', is_admin=bool(user.get('is_admin')), api_key_id=user.get('key_id'),
                           _user=local if local is not None and not user.get('is_admin') else None, _db=db)

    # ── rules (protocol §15.4 steps 3, 6, 8, 9; home: import, outbound blocks) ──

    def decide(self, net: str, rule: str, s: Dict[str, Any]) -> plugins.Decision:
        st = self.nets[net]
        now = st.now()
        peer = str(s.get('peer') or s.get('host') or '')
        bl = st.blocks()
        if rule == 'block_peer':
            direction = str(s.get('direction') or 'inbound')
            b = (nblocks.match_inbound(bl, now, peer) if direction == 'inbound'
                 else nblocks.match_outbound(bl, now, peer) if direction == 'outbound'
                 else next((x for x in nblocks.active(bl, now) if x.get('level') == 'instance'
                            and x.get('target_instance') in (peer, '*')), None))
            return plugins.Decision(b is None, b['level'] if b else 'not_blocked')
        if rule == 'block_user':
            u = s.get('user')
            name = u.get('name') if isinstance(u, dict) else str(u or '')
            b = nblocks.match_user(bl, now, name) if name else None
            return plugins.Decision(b is None, 'user' if b else 'not_blocked')
        if rule == 'block_tool':
            if str(s.get('direction') or 'inbound') == 'outbound':
                b = nblocks.match_outbound(bl, now, peer, str(s.get('qualified_name') or s.get('tool') or ''))
            else:
                b = next((x for x in (nblocks.match_tool(bl, now, peer, n)
                                      for n in [str(s.get('tool') or '')] + list(s.get('tool_names') or []))
                          if x is not None), None)        # under its published or its local name (§5.5)
            return plugins.Decision(b is None, 'tool' if b else 'not_blocked')
        if rule == 'service_call':
            return plugins.Decision(st.settings.service_calls, 'service_call' if st.settings.service_calls
                                    else 'anonymous')
        if rule == 'export':
            if nblocks.match_inbound(bl, now, peer):
                return plugins.Decision(False, 'export')
            tool = str(s.get('tool') or '')
            u = s.get('user') if isinstance(s.get('user'), dict) else None
            d = export_decision(st.settings.export, peer, tool, list(u.get('roles') or []) if u else None,
                                also=[str(n) for n in s.get('tool_names') or []])
            if d.allow and u is not None and not key_allows(u, net, st.me, tool):
                return plugins.Decision(False, 'access')
            return d
        if rule == 'import':
            host = str(s.get('host') or peer)
            b = nblocks.match_outbound(bl, now, host, s.get('qualified_name'))
            if b is not None:
                return plugins.Decision(False, 'import')
            u = s.get('user') if isinstance(s.get('user'), dict) else None
            roles = list(u.get('roles') or []) if u else None
            return import_decision(st.settings.import_, host, str(s.get('tool') or ''), roles)
        if rule == 'reexport':                                   # design §14: re-export rules of this net
            cat = getattr(self.svc, 'catalogs', None)
            if cat is None:
                return plugins.Decision(False, 'export')
            return cat.reexport_decision(net, s)
        if rule in ('residency_offer', 'residency_arguments', 'residency_result'):
            from sajha.net.integration.residency import decide as residency_decide
            return residency_decide(st.node, rule, s, registry=getattr(self.svc, 'tools_registry', None))               # design §12 (data classes, residency rules)
        return plugins.Decision(True, rule)

    # ── administration (local administrators only, design §11.3) ───

    @staticmethod
    def _local_only(by_auth_type: Optional[str]) -> None:
        if by_auth_type == 'sajhanet':
            from sajha.net.integration import ServiceError
            raise ServiceError(403, 'net settings are changed only by an administrator signed in to this server')

    def _bump_blocks(self, st: NetState, items: List[Dict[str, Any]]) -> int:
        version = st.blocks_version() + 1
        st._save('blocks', {'version': version, 'items': items})
        try:
            st.node.refresh_record()
        except Exception as e:
            logger.debug(f'SAJHA Net {st.net}: re-signing after a block change: {e}')
        return version

    def add_block(self, net: str, level: str, target_instance: str, reason: str, by: str = '', *, tool: str = '',
                  user: str = '', direction: str = 'inbound', expires_in_minutes: Any = None,
                  withhold_reason: bool = False, by_auth_type: Optional[str] = None) -> Dict[str, Any]:
        from sajha.net.integration import ServiceError, _audit
        self._local_only(by_auth_type)
        st = self._state(net)
        level = (level or '').strip().lower()
        if level not in nblocks.LEVELS:
            raise ServiceError(400, f'level must be one of {", ".join(nblocks.LEVELS)}')
        reason = (reason or '').strip()
        if not reason:
            raise ServiceError(400, 'give a reason for the block')
        target = (target_instance or '').strip()
        if level == 'user':
            if '@' not in (user or ''):
                raise ServiceError(400, 'a user block names a net user as user@instance')
            target = target or user.rsplit('@', 1)[1]
        if target != '*' and not names.is_instance_name(target):
            raise ServiceError(400, 'target_instance must be an instance name of the net, or *')
        if level == 'instance' and target == st.me or (level in ('inbound', 'outbound') and target == st.me):
            raise ServiceError(400, 'an instance does not block itself')
        if level == 'tool' and not (tool or '').strip():
            raise ServiceError(400, 'a tool block names the tool (a host tool, or a qualified name for outbound)')
        direction = (direction or 'inbound').lower()
        if direction not in ('inbound', 'outbound'):
            raise ServiceError(400, 'direction is inbound or outbound')
        now = st.now()
        b: Dict[str, Any] = {'id': secrets.token_hex(8), 'level': level, 'target_instance': target,
                             'reason': reason[:500], 'set_at': crypto.rfc3339(now), 'set_by': by or 'admin'}
        if level == 'tool':
            b.update(tool=tool.strip(), direction=direction)
        if level == 'user':
            b['user'] = user.strip()
        if expires_in_minutes not in (None, '', 0, '0'):
            try:
                mins = float(expires_in_minutes)
            except (TypeError, ValueError):
                raise ServiceError(400, 'expires_in_minutes must be a number')
            if mins <= 0:
                raise ServiceError(400, 'expires_in_minutes must be positive')
            b['expires_at'] = crypto.rfc3339(now + mins * 60)
        if withhold_reason:
            b['withhold_reason'] = True
        items = [x for x in st.blocks() if nblocks.is_active(x, now)] + [b]
        version = self._bump_blocks(st, items)
        _audit('block_added', by, {'net': net, **{k: v for k, v in b.items() if k != 'set_by'}, 'version': version})
        return dict(b, version=version, effect=self.effect_of(st, b))

    def remove_block(self, net: str, block_id: str, by: str = '', reason: str = '',
                     by_auth_type: Optional[str] = None) -> bool:
        from sajha.net.integration import _audit
        self._local_only(by_auth_type)
        st = self._state(net)
        items = st.blocks()
        keep = [x for x in items if x.get('id') != block_id]
        if len(keep) == len(items):
            return False
        version = self._bump_blocks(st, keep)
        _audit('block_removed', by, {'net': net, 'id': block_id, 'reason': reason, 'version': version})
        return True

    def effect_of(self, st: NetState, b: Dict[str, Any]) -> str:
        t = b.get('target_instance')
        who = 'every instance' if t == '*' else t
        lv = b.get('level')
        if lv == 'instance':
            return f'No calls to or from {who} in {st.net}; its tools disappear here and its updates are ignored.'
        if lv == 'inbound':
            return f'Calls from {who} are refused here; this server still calls its tools.'
        if lv == 'outbound':
            return f'This server stops calling {who}; its tools are hidden from local users.'
        if lv == 'tool':
            if b.get('direction') == 'outbound':
                return f'The remote tool {b.get("tool")} is hidden from local users.'
            return f'Calls from {who} to the tool {b.get("tool")} are refused here.'
        return f'Calls on behalf of {b.get("user")} are refused here, whatever their mapping.'

    def blocks_view(self, net: str) -> Dict[str, Any]:
        st = self._state(net)
        now = st.now()
        mine = [dict(b, active=nblocks.is_active(b, now)) for b in st.blocks()]
        theirs = {}
        if st.pub is not None:
            for peer, doc in st.pub.peer_documents().items():
                theirs[peer] = [b for b in nblocks.active(doc.get('blocks') or [], now)]
        return {'net': net, 'instance': st.me, 'version': st.blocks_version(), 'blocks': mine, 'published': theirs}

    def _users_change(self, st: NetState, fn: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
        doc = json.loads(json.dumps(st.users_doc() or {}))
        fn(doc)
        st._save('users', doc)
        return doc

    def link_user(self, net: str, remote_user: str, local_user: str, by: str = '',
                  by_auth_type: Optional[str] = None) -> Dict[str, Any]:
        from sajha.net.integration import ServiceError, _audit
        self._local_only(by_auth_type)
        st = self._state(net)
        remote_user = (remote_user or '').strip()
        if '@' not in remote_user or not names.is_instance_name(remote_user.rsplit('@', 1)[1]):
            raise ServiceError(400, 'name the remote user as user@instance')
        db = self.db()
        try:
            from sajha.db.models import User
            if db.query(User).filter(User.user_id == (local_user or '').strip()).first() is None:
                raise ServiceError(404, f'no local account {local_user!r}')
        finally:
            db.close()
        self._users_change(st, lambda d: d.setdefault('links', {}).__setitem__(
            remote_user, {'local': local_user.strip(), 'by': by, 'at': crypto.rfc3339(st.now())}))
        _audit('user_linked', by, {'net': net, 'remote_user': remote_user, 'local_user': local_user})
        return {'net': net, 'remote_user': remote_user, 'local_user': local_user.strip()}

    def unlink_user(self, net: str, remote_user: str, by: str = '', by_auth_type: Optional[str] = None) -> bool:
        from sajha.net.integration import _audit
        self._local_only(by_auth_type)
        st = self._state(net)
        if remote_user not in (st.users_doc().get('links') or {}):
            return False
        self._users_change(st, lambda d: (d.get('links') or {}).pop(remote_user, None))
        _audit('user_unlinked', by, {'net': net, 'remote_user': remote_user})
        return True

    def set_role_map(self, net: str, instance: str, mapping: Dict[str, Any], by: str = '',
                     by_auth_type: Optional[str] = None) -> Dict[str, Any]:
        from sajha.net.integration import ServiceError, _audit
        self._local_only(by_auth_type)
        st = self._state(net)
        if instance != '*' and not names.is_instance_name(instance):
            raise ServiceError(400, 'instance must be an instance name of the net, or *')
        if not isinstance(mapping, dict):
            raise ServiceError(400, 'the role map is an object: remote role -> local role(s)')
        clean = {str(k): _list(v) for k, v in mapping.items() if str(k).strip()}

        def fn(d):
            maps = d.setdefault('role_maps', {})
            if clean:
                maps[instance] = clean
            else:
                maps.pop(instance, None)
        self._users_change(st, fn)
        _audit('role_map_set', by, {'net': net, 'instance': instance, 'map': clean})
        return {'net': net, 'instance': instance, 'map': clean}

    def set_name_matching(self, net: str, instance: str, on: bool, by: str = '',
                          by_auth_type: Optional[str] = None) -> Dict[str, Any]:
        from sajha.net.integration import ServiceError, _audit
        self._local_only(by_auth_type)
        st = self._state(net)
        if not names.is_instance_name(instance):
            raise ServiceError(400, 'instance must be an instance name of the net')

        def fn(d):
            off = set(d.get('no_name_match') or [])
            (off.discard if on else off.add)(instance)
            d['no_name_match'] = sorted(off)
        doc = self._users_change(st, fn)
        _audit('name_matching_set', by, {'net': net, 'instance': instance, 'on': bool(on)})
        return {'net': net, 'no_name_match': doc.get('no_name_match') or []}

    def users_view(self, net: str) -> Dict[str, Any]:
        st = self._state(net)
        doc = st.users_doc()
        seen = sorted((v for _k, v in st.node.kv.scan('seen:')), key=lambda v: v.get('user', ''))
        u = st.settings.users
        return {'net': net, 'links': doc.get('links') or {}, 'role_maps': self._merged_maps(st),
                'no_name_match': sorted(set(u.no_name_match) | set(doc.get('no_name_match') or [])),
                'exclude_names': u.exclude_names, 'match_by_name': u.match_by_name, 'unknown': u.unknown,
                'remote_admin': u.remote_admin, 'seen': seen}

    def _merged_maps(self, st: NetState) -> Dict[str, Dict[str, List[str]]]:
        out = {k: dict(v) for k, v in st.settings.role_maps.items()}
        for k, v in (st.users_doc().get('role_maps') or {}).items():
            out.setdefault(k, {}).update(v)
        return out

    def keys_view(self, net: str, home: Optional[str] = None) -> Dict[str, Any]:
        st = self._state(net)
        out: Dict[str, Any] = {'net': net, 'instance': st.me}
        store = st.store
        if hasattr(store, 'summary'):
            out['homes'] = store.summary(net)
        if home and hasattr(store, 'records'):
            out['records'] = store.records(net, home)
        return out

    def resync(self, net: str, by: str = '') -> Dict[str, Any]:
        from sajha.net.integration import _audit
        st = self._state(net)
        for m in st.node.members():
            st.node.kv.set(f'kd:repull:{m["name"]}', True)
        if st.keys is not None:
            st.keys._last_full = 0.0
        _audit('key_directory_resync', by, {'net': net})
        return {'net': net, 'resync': 'scheduled for the next gossip round'}

    def status(self, net: str) -> Dict[str, Any]:
        st = self.nets.get(net)
        if st is None:
            return {}
        now = st.now()
        return {'user_identity': st.settings.user_identity, 'key_directory_version': st.keys.own_version()
                if st.keys else 0, 'blocks_version': st.blocks_version(),
                'blocks_active': len(nblocks.active(st.blocks(), now)), 'users': {
                    'match_by_name': st.settings.users.match_by_name, 'unknown': st.settings.users.unknown,
                    'remote_admin': st.settings.users.remote_admin}}


# ── linked audit (design §16) ───────────────────────────────────────

_SECRET_FIELDS = ('api_key', 'raw', 'key', 'sajha-net-api-key', 'Sajha-Net-Api-Key')


def linked_audit(event: str, details: Dict[str, Any], actor: Optional[str] = None) -> None:
    """One record of a cross-instance call in this instance's tamper-evident audit chain: the
    home's (``net.call``) and the host's (``net.host_call``, ``net.host_refused``) share the trace id
    and the key id, so the call can be reconstructed by joining them. Never the key itself."""
    d = {k: v for k, v in (details or {}).items() if k not in _SECRET_FIELDS}
    try:
        from sajha import audit
        audit.record(event, actor={'user': actor or str(d.get('user') or d.get('peer') or 'system')},
                     resource={'type': 'sajhanet', 'name': str(d.get('tool') or d.get('name') or '')},
                     outcome=str(d.get('outcome') or ''), details=d, defer=True)
    except Exception as e:
        logger.debug(f'SAJHA Net audit {event}: {e}')


def get_authz(svc) -> NetAuthz:
    a = getattr(svc, 'authz', None)
    if a is None:
        a = NetAuthz(svc, db_factory=getattr(svc, 'db_factory', None), engine=getattr(svc, 'db_engine', None),
                     persistent=getattr(svc, 'persistent_keys', None))
        svc.authz = a
    return a


# the assertion and token_exchange resolvers register next to api_key
from sajha.net.integration import identity as _identity  # noqa: E402,F401
