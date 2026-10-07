"""
SAJHA's integration of the SAJHA Net core: one :class:`SajhaNetService` per process.

* Configuration from ``sajhanet.*`` (:mod:`sajha.net.integration.config`); off by default.
* Each net's state in the state store under ``sajhanet:<net>:`` (members, names, nonces,
  revocation list), so every worker of an instance sees one net; the CA's tokens, issued
  certificates and revocation list, runtime seeds and manual-mode pins in the storage backend
  (``<sajhanet.data_dir>/<net>/ca-state.json``, ``runtime_seeds.json``, ``pins.json``);
  keys and certificates in files named by the net's ``identity`` and ``ca`` references.
* One gossip agent per net and instance: the worker holding the renewing state-store lease
  ``sajhanet:agent:<net>`` (:class:`sajha.core.state.lease.Lease`) runs :meth:`NetNode.tick`.
* Operators hear about it through System Notices, the audit log, logs and metrics
  (``sajha_net_name_conflict``, ``sajha_net_members``, ``sajha_net_joined``).
* The routes are in ``sajha/routes/sajhanet_routes.py``; the CLI is ``sajha net ...``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

from sajha.net import crypto, httpsig, plugins, schemas
from sajha.net.ca import CertificateAuthority, NameHeld, init_ca
from sajha.net.membership import PeerCache
from sajha.net.models import DocumentKV, KV, NetConfig, PrefixKV
from sajha.net.node import NetNode, Participant, PeerRefused, ResponseInvalid
from sajha.net.plugins import PeerUnreachable
from sajha.net.integration.config import Shared, net_configs, ref_path, shared as load_shared

logger = logging.getLogger(__name__)

NOTICE_LINK = '/help/guides/SAJHA%20Net.md'


class ServiceError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


# ── files ───────────────────────────────────────────────────────────

def read_ref(ref: str) -> Optional[bytes]:
    """A ``file:`` or ``env:`` secret reference's bytes, or None when it is not there."""
    if not ref:
        return None
    if ref.startswith('env:'):
        v = os.environ.get(ref[4:])
        return v.encode('utf-8') if v else None
    path = ref_path(ref) or ref
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


def write_file(ref: str, data: bytes, private: bool) -> str:
    path = ref_path(ref)
    if not path:
        raise ServiceError(400, f'{ref!r} is not a file: reference; SAJHA Net writes only files')
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.sajhanet-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.chmod(tmp, 0o600 if private else 0o644)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def _cert_info(cert) -> Dict[str, Any]:
    o, cn = crypto.subject_of(cert)
    return {'net': o, 'instance': cn, 'serial': crypto.serial_hex(cert),
            'thumbprint': crypto.thumbprint(crypto.cert_der(cert)),
            'not_before': crypto.rfc3339(cert.not_valid_before_utc.timestamp()),
            'not_after': crypto.rfc3339(cert.not_valid_after_utc.timestamp()),
            'hosts': crypto.san_hosts(cert), 'renews': crypto.renews_of(cert)}


# ── operator signals ────────────────────────────────────────────────

def _notice(nid: str, severity: str, title: str, detail: str, ttl: Optional[float] = None) -> None:
    try:
        from sajha import notices
        notices.raise_notice(nid, severity=severity, source='sajhanet', title=title, detail=detail,
                             link=NOTICE_LINK, ttl_minutes=ttl)
    except Exception as e:
        logger.debug(f'SAJHA Net notice {nid}: {e}')


def _clear(nid: str) -> None:
    try:
        from sajha import notices
        notices.clear_notice(nid)
    except Exception as e:
        logger.debug(f'SAJHA Net clear {nid}: {e}')


def _audit(what: str, by: str = 'system', details: Any = None) -> None:
    try:
        from sajha.core.audit import AuditLogger
        AuditLogger().config_changed(f'sajhanet.{what}', by_user=by or 'system',
                                     details=json.dumps(details, default=str)[:2000] if details is not None else None)
    except Exception as e:
        logger.debug(f'SAJHA Net audit {what}: {e}')


def on_event(kind: str, data: Dict[str, Any]) -> None:
    """Map core events to System Notices (design §17.4), logs and the audit log."""
    net = data.get('net', '')
    if kind == 'joined':
        _clear(f'sajhanet.not_joined:{net}')
        _clear(f'sajhanet.name_conflict:{net}')
    elif kind in ('not_joined', 'config_error'):
        _notice(f'sajhanet.not_joined:{net}', 'error', f'Not joined to SAJHA Net {net}', data.get('detail', ''), ttl=0)
    elif kind == 'name_conflict' and data.get('own'):
        _notice(f'sajhanet.name_conflict:{net}', 'error', f'Name {data.get("instance")} is held in {net}',
                f'Every member refuses this server under the name {data.get("instance")}: it is held by '
                f'{data.get("holder_url") or "another participant"} (certificate {data.get("holder_thumbprint")}, '
                f'{data.get("holder_state")}). This server does not join {net} until its configuration or '
                f'certificate changes; its local tools keep working.', ttl=0)
        _audit('name_conflict', details=data)
    elif kind == 'name_conflict_seen':
        _notice(f'sajhanet.name_conflict_seen:{net}:{data.get("claimant")}', 'warning',
                f'Two participants claim {data.get("claimant")} in {net}',
                f'A participant at {data.get("claimant_url") or "an unknown address"} (certificate '
                f'{data.get("claimant_thumbprint")}) claims the name held by {data.get("holder_url")} '
                f'(certificate {data.get("holder_thumbprint")}); it was refused.', ttl=60)
    elif kind == 'member_state':
        nid = f'sajhanet.member:{net}:{data.get("member")}'
        if data.get('state') == 'alive':
            _clear(nid)
        else:
            _notice(nid, 'warning', f'{data.get("member")} is {data.get("state")} in {net}',
                    f'Member {data.get("member")} ({data.get("url")}) is {data.get("state")} '
                    f'(was {data.get("previous") or "unknown"}).',
                    ttl=0 if data.get('state') == 'dead' else None)
    elif kind == 'member_removed':
        _clear(f'sajhanet.member:{net}:{data.get("member")}')
    elif kind == 'certificate_expiring':
        _notice(f'sajhanet.certificate:{net}', 'error' if data.get('expired') else 'warning',
                f'SAJHA Net certificate for {net} {"expired" if data.get("expired") else "expiring"}',
                f'This server\'s certificate in {net} is valid until {data.get("not_after")}; it renews itself at '
                f'the CA participant when a third of its validity remains.', ttl=0)
    elif kind == 'renewed':
        _clear(f'sajhanet.certificate:{net}')
        _clear(f'sajhanet.renewal:{net}')
        _audit('certificate_renewed', details=data)
    elif kind == 'renewal_failed':
        _notice(f'sajhanet.renewal:{net}', 'warning', f'Certificate renewal failing in {net}',
                f'This server could not renew its certificate at the CA participant of {net}: '
                f'{data.get("detail", "")}. It keeps trying with back-off.')
    elif kind == 'revocations_stale':
        _notice(f'sajhanet.revocations:{net}', 'warning', f'Revocation list of {net} is stale',
                data.get('detail', 'A member holds a newer revocation list that could not be fetched.'))
    elif kind == 'revocations_updated':
        _clear(f'sajhanet.revocations:{net}')
    elif kind == 'left':
        logger.info(f'SAJHA Net {net}: left (told {data.get("told")} members)')


def _metrics_collector():
    svc = _service
    if svc is None:
        return []
    conflict, members, joined = [], [], []
    for net, rt in svc.runtimes.items():
        node = rt.node
        refused = bool(node and node.refused())
        conflict.append(('sajha_net_name_conflict', {'net': net}, 1.0 if refused else 0.0))
        joined.append(('sajha_net_joined', {'net': net}, 1.0 if node and node.joined() else 0.0))
        counts: Dict[str, int] = {s: 0 for s in ('alive', 'suspect', 'dead', 'left')}
        for m in (node.members() if node else []):
            counts[m['state']] = counts.get(m['state'], 0) + 1
        for s, n in counts.items():
            members.append(('sajha_net_members', {'net': net, 'state': s}, float(n)))
    return [('sajha_net_name_conflict', 'gauge', 'This server refused in a net under a held name (1) or not (0).',
             conflict),
            ('sajha_net_joined', 'gauge', 'This server has joined the net (1) or not (0).', joined),
            ('sajha_net_members', 'gauge', 'Members of each net this server knows, by state.', members)]


_collector_added = False


def _add_collector() -> None:
    global _collector_added
    if _collector_added:
        return
    try:
        from sajha.observability.metrics import REGISTRY
        REGISTRY.add_collector(_metrics_collector)
        _collector_added = True
    except Exception as e:
        logger.debug(f'SAJHA Net metrics: {e}')


# ── the service ─────────────────────────────────────────────────────

@dataclass
class Runtime:
    cfg: NetConfig
    node: Optional[NetNode] = None
    error: str = ''
    ca: Optional[CertificateAuthority] = None
    thread: Optional[threading.Thread] = None
    lease: Any = None
    stop: threading.Event = field(default_factory=threading.Event)


class SajhaNetService:
    def __init__(self, s: Shared, configs: List[NetConfig], errors: Dict[str, str], store=None,
                 connector: Optional[plugins.PeerConnector] = None, clock: Callable[[], float] = time.time,
                 documents: Optional[Any] = None):
        self.shared = s
        self.clock = clock
        self.errors = dict(errors)
        self._store = store
        self.documents = documents
        self.connector = connector or plugins.create('connector', s.connector)
        self.runtimes: Dict[str, Runtime] = {c.name: Runtime(cfg=c) for c in configs}
        self.participant = Participant({}, enabled=s.enabled)
        self._lock = threading.RLock()

    # ── stores ─────────────────────────────────────────────────────

    @property
    def store(self) -> KV:
        if self._store is None:
            from sajha.core.state import get_state_store
            self._store = get_state_store()
        return self._store

    def _doc_io(self, path: str):
        def read():
            try:
                if self.documents is not None:
                    return self.documents.read_json(path) if self.documents.exists(path) else {}
                from sajha.core.storage import get_storage
                st = get_storage()
                return st.read_json(path) if st.exists(path) else {}
            except Exception as e:
                logger.warning(f'SAJHA Net: cannot read {path}: {e}')
                return {}

        def write(doc):
            if self.documents is not None:
                self.documents.write_json(path, doc)
                return
            from sajha.core.storage import get_storage
            get_storage().write_json(path, doc)
        return read, write

    def _ca_kv(self, net: str) -> KV:
        r, w = self._doc_io(f'{self.shared.data_dir}/{net}/ca-state.json')
        return DocumentKV(r, w, self.clock)

    def _list_doc(self, net: str, what: str) -> List[Dict[str, Any]]:
        r, _ = self._doc_io(f'{self.shared.data_dir}/{net}/{what}.json')
        return list((r() or {}).get('items') or [])

    def _save_list_doc(self, net: str, what: str, items: List[Dict[str, Any]]) -> None:
        _, w = self._doc_io(f'{self.shared.data_dir}/{net}/{what}.json')
        w({'items': items})

    def runtime_seeds(self, net: str) -> List[Dict[str, Any]]:
        return self._list_doc(net, 'runtime_seeds')

    def runtime_pins(self, net: str) -> List[str]:
        return [p['thumbprint'] for p in self._list_doc(net, 'pins') if p.get('thumbprint')]

    # ── building nodes ─────────────────────────────────────────────

    def _build(self, rt: Runtime) -> None:
        cfg = rt.cfg
        net = cfg.name
        rt.node, rt.ca, rt.error = None, None, ''
        if net in self.errors:
            rt.error = self.errors[net]
            return
        try:
            adm = plugins.create('admission', cfg.admission)
            membership = plugins.create('membership', cfg.membership)
        except Exception as e:
            rt.error = f'plug-in: {e}'
            return
        ca_cert = None
        raw = read_ref(cfg.identity.ca_ref)
        if raw and not adm.manual:
            try:
                ca_cert = crypto.load_cert(raw)
            except Exception as e:
                rt.error = f'the CA certificate ({cfg.identity.ca_ref}) cannot be read: {e}'
                return
        if cfg.ca.enabled and not adm.manual:
            ck, cc = read_ref(cfg.ca.key_ref), read_ref(cfg.ca.cert_ref)
            if ck and cc:
                try:
                    rt.ca = CertificateAuthority(net, crypto.key_from_pem(ck), crypto.load_cert(cc), self._ca_kv(net),
                                                 self.clock, validity_days=cfg.ca.cert_validity_days,
                                                 token_minutes=cfg.ca.enrollment_token_minutes,
                                                 enrollments_per_minute=cfg.ca.enrollments_per_minute)
                    ca_cert = rt.ca.cert
                except Exception as e:
                    rt.error = f'the CA key or certificate cannot be loaded: {e}'
                    return
        host = urlsplit(cfg.base_url).hostname or ''
        kb, cb = read_ref(cfg.identity.key_ref), read_ref(cfg.identity.cert_ref)
        if not kb or not cb:
            if adm.manual:
                key = crypto.generate_key()
                cert = crypto.self_signed_certificate(key, net, cfg.instance_name, host, now=self.clock())
                write_file(cfg.identity.key_ref, crypto.key_to_pem(key), private=True)
                write_file(cfg.identity.cert_ref, crypto.cert_pem(cert), private=False)
                logger.info(f'SAJHA Net {net}: created a self-signed certificate ({crypto.thumbprint(crypto.cert_der(cert))})')
            elif rt.ca is not None:
                key = crypto.generate_key()
                cert = rt.ca.issue_own(key, cfg.instance_name, host)
                write_file(cfg.identity.key_ref, crypto.key_to_pem(key), private=True)
                write_file(cfg.identity.cert_ref, crypto.cert_pem(cert), private=False)
            elif cfg.ca.enabled:
                rt.error = (f'this server is the CA instance of {net} but the CA is not initialised: run '
                            f'`sajha net ca init --net {net}`')
                return
            else:
                rt.error = (f'no certificate for {net}: enroll with `sajha net enroll --net {net} --ca-url <CA URL> '
                            f'--token <token>` (the CA administrator creates the token with `sajha net ca enroll`)')
                return
        else:
            try:
                key, cert = crypto.key_from_pem(kb), crypto.load_cert(cb)
            except Exception as e:
                rt.error = f'the instance key or certificate cannot be loaded: {e}'
                return
        if crypto.subject_of(cert) != (net, cfg.instance_name):
            o, cn = crypto.subject_of(cert)
            rt.error = (f'the certificate names O={o}, CN={cn}, but this server is {cfg.instance_name} in {net}; '
                        f'enroll again for the configured name')
            return
        if not adm.manual and ca_cert is None:
            rt.error = f'no CA certificate for {net} at {cfg.identity.ca_ref}'
            return
        kv = PrefixKV(self.store, f'sajhanet:{net}:')
        trust = adm.trust(net, cfg, ca_cert, lambda kv=kv: kv.get('rl'),
                          lambda c=cfg, n=net: list(c.identity.pins) + self.runtime_pins(n))

        def write_identity(k, c, cfg=cfg):
            write_file(cfg.identity.key_ref, crypto.key_to_pem(k), private=True)
            write_file(cfg.identity.cert_ref, crypto.cert_pem(c), private=False)

        node = NetNode(cfg, cfg.instance_name, httpsig.Signer(key, [cert]), trust, kv, self.connector,
                       clock=self.clock, events=on_event, ca=rt.ca, ca_certificate=ca_cert,
                       peer_cache=PeerCache(cfg.peer_cache.path), membership=membership, manual=adm.manual,
                       pins=lambda c=cfg, n=net: list(c.identity.pins) + self.runtime_pins(n),
                       write_identity=write_identity,
                       runtime_seeds=lambda n=net: [s['url'] for s in self.runtime_seeds(n)])
        rl = read_ref(cfg.identity.revocation_list_ref)
        if rl and not adm.manual:
            try:
                node.accept_revocations(json.loads(rl.decode('utf-8')))
            except Exception as e:
                logger.warning(f'SAJHA Net {net}: the configured revocation list is unreadable: {e}')
        try:                                             # identity, key directory, blocks (design §10, §11)
            from sajha.net.integration.authz import get_authz
            get_authz(self).attach(cfg, node)
        except Exception as e:
            logger.warning(f'SAJHA Net {net}: identity and authorization not installed: {e}', exc_info=True)
        try:                                             # catalogs, proxies, routing (design §7-§9)
            from sajha.net.integration.catalogs import get_net_catalogs
            get_net_catalogs(self).attach(cfg, node)
        except Exception as e:
            logger.warning(f'SAJHA Net {net}: catalogs not installed: {e}', exc_info=True)
        node.start()
        if not node.refused():
            _clear(f'sajhanet.name_conflict:{net}')
        rt.node = node
        self.participant.nodes[net] = node

    def start(self, run_agents: bool = True) -> None:
        _add_collector()
        if not self.shared.enabled:
            return
        if self.shared.mtls not in ('off', 'false', ''):
            logger.warning(f'sajhanet.mtls: {self.shared.mtls!r} is not built yet; requests are checked by their '
                           f'signatures only')
        for net, rt in self.runtimes.items():
            try:
                self._build(rt)
            except Exception as e:
                logger.warning(f'SAJHA Net {net}: not started: {e}', exc_info=True)
                rt.error = str(e)
            if rt.error:
                logger.error(f'SAJHA Net {net}: {rt.error}')
                _notice(f'sajhanet.not_joined:{net}', 'error', f'Not joined to SAJHA Net {net}', rt.error, ttl=0)
            if net == 'default':
                _notice('sajhanet.default_name', 'info', 'A SAJHA Net net is still named default',
                        'Give the net a name (sajhanet.nets[].name) before it is used in production.', ttl=0)
            if not rt.cfg.require_https:
                _notice(f'sajhanet.plain_http:{net}', 'warning', f'SAJHA Net {net} allows plain HTTP',
                        'require_https is false: forwarded API keys may travel over plain HTTP. Lab use only.', ttl=0)
            if run_agents and rt.node is not None:
                self._start_agent(rt)
        try:
            from sajha.core import net_extension
            feats = sorted({f for rt in self.runtimes.values() if rt.node for f in rt.node.features})
            net_extension.advertise(features=feats, user_identity=sorted(
                {u for rt in self.runtimes.values() if rt.node for u in rt.cfg.user_identity}) or ['none'],
                                    signature_algorithms=[crypto.ED25519, crypto.P256])
        except Exception as e:
            logger.debug(f'SAJHA Net advertisement: {e}')

    def _start_agent(self, rt: Runtime) -> None:
        from sajha.core.state.lease import Lease
        rt.stop.clear()
        rt.lease = Lease(f'sajhanet:agent:{rt.cfg.name}', ttl=self.shared.agent_lease_seconds, store=self.store)
        interval = max(0.05, rt.cfg.gossip.gossip_interval_ms / 1000.0)

        def loop():
            while not rt.stop.wait(interval):
                node = rt.node
                if node is None:
                    return
                cat = getattr(self, 'catalogs', None)
                if cat is not None:                      # every worker keeps its registry's proxies current
                    try:
                        cat.maybe_sync()
                    except Exception as e:
                        logger.warning(f'SAJHA Net {rt.cfg.name}: proxy sync failed: {e}', exc_info=True)
                if not rt.lease.held and not rt.lease.try_acquire():
                    continue
                try:
                    node.tick()
                except Exception as e:
                    logger.warning(f'SAJHA Net {rt.cfg.name}: gossip tick failed: {e}', exc_info=True)
        rt.thread = threading.Thread(target=loop, name=f'sajhanet-{rt.cfg.name}', daemon=True)
        rt.thread.start()

    def _stop_agent(self, rt: Runtime, leave: bool) -> None:
        rt.stop.set()
        if rt.thread is not None and rt.thread is not threading.current_thread():
            rt.thread.join(timeout=5)
        rt.thread = None
        if rt.lease is not None and rt.lease.held:
            if leave and rt.node is not None:
                try:
                    rt.node.leave()
                except Exception as e:
                    logger.debug(f'SAJHA Net {rt.cfg.name}: leave: {e}')
            rt.lease.release()
        rt.lease = None

    def rebuild(self, net: str, run_agent: bool = True) -> Runtime:
        rt = self._rt(net)
        self._stop_agent(rt, leave=False)
        self.participant.nodes.pop(net, None)
        if getattr(self, 'catalogs', None) is not None:
            self.catalogs.detach(net)
        self._build(rt)
        if rt.node is not None and run_agent and self.shared.enabled:
            self._start_agent(rt)
        return rt

    def stop(self) -> None:
        for rt in self.runtimes.values():
            self._stop_agent(rt, leave=True)
        if getattr(self, 'catalogs', None) is not None:
            self.catalogs.clear_registry()

    # ── views ──────────────────────────────────────────────────────

    def _rt(self, net: str) -> Runtime:
        rt = self.runtimes.get(net)
        if rt is None:
            raise ServiceError(404, f'this server is not configured for net {net!r}')
        return rt

    def _node(self, net: str) -> NetNode:
        rt = self._rt(net)
        if rt.node is None:
            raise ServiceError(409, rt.error or f'net {net} is not running')
        return rt.node

    def status(self) -> Dict[str, Any]:
        nets = []
        for net, rt in self.runtimes.items():
            node = rt.node
            item: Dict[str, Any] = {
                'net': net, 'instance': rt.cfg.instance_name, 'url': rt.cfg.base_url, 'founder': rt.cfg.founder,
                'seeds': list(rt.cfg.seeds), 'runtime_seeds': self.runtime_seeds(net) if self.shared.enabled else [],
                'admission': rt.cfg.admission, 'membership': rt.cfg.membership, 'error': rt.error,
                'ca': {'enabled': rt.cfg.ca.enabled, 'initialised': rt.ca is not None}}
            if node is not None:
                st = node.status()
                item.update(joined=node.joined(), refused=node.refused(), features=node.features,
                            incarnation=node.incarnation(), certificate=_cert_info(node.signer.chain[0]),
                            last_errors=st.get('last_errors') or [], config_error=st.get('config_error'),
                            revocations=(node.revocation_list() or {}).get('version', 0),
                            agent=rt.lease.current_holder() if rt.lease is not None else None,
                            members=[{'name': m['name'], 'state': m['state'], 'url': m['record'].get('url'),
                                      'region': m['record'].get('region', ''), 'kind': m['record'].get('kind'),
                                      'incarnation': m['record'].get('incarnation'),
                                      'features': m['record'].get('features'),
                                      'last_seen': crypto.rfc3339(m['last_seen']) if m.get('last_seen') else None}
                                     for m in node.members()])
            authz = getattr(self, 'authz', None)
            if authz is not None and net in authz.nets:
                try:
                    item['authz'] = authz.status(net)
                except Exception as e:
                    logger.debug(f'SAJHA Net {net}: authorization status: {e}')
            nets.append(item)
        return {'enabled': self.shared.enabled, 'protocol_versions': [1], 'nets': nets}

    # ── operations (admin API, CLI) ────────────────────────────────

    def inject(self, net: str, address: str, keep_as_seed: bool = False, by: str = '') -> Dict[str, Any]:
        """Contact a peer at an operator-given address with a signed join (design §6.6)."""
        node = self._node(net)
        cfg = node.cfg
        address = (address or '').strip()
        if not address:
            raise ServiceError(400, 'give the peer address as ip:port, host:port or a URL')
        recorded, _hits = self.store.window_add(f'sajhanet:{net}:inject', 60, cfg.max_injections_per_minute)
        if not recorded:
            raise ServiceError(429, 'too many peer additions this minute; try again shortly')
        url = address if '://' in address else ('https://' if cfg.require_https else 'http://') + address
        url = url.rstrip('/')
        try:
            from sajha.federation.security import check_peer_url
            check_peer_url(url, require_https=cfg.require_https)
        except ImportError:                                  # pragma: no cover - stream B's guard is present
            pass
        except Exception as e:
            self._injected(net, url, False, f'refused by the network rules: {e}', by)
            raise ServiceError(400, f'the address is refused: {e}')
        try:
            x = node.sync(url, httpsig.ANY, reason='join')
        except PeerRefused as e:
            if e.reason == 'name_conflict':
                node._refuse(e)
            self._injected(net, url, False, f'{e.reason}: {e.body.get("detail", "")}', by)
            raise ServiceError(409 if e.reason == 'name_conflict' else 502, f'the peer refused: {e.reason}',
                               reason=e.reason)
        except ResponseInvalid as e:
            self._injected(net, url, False, e.reason, by)
            raise ServiceError(502, f'the peer\'s answer was refused: {e.reason}', reason=e.reason)
        except PeerUnreachable as e:
            self._injected(net, url, False, 'unreachable', by)
            raise ServiceError(502, f'the peer is unreachable: {e}', reason='unreachable')
        if not node.joined():
            node._set_status(joined=True, joined_at=self.clock(), joined_via=url, config_error=None)
            on_event('joined', {'net': net, 'via': url})
        node.save_peers(force=True)
        if keep_as_seed:
            items = [s for s in self.runtime_seeds(net) if s.get('url') != url]
            items.append({'url': url, 'name': x.sender, 'added_by': by, 'added_at': crypto.rfc3339(self.clock())})
            self._save_list_doc(net, 'runtime_seeds', items)
        self._injected(net, url, True, x.sender, by, keep_as_seed)
        return {'ok': True, 'net': net, 'peer': x.sender, 'url': url, 'kept_as_seed': bool(keep_as_seed)}

    def _injected(self, net: str, url: str, ok: bool, detail: str, by: str, seed: bool = False) -> None:
        _audit('peer_added' if ok else 'peer_add_failed', by, {'net': net, 'url': url, 'detail': detail,
                                                                'kept_as_seed': seed})
        _notice(f'sajhanet.peer_added:{net}:{url}', 'info' if ok else 'warning',
                f'Peer {"added" if ok else "not added"} in {net}',
                f'{by or "An administrator"} pointed this server at {url} for {net}: '
                f'{("joined with " + detail) if ok else "failed (" + detail + "); nothing was stored"}.',
                ttl=24 * 60)

    def remove_runtime_seed(self, net: str, url: str, by: str = '') -> bool:
        items = self.runtime_seeds(net)
        keep = [s for s in items if s.get('url') != url.rstrip('/')]
        if len(keep) == len(items):
            return False
        self._save_list_doc(net, 'runtime_seeds', keep)
        _audit('runtime_seed_removed', by, {'net': net, 'url': url})
        return True

    def ca_init(self, net: str, by: str = '', alg: str = crypto.ED25519) -> Dict[str, Any]:
        rt = self._rt(net)
        cfg = rt.cfg
        if not cfg.ca.enabled:
            raise ServiceError(409, f'this server is not the CA instance of {net} (set ca.enabled in its net entry)')
        if cfg.admission != 'builtin_ca':
            raise ServiceError(409, 'the net runs in manual mode: it has no CA')
        if read_ref(cfg.ca.key_ref):
            raise ServiceError(409, f'the CA of {net} is already initialised ({cfg.ca.key_ref})')
        key, cert = init_ca(net, alg=alg, now=self.clock())
        write_file(cfg.ca.key_ref, crypto.key_to_pem(key), private=True)
        write_file(cfg.ca.cert_ref, crypto.cert_pem(cert), private=False)
        if ref_path(cfg.identity.ca_ref) and ref_path(cfg.identity.ca_ref) != ref_path(cfg.ca.cert_ref):
            write_file(cfg.identity.ca_ref, crypto.cert_pem(cert), private=False)
        _audit('ca_initialised', by, {'net': net, 'thumbprint': crypto.thumbprint(crypto.cert_der(cert))})
        self.rebuild(net)
        logger.warning(f'SAJHA Net {net}: CA initialised; back up {cfg.ca.key_ref} (it never leaves this server)')
        return {'net': net, 'ca_certificate': crypto.cert_pem(cert).decode('ascii'),
                'thumbprint': crypto.thumbprint(crypto.cert_der(cert)), 'key_ref': cfg.ca.key_ref,
                'backup': 'Back up the CA key file now; it is the only copy.'}

    def _ca(self, net: str) -> CertificateAuthority:
        rt = self._rt(net)
        if rt.ca is None:
            raise ServiceError(409, f'this server holds no CA key for {net}')
        return rt.ca

    def ca_token(self, net: str, instance: str, host: str = '', by: str = '') -> Dict[str, Any]:
        ca = self._ca(net)
        try:
            token, rec = ca.create_token(instance, host=host, by=by)
        except NameHeld as e:
            _audit('ca_token_refused', by, {'net': net, 'instance': instance, 'holder': e.holder})
            raise ServiceError(409, str(e), holder=e.holder)
        except ValueError as e:
            raise ServiceError(400, str(e))
        _audit('ca_token_created', by, {'net': net, 'instance': instance, 'host': host})
        node = self.runtimes[net].node
        return {'net': net, 'instance': instance, 'token': token, 'expires_at': crypto.rfc3339(rec['expires']),
                'ca_url': node.cfg.base_url if node else '', 'ca_certificate': crypto.cert_pem(ca.cert).decode(),
                'ca_thumbprint': ca.thumbprint}

    def ca_revoke(self, net: str, instance: str = '', serial: str = '', reason: str = '', by: str = '') -> Dict[str, Any]:
        ca = self._ca(net)
        try:
            doc = ca.revoke(instance=instance or None, serial=serial or None, reason=reason)
        except ValueError as e:
            raise ServiceError(400, str(e))
        rt = self.runtimes[net]
        if rt.node is not None:
            rt.node.accept_revocations(doc)
        try:
            write_file(rt.cfg.identity.revocation_list_ref, json.dumps(doc, indent=1).encode(), private=False)
        except Exception as e:
            logger.warning(f'SAJHA Net {net}: revocation list not written to {rt.cfg.identity.revocation_list_ref}: {e}')
        _audit('ca_revoked', by, {'net': net, 'instance': instance, 'serial': serial, 'version': doc['version']})
        return {'net': net, 'version': doc['version'], 'revoked': doc['revoked']}

    def ca_view(self, net: str) -> Dict[str, Any]:
        ca = self._ca(net)
        rl = ca.revocation_list() or {}
        return {'net': net, 'thumbprint': ca.thumbprint, 'issued': ca.issued(),
                'pending_tokens': [{k: v for k, v in t.items() if k not in ('created',)} for t in ca.pending_tokens()],
                'revocation_list': {'version': rl.get('version'), 'revoked': rl.get('revoked', [])}}

    def enroll(self, net: str, ca_url: str, token: str, by: str = '', alg: str = crypto.ED25519) -> Dict[str, Any]:
        """Obtain this server's certificate for ``net`` from the CA participant (§14.1)."""
        rt = self._rt(net)
        cfg = rt.cfg
        if net in self.errors:
            raise ServiceError(409, self.errors[net])
        host = urlsplit(cfg.base_url).hostname or ''
        key = crypto.generate_key(alg)
        body = {'net': net, 'instance': cfg.instance_name, 'token': token,
                'csr': crypto.b64(crypto.make_csr(key, net, cfg.instance_name, host))}
        raw = json.dumps(body).encode()
        url = ca_url.rstrip('/') + '/sajhanet/v1/ca/enroll'
        if cfg.require_https and not url.startswith('https://'):
            raise ServiceError(400, 'enrollment is only over HTTPS (require_https)')
        try:
            r = self.connector.send('POST', url, {'content-type': 'application/json', 'sajha-net-version': '1',
                                                  'sajha-net-name': net}, raw, 30)
        except PeerUnreachable as e:
            raise ServiceError(502, f'the CA is unreachable: {e}')
        try:
            data = json.loads(r.body.decode('utf-8')) if r.body else {}
        except ValueError:
            data = {}
        if r.status != 200:
            raise ServiceError(502 if r.status >= 500 else 403, f'the CA refused: {data.get("reason") or r.status}',
                               reason=data.get('reason'))
        if schemas.errors('enroll_response', data):
            raise ServiceError(502, 'the CA answer fails its schema')
        ca_cert = crypto.load_cert(crypto.unb64(data['ca_certificate']))
        pinned = read_ref(cfg.identity.ca_ref)
        if pinned and crypto.cert_der(crypto.load_cert(pinned)) != crypto.cert_der(ca_cert):
            raise ServiceError(502, 'the CA certificate in the answer differs from the configured one')
        from sajha.net.trust import CATrust
        try:
            httpsig.verify_response(CATrust(net, ca_cert, lambda: None), cfg.instance_name, httpsig.ANY, r.status,
                                    r.headers, r.body, None, now=self.clock(),
                                    max_age=cfg.signature_max_age_seconds)
        except Exception as e:
            raise ServiceError(502, f'the CA answer does not verify: {getattr(e, "reason", e)}')
        cert = crypto.chain_from_b64(data['certificate'])[0]
        if cert.public_key().public_bytes(*_raw_pub()) != key.public_key().public_bytes(*_raw_pub()) or \
                crypto.subject_of(cert) != (net, cfg.instance_name):
            raise ServiceError(502, 'the issued certificate is not for this key and name')
        write_file(cfg.identity.key_ref, crypto.key_to_pem(key), private=True)
        write_file(cfg.identity.cert_ref, crypto.cert_pem(cert), private=False)
        if not pinned:
            write_file(cfg.identity.ca_ref, crypto.cert_pem(ca_cert), private=False)
        _audit('enrolled', by, {'net': net, 'serial': crypto.serial_hex(cert)})
        self.rebuild(net)
        return {'net': net, 'certificate': _cert_info(cert)}

    def renew(self, net: str, by: str = '') -> Dict[str, Any]:
        node = self._node(net)
        try:
            cert = node.renew()
        except Exception as e:
            raise ServiceError(502, f'renewal failed: {e}')
        _audit('renewed', by, {'net': net, 'serial': crypto.serial_hex(cert)})
        return {'net': net, 'certificate': _cert_info(cert)}

    def add_pin(self, net: str, thumbprint: str, by: str = '') -> Dict[str, Any]:
        node = self._node(net)
        if not node.manual:
            raise ServiceError(409, f'{net} is not in manual mode; pins apply only there')
        thumbprint = thumbprint.strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', thumbprint):
            raise ServiceError(400, 'a thumbprint is 43 base64url characters (the SHA-256 of the certificate)')
        items = [p for p in self._list_doc(net, 'pins') if p.get('thumbprint') != thumbprint]
        items.append({'thumbprint': thumbprint, 'added_by': by, 'added_at': crypto.rfc3339(self.clock())})
        self._save_list_doc(net, 'pins', items)
        _audit('pin_added', by, {'net': net, 'thumbprint': thumbprint})
        return {'net': net, 'pins': [p['thumbprint'] for p in items]}

    def remove_pin(self, net: str, thumbprint: str, by: str = '') -> bool:
        items = self._list_doc(net, 'pins')
        keep = [p for p in items if p.get('thumbprint') != thumbprint]
        if len(keep) == len(items):
            return False
        self._save_list_doc(net, 'pins', keep)
        _audit('pin_removed', by, {'net': net, 'thumbprint': thumbprint})
        return True


def _raw_pub():
    from cryptography.hazmat.primitives import serialization
    return serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo


# ── process singleton ───────────────────────────────────────────────

_service: Optional[SajhaNetService] = None


def get_service() -> Optional[SajhaNetService]:
    return _service


def set_service(svc: Optional[SajhaNetService]) -> None:
    global _service
    _service = svc


def init_sajhanet(run_agents: bool = True) -> SajhaNetService:
    """Build the service from configuration (start-up). With ``sajhanet.enabled: false`` it serves
    nothing: every ``/sajhanet/`` path answers 404."""
    from sajha.core.config import get_settings
    s = load_shared()
    st = get_settings()
    configs, errors = net_configs(s, bind_host=str(st.server_host), port=int(st.server_port)) if s.enabled else ([], {})
    svc = SajhaNetService(s, configs, errors)
    set_service(svc)
    svc.start(run_agents=run_agents)
    return svc


def shutdown_sajhanet() -> None:
    svc = _service
    if svc is not None:
        svc.stop()
    set_service(None)
