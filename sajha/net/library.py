"""
The SAJHA Net reference library (design §5.1, §5.4): a complete participant assembled from the
protocol core alone, for any MCP server that wants to join a net without SAJHA.

:class:`NetParticipant` holds one participant's node in one net (identity, SWIM gossip, the
revocation list), its catalog (served with net metadata and digests), its signed MCP host endpoint
(protocol §15.4 in order) and, when key verification is on, the net key directory it verifies
forwarded API keys against. What it offers and how a call runs are given to it: a
:class:`~sajha.net.plugins.CatalogSource` and an ``execute(ctx, arguments)`` function. The SAJHA Net
agent (``sajhanet_agent/``) is this library in front of an MCP server reached over stdio or HTTP.

Like the rest of the core it imports nothing from SAJHA outside ``sajha.net``
(``tests/test_sajhanet_agent_boundary.py``).

* :func:`self_signed` and :class:`IdentityFiles`: a self-signed identity for ``admission: open`` (or
  manual mode, where peers pin its thumbprint), kept in a directory of its own.
* :func:`enroll`: a certificate from the net's CA participant with an enrollment token (§14.1).
* :class:`ExportPolicy`: the small export policy of an agent: which tools, to which peers and roles,
  whether calls without a user are served; it imports nothing.
* :class:`KeyDirectoryIdentity`: the ``api_key`` resolver of a participant without accounts of its
  own: the key is checked against the net key directory (§15.3); the user is the key's owner at
  their home, with their roles there and the key's tool access as a ceiling.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from sajha.net import ENDPOINT, EXTENSION_ID, SUPPORTED_VERSIONS, crypto, httpsig, names, schemas
from sajha.net.catalog import CatalogBook
from sajha.net.errors import NetError
from sajha.net.keydir import KeyDirectory, check_usable, key_hash
from sajha.net.membership import PeerCache
from sajha.net.models import GossipSettings, KV, MemoryKV, NetConfig, PeerCacheSettings
from sajha.net.node import Participant, NetNode, empty_404
from sajha.net.plugins import (CatalogSource, Decision, IdentityResolver, MemoryKeyDirectory, NoIdentity,
                               PeerConnector, PeerResponse, PeerUnreachable, RuleEvaluator, create)
from sajha.net.routing import CallContext, HostRefusal, HostServer
from sajha.net.trust import CATrust, FirstUseTrust, PinnedTrust

logger = logging.getLogger(__name__)

API_KEY_HEADER = 'sajha-net-api-key'
MCP_ERAS = ['2026-07-28', '2025-11-25']

__all__ = ['NetParticipant', 'IdentityFiles', 'ExportPolicy', 'KeyDirectoryIdentity', 'StaticTools', 'enroll',
           'self_signed', 'CallContext', 'HostRefusal', 'EnrollmentError']


# ── identity ───────────────────────────────────────────────────────

class EnrollmentError(Exception):
    pass


def _write(path: str, data: bytes, private: bool) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.sajhanet-')
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
    os.chmod(tmp, 0o600 if private else 0o644)
    os.replace(tmp, path)


class IdentityFiles:
    """One participant's key, certificate, CA certificate and first-use keys in a directory
    (``instance.key`` is private; nothing here leaves the machine except the certificate)."""

    def __init__(self, directory: str):
        self.dir = directory
        self.key_path = os.path.join(directory, 'instance.key')
        self.cert_path = os.path.join(directory, 'instance.crt')
        self.ca_path = os.path.join(directory, 'ca.pem')
        self.first_use_path = os.path.join(directory, 'first_use.json')
        self.peers_path = os.path.join(directory, 'peers.json')

    def _read(self, path: str) -> Optional[bytes]:
        try:
            with open(path, 'rb') as f:
                return f.read()
        except OSError:
            return None

    def load(self) -> Optional[Tuple[Any, Any]]:
        kb, cb = self._read(self.key_path), self._read(self.cert_path)
        if not kb or not cb:
            return None
        return crypto.key_from_pem(kb), crypto.load_cert(cb)

    def ca_certificate(self):
        raw = self._read(self.ca_path)
        return crypto.load_cert(raw) if raw else None

    def save(self, key, cert, ca_cert=None) -> None:
        _write(self.key_path, crypto.key_to_pem(key), private=True)
        _write(self.cert_path, crypto.cert_pem(cert), private=False)
        if ca_cert is not None:
            _write(self.ca_path, crypto.cert_pem(ca_cert), private=False)

    # admission: open — instance name -> the key thumbprint first seen for it
    def known(self) -> Dict[str, str]:
        raw = self._read(self.first_use_path)
        try:
            return dict(json.loads(raw.decode('utf-8'))) if raw else {}
        except ValueError:
            return {}

    def remember(self, name: str, thumbprint: str) -> None:
        cur = self.known()
        cur[name] = thumbprint
        _write(self.first_use_path, json.dumps(cur, indent=1, sort_keys=True).encode(), private=False)

    def forget(self, name: str) -> bool:
        cur = self.known()
        if cur.pop(name, None) is None:
            return False
        _write(self.first_use_path, json.dumps(cur, indent=1, sort_keys=True).encode(), private=False)
        return True


def self_signed(net: str, instance: str, host: str, alg: str = crypto.ED25519, now: Optional[float] = None):
    """A new key and a self-signed certificate ``O=<net>, CN=<instance>`` naming ``host`` (§8.11)."""
    key = crypto.generate_key(alg)
    return key, crypto.self_signed_certificate(key, net, instance, host, now=now)


def _spki(key) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def enroll(connector: PeerConnector, net: str, instance: str, host: str, ca_url: str, token: str, *,
           require_https: bool = True, alg: str = crypto.ED25519, ca_certificate=None,
           clock: Callable[[], float] = time.time, max_age: float = 30) -> Tuple[Any, Any, Any]:
    """Enroll at the CA participant (§14.1): a new key, a CSR and the token; returns ``(key,
    certificate, CA certificate)`` after checking the CA's signed answer. ``ca_certificate``, when
    given, must be the CA certificate the answer carries (a pinned CA)."""
    url = ca_url.rstrip('/') + ENDPOINT + 'ca/enroll'
    if require_https and not url.startswith('https://'):
        raise EnrollmentError('enrollment is only over HTTPS (require_https)')
    key = crypto.generate_key(alg)
    body = json.dumps({'net': net, 'instance': instance, 'token': token,
                       'csr': crypto.b64(crypto.make_csr(key, net, instance, host))}).encode()
    try:
        r = connector.send('POST', url, {'content-type': 'application/json', 'sajha-net-version': '1',
                                         'sajha-net-name': net}, body, 30)
    except PeerUnreachable as e:
        raise EnrollmentError(f'the CA is unreachable: {e}')
    try:
        data = json.loads(r.body.decode('utf-8')) if r.body else {}
    except ValueError:
        data = {}
    if r.status != 200:
        raise EnrollmentError(f'the CA refused: {data.get("reason") or r.status}')
    if schemas.errors('enroll_response', data):
        raise EnrollmentError('the CA answer fails its schema')
    ca_cert = crypto.load_cert(crypto.unb64(data['ca_certificate']))
    if ca_certificate is not None and crypto.cert_der(ca_certificate) != crypto.cert_der(ca_cert):
        raise EnrollmentError('the CA certificate in the answer differs from the pinned one')
    try:
        httpsig.verify_response(CATrust(net, ca_cert, lambda: None), instance, httpsig.ANY, r.status, r.headers,
                                r.body, None, now=clock(), max_age=max_age)
    except Exception as e:
        raise EnrollmentError(f'the CA answer does not verify: {getattr(e, "reason", e)}')
    cert = crypto.chain_from_b64(data['certificate'])[0]
    if _spki(cert.public_key()) != _spki(key.public_key()) or crypto.subject_of(cert) != (net, instance):
        raise EnrollmentError('the issued certificate is not for this key and name')
    return key, cert, ca_cert


# ── catalog, rules, identity ───────────────────────────────────────

class StaticTools(CatalogSource):
    """A fixed list of MCP Tool objects (or a callable returning one)."""
    name = 'static_tools'

    def __init__(self, tools: Any = None):
        self._tools = tools if tools is not None else []

    def tools(self, net, peer=None):
        items = self._tools() if callable(self._tools) else self._tools
        return [dict(t) for t in items or []]


def _match(value: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(value or '', p) for p in patterns or [])


def key_ceiling(user: Optional[Dict[str, Any]], net: str, host: str, tool: str) -> bool:
    """The key's tool access is a ceiling (protocol §11.1); its patterns name the tool as the home
    knows it (the qualified name) or by its plain name."""
    if not user:
        return True
    mode = str(user.get('tool_access_mode') or 'all').lower()
    pats = [str(p) for p in user.get('tool_access_list') or [] if str(p).strip()]
    names_ = [names.qualified_name(net, host, tool), tool]
    if mode == 'all':
        return True
    if mode == 'allowlist':
        return any(_match(n, pats) for n in names_)
    if mode == 'denylist':
        return not any(_match(n, pats) for n in names_)
    if mode == 'regex':
        rx = [p[3:] if p.startswith('re:') else p for p in pats]
        return any(re.search(r, n) for r in rx for n in names_)
    return False


class ExportPolicy(RuleEvaluator):
    """An agent's export policy: tools (globs) to peers (globs) and, for calls with a user, roles at
    the user's home (None: any role); the key's tool access is a ceiling. It imports and pulls
    nothing. ``service_calls``: calls that carry no user are served (a service identity)."""
    name = 'export_policy'

    def __init__(self, tools: Optional[List[str]] = None, peers: Optional[List[str]] = None,
                 roles: Optional[List[str]] = None, service_calls: bool = False, host: str = ''):
        self.tools = list(tools or ['*'])
        self.peers = list(peers or ['*'])
        self.roles = list(roles) if roles else None
        self.service_calls = bool(service_calls)
        self.host = host
        self.version = 1

    def decide(self, rule, subject):
        s = subject or {}
        if rule == 'export':
            tool = str(s.get('tool') or '')
            peer = s.get('peer')
            if not _match(tool, self.tools):
                return Decision(False, 'export')
            if peer is not None and not _match(str(peer), self.peers):
                return Decision(False, 'export')
            user = s.get('user')
            if user:
                if self.roles is not None and not set(self.roles) & set(user.get('remote_roles') or []):
                    return Decision(False, 'export')
                if not key_ceiling(user, str(s.get('net') or ''), self.host, tool):
                    return Decision(False, 'export')
            return Decision(True, 'export')
        if rule == 'service_call':
            return Decision(self.service_calls, rule)
        if rule in ('import', 'pull', 'reexport'):
            return Decision(False, rule)
        return Decision(True, rule)


class KeyDirectoryIdentity(IdentityResolver):
    """``api_key`` at a host with no accounts of its own: the forwarded key is checked against the
    net key directory (§15.3, §15.4 step 5); the user is the key's owner at their home."""
    name = 'api_key'

    def __init__(self, participant: 'NetParticipant'):
        self.p = participant

    def outbound_headers(self, user):
        return {}                                    # a participant of this kind never sends calls

    def resolve(self, headers, sender, **kw):
        h = httpsig.lower_headers(headers or {})
        raw = h.get(API_KEY_HEADER, '')
        if not raw:
            if h.get('sajha-net-user-assertion') or h.get('sajha-net-user-token'):
                raise NetError('assertion_invalid', 'this host accepts the api_key identity only')
            return None
        if kw.get('secure') is False and self.p.node.cfg.require_https:
            raise NetError('https_required', 'a forwarded key is accepted only over HTTPS')
        kd = self.p.keys
        if kd is None:
            raise NetError('key_unknown', 'this host keeps no key directory')
        kh = key_hash(str(raw))
        del raw
        recs = kd.store.find(self.p.node.net, kh)
        rec = next((r for r in recs if r.get('home_instance') == sender), recs[0] if recs else None)
        why = check_usable(rec, sender, self.p.node.clock(), kd.home_usable)
        if why is not None:
            raise NetError(why)
        owner = rec.get('owner') or {}
        login = str(owner.get('user_name') or '')
        roles = [str(r) for r in owner.get('roles') or []]
        return {'name': names.net_user(login, rec['home_instance']), 'net': self.p.node.net,
                'home': rec['home_instance'], 'user_name': login, 'display_name': str(owner.get('display_name') or login),
                'remote_roles': roles, 'roles': roles, 'key_id': rec['key_id'],
                'tool_access_mode': rec.get('tool_access_mode') or 'all',
                'tool_access_list': list(rec.get('tool_access_list') or []), 'identity': 'api_key',
                'mapping': 'home_identity'}


# ── the participant ────────────────────────────────────────────────

class NetParticipant:
    """One participant in one net, built from the core (see the module docstring)."""

    def __init__(self, cfg: NetConfig, signer: httpsig.Signer, trust: httpsig.Trust, *, source: CatalogSource,
                 execute: Callable[[CallContext, Dict[str, Any]], Dict[str, Any]],
                 connector: Optional[PeerConnector] = None, kv: Optional[KV] = None,
                 clock: Callable[[], float] = time.time, rules: Optional[RuleEvaluator] = None,
                 identity: Optional[IdentityResolver] = None, key_store=None, verify_keys: bool = True,
                 max_hops: int = 1, max_chain: int = 8, ca_certificate=None, manual: bool = False,
                 pins: Optional[Callable[[], List[str]]] = None, peer_cache_path: str = '',
                 events: Optional[Callable[[str, Dict[str, Any]], None]] = None,
                 audit: Optional[Callable[[str, Dict[str, Any]], None]] = None,
                 server_info: Optional[Dict[str, Any]] = None, calls_per_minute: int = 600,
                 refresh_interval: float = 300.0, write_identity: Optional[Callable] = None):
        self.cfg = cfg
        self.clock = clock
        self.server_info = dict(server_info or {'name': f'sajhanet-{cfg.kind}', 'version': '1'})
        self.rules = rules or ExportPolicy(host=cfg.instance_name)
        cfg.user_identity = ['api_key'] if verify_keys else ['none']
        self.node = NetNode(cfg, cfg.instance_name, signer, trust, kv or MemoryKV(clock),
                            connector or create('connector', 'sajha_native'), clock=clock, events=events,
                            ca_certificate=ca_certificate, manual=manual, pins=pins,
                            peer_cache=PeerCache(peer_cache_path) if peer_cache_path else None,
                            write_identity=write_identity)
        self.keys: Optional[KeyDirectory] = None
        if verify_keys:
            self.keys = KeyDirectory(self.node, key_store or MemoryKeyDirectory(), own=lambda: [],
                                     full_sync_interval=max(30.0, cfg.gossip.full_sync_interval_seconds)).install()
        self.identity = identity or (KeyDirectoryIdentity(self) if verify_keys else NoIdentity())
        self.book = CatalogBook(self.node, source, rules=self.rules, refresh_interval=refresh_interval).attach()
        self.host = HostServer(self.book, execute=execute, identity=self.identity, rules=self.rules,
                               max_hops=max_hops, max_chain=max_chain, other=self._other,
                               calls_per_minute=calls_per_minute, audit=audit).attach()
        self.participant = Participant({cfg.name: self.node})
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── building ───────────────────────────────────────────────────

    @classmethod
    def build(cls, *, net: str, instance: str, base_url: str, source: CatalogSource,
              execute: Callable[[CallContext, Dict[str, Any]], Dict[str, Any]], seeds: Iterable[str] = (),
              founder: bool = False, kind: str = 'agent', admission: str = 'open', data_dir: str = '',
              ca_url: str = '', token: str = '', ca_certificate=None, pins: Optional[List[str]] = None,
              connector: Optional[PeerConnector] = None, require_https: bool = True, region: str = '',
              labels: Optional[Dict[str, str]] = None, gossip: Optional[GossipSettings] = None,
              verify_keys: bool = True, rules: Optional[RuleEvaluator] = None, mcp_path: str = '/mcp',
              clock: Callable[[], float] = time.time, alg: str = crypto.ED25519, **kw) -> 'NetParticipant':
        """Configure, obtain an identity (the saved one, else a self-signed one for ``open`` or
        ``manual``, else enrollment with ``ca_url`` and ``token`` for ``builtin_ca``) and assemble."""
        if not names.is_net_name(net):
            raise ValueError(f'{net!r} is not a net name (protocol §5.1)')
        if not names.is_configured_name(instance):
            raise ValueError(f'{instance!r} is not an instance name (protocol §5.2)')
        if admission not in ('open', 'builtin_ca', 'manual'):
            raise ValueError('admission is open, builtin_ca or manual')
        connector = connector or create('connector', 'sajha_native')
        cfg = NetConfig(name=net, instance_name=instance, base_url=base_url.rstrip('/'), seeds=list(seeds),
                        founder=founder, kind=kind, admission=admission, require_https=require_https,
                        region=region, labels=dict(labels or {}), mcp_path=mcp_path,
                        gossip=gossip or GossipSettings(),
                        peer_cache=PeerCacheSettings(path=os.path.join(data_dir, 'peers.json') if data_dir else ''))
        host = urlsplit(cfg.base_url).hostname or ''
        files = IdentityFiles(data_dir) if data_dir else None
        held = files.load() if files is not None else None
        ca_cert = ca_certificate or (files.ca_certificate() if files is not None else None)
        if held is not None and crypto.subject_of(held[1]) != (net, instance):
            raise ValueError(f'the saved certificate in {data_dir} is for another net or name; remove it or use '
                             f'another data directory')
        if held is None:
            if admission == 'builtin_ca':
                if not (ca_url and token):
                    raise EnrollmentError(f'no certificate for {net}: give the CA participant\'s URL and an '
                                          f'enrollment token (its administrator creates one with `sajha net ca '
                                          f'enroll --net {net} --instance {instance}`)')
                key, cert, ca_cert = enroll(connector, net, instance, host, ca_url, token,
                                            require_https=require_https, alg=alg, ca_certificate=ca_cert, clock=clock)
            else:
                key, cert = self_signed(net, instance, host, alg=alg, now=clock())
            if files is not None:
                files.save(key, cert, ca_cert)
        else:
            key, cert = held
        manual = admission != 'builtin_ca'
        if admission == 'open':
            if files is not None:
                trust = FirstUseTrust(net, files.known, files.remember)
            else:
                mem: Dict[str, str] = {}
                trust = FirstUseTrust(net, lambda: mem, mem.__setitem__)
        elif admission == 'manual':
            pinned = list(pins or [])
            trust = PinnedTrust(net, lambda: pinned)
        else:
            if ca_cert is None:
                raise EnrollmentError(f'no CA certificate for {net}')
            trust = None                     # needs the node's KV for the revocation list: set below
        kv = kw.pop('kv', None) or MemoryKV(clock)
        if trust is None:
            trust = CATrust(net, ca_cert, lambda kv=kv: kv.get('rl'))

        def write_identity(k, c):
            if files is not None:
                files.save(k, c)
        return cls(cfg, httpsig.Signer(key, [cert]), trust, source=source, execute=execute, connector=connector,
                   kv=kv, clock=clock, rules=rules or ExportPolicy(host=instance), verify_keys=verify_keys,
                   ca_certificate=ca_cert, manual=manual, pins=(lambda: list(pins or [])),
                   peer_cache_path=cfg.peer_cache.path, write_identity=write_identity, **kw)

    # ── running ────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self.node.name

    @property
    def net(self) -> str:
        return self.node.net

    def start(self) -> 'NetParticipant':
        self.node.start()
        self.book.start()
        self.node.refresh_record()
        return self

    def tick(self) -> None:
        self.node.tick()

    def run_in_background(self) -> threading.Thread:
        """Run the gossip agent in a daemon thread until :meth:`stop`."""
        if not self.node.started:
            self.start()
        interval = max(0.05, self.cfg.gossip.gossip_interval_ms / 1000.0)

        def loop():
            while not self._stop.wait(interval):
                try:
                    self.node.tick()
                except Exception as e:                   # the agent keeps running
                    logger.warning(f'SAJHA Net {self.net}: tick failed: {e}', exc_info=True)
        self._thread = threading.Thread(target=loop, name=f'sajhanet-{self.net}', daemon=True)
        self._thread.start()
        return self._thread

    def stop(self, leave: bool = True) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        if leave and self.node.started:
            try:
                self.node.leave()
            except Exception as e:
                logger.debug(f'SAJHA Net {self.net}: leave: {e}')

    def invalidate(self) -> None:
        """The served catalog changed: recompute the digest so peers pull again."""
        self.book.invalidate()

    # ── serving ────────────────────────────────────────────────────

    def extension(self, signed: bool = True) -> Dict[str, Any]:
        return self.participant.extension(self.net if signed else None)

    def _other(self, msg: Dict[str, Any], v) -> Dict[str, Any]:
        """``ping``, ``server/discover`` and ``initialize`` from a participant (signed: the full object)."""
        return self._mcp_answer(msg, signed=True)

    def _mcp_answer(self, msg: Dict[str, Any], signed: bool) -> Dict[str, Any]:
        rid = msg.get('id')
        method = msg.get('method')
        ext = self.extension(signed)
        if method == 'ping':
            return {'jsonrpc': '2.0', 'id': rid, 'result': {}}
        if method == 'server/discover':
            return {'jsonrpc': '2.0', 'id': rid, 'result': {
                'supportedVersions': list(MCP_ERAS), 'serverInfo': self.server_info,
                'capabilities': {'tools': {}, 'extensions': {EXTENSION_ID: ext}}}}
        if method == 'initialize':
            return {'jsonrpc': '2.0', 'id': rid, 'result': {
                'protocolVersion': '2025-11-25', 'serverInfo': self.server_info,
                'capabilities': {'tools': {}, 'experimental': {EXTENSION_ID: ext}}}}
        return {'jsonrpc': '2.0', 'id': rid, 'error': {
            'code': -32601, 'message': f'{method} is not served here: this endpoint serves SAJHA Net participants'}}

    def handle(self, method: str, path: str, query: str, headers: Dict[str, str], body: bytes,
               secure: bool = True, source: str = '') -> PeerResponse:
        """One HTTP request: ``/sajhanet/...`` (§7), or the MCP endpoint, signed (§15) or not (an
        unsigned ``server/discover`` or ``initialize`` gets the reduced extension object, §6.1)."""
        h = httpsig.lower_headers(headers or {})
        if path.startswith('/sajhanet/'):
            return self.participant.handle(method, path, query, h, body, secure=secure, source=source)
        if path.rstrip('/') != (self.cfg.mcp_path or '/mcp').rstrip('/'):
            return empty_404()
        if any(k.startswith('sajha-net-') for k in h):
            return self.participant.handle_mcp(method, path, query, h, body, secure=secure, source=source) \
                or empty_404()
        if method.upper() != 'POST':
            return PeerResponse(405, {'allow': 'POST'}, b'')
        try:
            msg = json.loads((body or b'').decode('utf-8'))
        except ValueError:
            msg = None
        if not isinstance(msg, dict):
            return PeerResponse(400, {'content-type': 'application/json'},
                                b'{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"parse error"}}')
        if 'id' not in msg:
            return PeerResponse(202, {}, b'')
        out = self._mcp_answer(msg, signed=False)
        return PeerResponse(200, {'content-type': 'application/json'}, json.dumps(out).encode('utf-8'))

    # ── views ──────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        n = self.node
        return {'net': n.net, 'instance': n.name, 'kind': self.cfg.kind, 'url': self.cfg.base_url,
                'joined': n.joined(), 'refused': n.refused(), 'features': n.features,
                'certificate': crypto.thumbprint(crypto.cert_der(n.signer.chain[0])),
                'tools': [t['name'] for t in self.book.exports(None)],
                'members': [{'name': m['name'], 'state': m['state'], 'kind': m['record'].get('kind'),
                             'url': m['record'].get('url')} for m in n.members()]}
