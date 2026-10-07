"""
A participant: one :class:`NetNode` per net, kept apart on one port by the signed
``Sajha-Net-Name`` header (protocol §7.7), and :class:`Participant`, which selects the node.

A node serves the ``/sajhanet/v1/`` endpoints of its features (§7.2) and runs the gossip agent
(§9): join through seeds, then saved peers, then discovery; ping, ping-req, suspicion and death;
dissemination; anti-entropy; leave; dead probing; revocation-list pulls; name ownership by
certificate lineage and loud ``name_conflict`` refusals (§5.2).

Everything a node remembers lives in a :class:`~sajha.net.models.KV` (SAJHA: the state store,
so every worker of an instance sees one net); the agent's work is driven by :meth:`NetNode.tick`,
which one worker runs (SAJHA: the holder of the net's lease). Time comes from an injectable clock.

Events for operators (``events(kind, data)``): ``joined``, ``not_joined``, ``config_error``,
``name_conflict`` (this participant refused), ``name_conflict_seen`` (two others claim a name),
``member_state`` (a member's state changed), ``member_removed``, ``revocations_updated``,
``revocations_stale``, ``certificate_expiring``, ``renewed``, ``renewal_failed``, ``left``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from sajha.net import ENDPOINT, PROTOCOL_VERSION, SUPPORTED_VERSIONS, crypto, httpsig, names, schemas
from sajha.net.ca import CertificateAuthority
from sajha.net.errors import NetError, problem, problem_from
from sajha.net.membership import (PeerCache, decide_merge, dissemination_limit, new_incarnation,
                                  saved_peers_to_try, KEEP)
from sajha.net.models import KV, NetConfig, PRECEDENCE, member_record
from sajha.net.plugins import GossipMembership, MembershipProvider, PeerConnector, PeerResponse, PeerUnreachable
from sajha.net.trust import revocation_reason, verify_revocation_list

logger = logging.getLogger(__name__)

P = ENDPOINT.rstrip('/')
KIB = 1024

#: path -> (method, feature, schema of the body, size limit, signed)
ROUTES: Dict[str, Tuple[str, Optional[str], Optional[str], int, bool]] = {
    P + '/gossip/ping': ('POST', 'gossip', 'ping', 64 * KIB, True),
    P + '/gossip/ping-req': ('POST', 'gossip', 'ping_req', 64 * KIB, True),
    P + '/membership/sync': ('POST', 'gossip', 'sync', 1024 * KIB, True),
    P + '/membership/leave': ('POST', 'gossip', 'leave', 16 * KIB, True),
    P + '/revocations': ('GET', None, None, 0, True),
    P + '/ca/enroll': ('POST', 'ca', 'enroll_request', 64 * KIB, False),
    P + '/ca/renew': ('POST', 'ca', 'renew_request', 64 * KIB, True),
    # catalog, visibility, keys, blocks and conflicts are served once their features are built
    P + '/catalog': ('POST', 'catalog', 'catalog_request', 64 * KIB, True),
    P + '/catalog/visibility': ('POST', 'visibility', 'visibility_request', 64 * KIB, True),
    P + '/keys': ('POST', 'key_directory', 'keys_request', 64 * KIB, True),
    P + '/keys/digest': ('POST', 'key_directory', 'keys_digest_request', 64 * KIB, True),
    P + '/blocks': ('POST', 'blocks', 'empty_request', 64 * KIB, True),
    P + '/conflicts': ('POST', 'catalog', 'empty_request', 64 * KIB, True),
}
MAX_HEADERS = 16 * KIB
MAX_UPDATES = 32
REVOCATIONS_STALE_SECONDS = 600


def empty_404() -> PeerResponse:
    return PeerResponse(404, {}, b'')


def dumps(obj: Any) -> bytes:
    return json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


@dataclass
class Exchange:
    """The verified answer of a peer."""
    status: int
    body: Any
    sender: str
    verified: httpsig.Verified


class ResponseInvalid(PeerUnreachable):
    """A response that failed verification (§8.8): treated as a transport failure, with its reason."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f'{reason}: {detail}')
        self.reason = reason


class PeerRefused(Exception):
    """A peer answered with a signed refusal (``problem``)."""

    def __init__(self, status: int, body: Dict[str, Any], sender: str = ''):
        super().__init__(f'{status} {body.get("reason")}: {body.get("detail", "")}')
        self.status = status
        self.body = body
        self.reason = body.get('reason', '')
        self.sender = sender


class NetNode:
    def __init__(self, cfg: NetConfig, own_name: str, signer: httpsig.Signer, trust: httpsig.Trust, kv: KV,
                 connector: PeerConnector, *, clock: Callable[[], float] = time.time,
                 events: Optional[Callable[[str, Dict[str, Any]], None]] = None,
                 ca: Optional[CertificateAuthority] = None, ca_certificate=None,
                 peer_cache: Optional[PeerCache] = None, membership: Optional[MembershipProvider] = None,
                 rng: Optional[random.Random] = None, manual: bool = False,
                 pins: Optional[Callable[[], List[str]]] = None, write_identity: Optional[Callable] = None,
                 runtime_seeds: Optional[Callable[[], List[str]]] = None):
        self.cfg = cfg
        self.net = cfg.name
        self.name = own_name
        self.signer = signer
        self.trust = trust
        self.kv = kv
        self.connector = connector
        self.clock = clock
        self._events = events
        self.ca = ca
        self.ca_certificate = ca_certificate
        self.peer_cache = peer_cache
        self.membership = membership or GossipMembership()
        self.rng = rng or random.Random()
        self.manual = manual
        self.pins = pins or (lambda: [])
        self.write_identity = write_identity
        self.runtime_seeds = runtime_seeds or (lambda: [])
        self.timeout = max(0.05, cfg.gossip.ping_timeout_ms / 1000.0)
        self._lock = threading.RLock()
        self._probe_order: List[str] = []
        self._last_full_sync = 0.0
        self._last_cache_save = 0.0
        self._seq = 0
        self.started = False
        # extension points for the parts built on membership (catalogs, key directory, blocks):
        self.extra_features: List[str] = []                  # features listed besides cfg.features()
        self.digest_sources: Dict[str, Callable[[], Any]] = {}   # digests.<name> of the own record
        self.handlers: Dict[str, Callable[[Any, httpsig.Verified], Dict[str, Any]]] = {}   # endpoint -> handler
        self.observers: List[Callable[[str, Dict[str, Any]], None]] = []   # see every event
        self.mcp_server: Optional[Callable[..., PeerResponse]] = None      # signed requests to the MCP endpoint
        self.catalog: Any = None                                            # the CatalogBook, once attached
        self.tick_hooks: List[Callable[[], None]] = []        # run at the end of every joined tick (key directory, blocks)

    # ── events, status ──────────────────────────────────────────────

    def event(self, kind: str, **data) -> None:
        data.setdefault('net', self.net)
        data.setdefault('instance', self.name)
        for obs in list(self.observers):
            try:
                obs(kind, data)
            except Exception as e:                       # an observer never breaks the protocol
                logger.warning(f'SAJHA Net {self.net}: observer of {kind} failed: {e}', exc_info=True)
        if self._events is not None:
            try:
                self._events(kind, data)
            except Exception as e:                       # never let an observer break the protocol
                logger.debug(f'SAJHA Net event {kind}: {e}')

    def status(self) -> Dict[str, Any]:
        return self.kv.get('status') or {}

    def _set_status(self, **fields) -> Dict[str, Any]:
        return self.kv.update('status', lambda cur: dict(cur or {}, **fields))

    @property
    def features(self) -> List[str]:
        out = self.cfg.features()
        return out + [f for f in self.extra_features if f not in out]

    @property
    def gossiping(self) -> bool:
        return bool(self.membership.gossip)

    # ── own record ──────────────────────────────────────────────────

    def _held_revocation_version(self) -> int:
        rl = self.kv.get('rl')
        return int(rl.get('version') or 0) if isinstance(rl, dict) else 0

    def own_entry(self, state: str = 'alive') -> Dict[str, Any]:
        cur = self.kv.get('self')
        if not cur:
            raise RuntimeError('the node has not started')
        return {'record': cur['record'], 'signature': cur['signature'],
                'certificate': [crypto.b64(crypto.cert_der(c)) for c in self.signer.chain], 'state': state}

    def _resign(self, incarnation: Optional[int] = None, leaving: bool = False) -> Dict[str, Any]:
        def fn(cur):
            cur = cur or {}
            inc = int(incarnation if incarnation is not None else cur.get('incarnation') or 0)
            seq = 0 if inc != cur.get('incarnation') else int(cur.get('seq', -1)) + 1
            rec = member_record(self.cfg, self.name, inc, seq, revocations=self._held_revocation_version(),
                                leaving=leaving, now=self.clock())
            rec['features'] = self.features
            for k, fn in self.digest_sources.items():
                try:
                    rec['digests'][k] = fn()
                except Exception as e:
                    logger.warning(f'SAJHA Net {self.net}: digest {k}: {e}')
            sig = crypto.sign_record('member', rec, self.signer.key, self.signer.keyid)
            return {'incarnation': inc, 'seq': seq, 'record': rec, 'signature': sig, 'leaving': leaving}
        out = self.kv.update('self', fn)
        self._enqueue(self.name, self.own_entry('left' if leaving else 'alive'), priority=False)
        return out

    def refresh_record(self) -> None:
        """Re-sign the own record (a digest or feature changed); gossip carries it (§9.1 ``seq``)."""
        if self.started:
            self._resign()

    def incarnation(self) -> int:
        return int((self.kv.get('self') or {}).get('incarnation') or 0)

    # ── start, join, leave ──────────────────────────────────────────

    def start(self) -> None:
        """Choose the incarnation (§9.3), register the own name's lineage, load the revocation list."""
        last = None
        if self.peer_cache is not None:
            last = self.peer_cache.load().get('incarnation')
        inc = new_incarnation(int(self.clock() * 1000), last)
        if self.peer_cache is not None:
            self.peer_cache.update(incarnation=inc, net=self.net, name=self.name)
        self._register_lineage(self.name, self.signer.chain[0])
        if self.ca is not None:
            self._accept_revocations(self.ca.revocation_list(), local=True)
        self._resign(incarnation=inc)
        self.started = True
        self._set_status(started_at=self.clock(), joined=False)

    def _fingerprint(self) -> str:
        cfg = {'name': self.net, 'instance': self.name, 'seeds': list(self.cfg.seeds), 'founder': self.cfg.founder,
               'url': self.cfg.base_url}
        return hashlib.sha256((json.dumps(cfg, sort_keys=True) + self.signer.keyid).encode()).hexdigest()[:24]

    def refused(self) -> Optional[Dict[str, Any]]:
        """The ``name_conflict`` refusal that stops this node from joining, while config and certificate
        are unchanged (protocol §5.2, NAME-07)."""
        r = (self.peer_cache.load().get('refused') if self.peer_cache is not None else None) or \
            self.status().get('refused')
        if r and r.get('fingerprint') == self._fingerprint():
            return r
        return None

    def _refuse(self, err: PeerRefused) -> None:
        body = err.body
        r = {'fingerprint': self._fingerprint(), 'at': crypto.rfc3339(self.clock()), 'by': err.sender,
             'holder_url': body.get('holder_url'), 'holder_thumbprint': body.get('holder_thumbprint'),
             'holder_state': body.get('holder_state'), 'detail': body.get('detail', '')}
        self._set_status(refused=r, joined=False)
        if self.peer_cache is not None:
            self.peer_cache.update(refused=r)
        logger.error(f'SAJHA Net {self.net}: the name {self.name} is held by another participant '
                     f'({r["holder_url"]}, {r["holder_thumbprint"]}, {r["holder_state"]}); not joining until the '
                     f'configuration or certificate changes')
        self.event('name_conflict', own=True, **{k: v for k, v in r.items() if k != 'fingerprint'})

    def join_sources(self) -> List[Tuple[str, str, str]]:
        """``(kind, url, name)`` in the order §9.7 tries them: seeds, saved peers, discovery."""
        out = [('seed', u.rstrip('/'), httpsig.ANY) for u in self.cfg.seeds if u]
        out += [('runtime_seed', u.rstrip('/'), httpsig.ANY) for u in (self.runtime_seeds() or [])
                if u and u.rstrip('/') not in self.cfg.seeds]
        if self.peer_cache is not None:
            for m in saved_peers_to_try(self.peer_cache.load(), self.clock(), self.cfg.peer_cache.max_age_days):
                if m['name'] != self.name:
                    out.append(('saved', m['url'].rstrip('/'), m['name']))
        for u in (self.membership.peers(self.cfg) or []) + (self.membership.discover(self.cfg) or []):
            out.append(('discovery', u.rstrip('/'), httpsig.ANY))
        return out

    def try_join(self) -> bool:
        """One join attempt (§9.7). True when joined."""
        if self.refused():
            return False
        # A net with no seeds is a net of one (owner decision; protocol §9.7): this participant is its
        # founder and only member until a peer contacts it, is added by address, or is learnt otherwise.
        alone_ok = self.cfg.founder or not self.cfg.seeds
        tried = []
        for kind, url, name in self.join_sources():
            try:
                self.sync(url, name, reason='join')
                self._set_status(joined=True, joined_at=self.clock(), joined_via=url, backoff=0, next_join_at=0,
                                 config_error=None)
                self.event('joined', via=url, source=kind)
                self._mark_dirty()
                return True
            except PeerRefused as e:
                if e.reason == 'name_conflict':
                    self._refuse(e)
                    return False
                tried.append(f'{url}: {e.reason}')
            except (PeerUnreachable, NetError) as e:
                tried.append(f'{url}: {getattr(e, "reason", "") or e}')
        if alone_ok:
            self._set_status(joined=True, founder_alone=True, single_member=not self.cfg.seeds,
                             config_error=None, backoff=0, next_join_at=0)
            return True
        st = self.status()
        backoff = min(300.0, max(5.0, float(st.get('backoff') or 0) * 2 or 5.0))
        self._set_status(joined=False, backoff=backoff, next_join_at=self.clock() + backoff, last_errors=tried[-5:])
        why = 'no seed or saved peer reachable' if tried else 'nothing to contact'
        self.event('not_joined', detail=f'not joined to {self.net}: {why}', tried=tried[-5:])
        return False

    def joined(self) -> bool:
        return bool(self.status().get('joined'))

    def leave(self) -> int:
        """§9.8: re-sign with ``leaving: true`` and tell at least three members. Returns how many answered."""
        if not self.started:
            return 0
        self._resign(leaving=True)
        entry = self.own_entry('left')
        targets = [m for m in self.members() if m['state'] in ('alive', 'suspect')]
        self.rng.shuffle(targets)
        n = 0
        for m in targets:                                  # at least three; all of them when fewer
            try:
                self.request(m['record']['url'], P + '/membership/leave', {'type': 'leave', 'entry': entry},
                             m['name'])
                n += 1
            except (PeerUnreachable, PeerRefused, NetError):
                pass
        self.event('left', told=n)
        self.save_peers(force=True)
        return n

    # ── the member table ────────────────────────────────────────────

    def members(self) -> List[Dict[str, Any]]:
        return sorted((dict(v, name=k[2:]) for k, v in self.kv.scan('m:')), key=lambda m: m['name'])

    def member(self, name: str) -> Optional[Dict[str, Any]]:
        v = self.kv.get('m:' + name)
        return dict(v, name=name) if v else None

    def _entry_of(self, m: Dict[str, Any], with_cert: bool = True) -> Dict[str, Any]:
        e = {'record': m['record'], 'signature': m['signature'], 'state': m['state']}
        if with_cert and m.get('certificate'):
            e['certificate'] = m['certificate']
        if m.get('reported_by'):
            e['reported_by'] = m['reported_by']
        if m.get('reported_at'):
            e['reported_at'] = m['reported_at']
        return e

    def _register_lineage(self, name: str, cert) -> None:
        serial, th = crypto.serial_hex(cert), crypto.thumbprint(crypto.cert_der(cert))

        def fn(cur):
            if cur and serial in cur.get('serials', []):
                return cur
            cur = cur or {'serials': [], 'thumbprints': [], 'first_seen': self.clock()}
            return dict(cur, serials=(cur['serials'] + [serial])[-50:],
                        thumbprints=(cur.get('thumbprints', []) + [th])[-50:], current=th)
        self.kv.update('names:' + name, fn)

    def lineage_conflict(self, name: str, cert) -> Optional[Dict[str, Any]]:
        """The holder (for the 409 body) when ``cert`` claims ``name`` outside its holder's lineage and the
        holder's certificates are not all revoked (§5.2); None when ``cert`` may hold the name."""
        reg = self.kv.get('names:' + name)
        if not reg:
            return None
        serial, th = crypto.serial_hex(cert), crypto.thumbprint(crypto.cert_der(cert))
        if serial in reg.get('serials', []) or th in reg.get('thumbprints', []):
            return None
        renews = crypto.renews_of(cert)
        if renews and renews in reg.get('serials', []) and not self.manual:
            return None
        rl = self.kv.get('rl')
        if not self.manual and reg.get('serials') and all(
                revocation_reason(rl, s, '') == 'certificate_revoked' for s in reg['serials']):
            return None
        held = self.member(name)
        return {'holder_url': (held or {}).get('record', {}).get('url') or reg.get('url') or '',
                'holder_thumbprint': reg.get('current') or (reg.get('thumbprints') or [''])[-1],
                'holder_state': (held or {}).get('state') or 'unknown'}

    def _accept_lineage(self, name: str, cert, url: str = '') -> None:
        reg = self.kv.get('names:' + name)
        th = crypto.thumbprint(crypto.cert_der(cert))
        if reg and crypto.serial_hex(cert) not in reg.get('serials', []) and th not in reg.get('thumbprints', []):
            renews = crypto.renews_of(cert)
            if not renews or renews not in reg.get('serials', []):
                self.kv.delete('names:' + name)          # every certificate of the old lineage is revoked
        self._register_lineage(name, cert)
        if url:
            self.kv.update('names:' + name, lambda cur: dict(cur or {}, url=url))

    def _verify_entry(self, entry: Dict[str, Any], via_net: str):
        """§9.4 rule 1 and §9.1: returns the leaf certificate, or raises NetError."""
        if not schemas.is_valid('member_entry', entry):
            raise NetError('invalid_request', 'a member entry fails its schema')
        rec, sig = entry['record'], entry['signature']
        if rec.get('net') != via_net or via_net != self.net:
            raise NetError('net_mismatch', 'a member record of another net')
        chain_b64 = entry.get('certificate') or self.kv.get('cert:' + sig.get('keyid', ''))
        if not chain_b64:
            raise NetError('certificate_invalid', 'no certificate for the record')
        chain = crypto.chain_from_b64(chain_b64)
        try:
            self.trust.check_chain(chain, self.clock())
        except crypto.CryptoError as e:
            raise NetError('certificate_invalid', e.detail)
        o, cn = crypto.subject_of(chain[0])
        if o != self.net:
            raise NetError('net_mismatch', 'the certificate names another net')
        why = self.trust.revocation(crypto.serial_hex(chain[0]), cn or '')
        if why or revocation_reason(self.kv.get('rl'), '', rec['name']):
            raise NetError(why or 'instance_revoked', 'revoked')
        if cn != rec['name']:
            raise NetError('signature_invalid', 'the record is not signed by its subject')
        if not crypto.host_in_san(chain[0], urlsplit(rec['url']).hostname or ''):
            raise NetError('signature_invalid', 'the record url host is not in the subject certificate')
        if sig.get('keyid') != crypto.thumbprint(crypto.cert_der(chain[0])):
            raise NetError('signature_invalid', 'keyid is not the certificate thumbprint')
        if not crypto.verify_record('member', rec, sig, chain[0].public_key()):
            raise NetError('signature_invalid', 'the member record signature does not verify')
        self.kv.set('cert:' + sig['keyid'], [crypto.b64(crypto.cert_der(c)) for c in chain],
                    ttl=self.cfg.gossip.dead_retention_minutes * 60 + 3600)
        return chain[0]

    def merge(self, entry: Dict[str, Any], via_net: Optional[str] = None, sender: str = '') -> bool:
        """Apply §9.4 to one incoming entry. True when the held view changed."""
        via_net = via_net or self.net
        rec = entry.get('record') or {}
        name = rec.get('name')
        if name == self.name:
            return self._about_self(entry, via_net)
        try:
            cert = self._verify_entry(entry, via_net)
        except (NetError, crypto.CryptoError) as e:
            logger.debug(f'SAJHA Net {self.net}: dropped an entry about {name}: {getattr(e, "detail", e)}')
            return False
        holder = self.lineage_conflict(name, cert)
        if holder is not None:
            self.event('name_conflict_seen', claimant=name, claimant_url=rec.get('url'),
                       claimant_thumbprint=crypto.thumbprint(crypto.cert_der(cert)), **holder)
            return False
        if entry.get('state') == 'left' and not rec.get('leaving'):
            entry = dict(entry, state='alive')                 # §9.2: left needs the subject's own leaving record
        changed = {}

        def fn(cur):
            held = {'record': cur['record'], 'state': cur['state']} if cur else None
            action, new_rec, new_state = decide_merge(held, entry)
            if action == KEEP:
                raise _NoChange()
            out = dict(cur or {})
            now = self.clock()
            if new_rec is not (cur or {}).get('record'):
                out['record'] = new_rec
                out['signature'] = entry['signature'] if new_rec is entry['record'] else cur['signature']
                out['certificate'] = entry.get('certificate') or (cur or {}).get('certificate') or \
                    self.kv.get('cert:' + entry['signature']['keyid'])
            if not cur or new_state != cur.get('state'):
                out['since'] = now
                if new_state in ('suspect', 'dead'):
                    out['reported_by'] = entry.get('reported_by') or sender
                    out['reported_at'] = entry.get('reported_at') or crypto.rfc3339(now)
                else:
                    out.pop('reported_by', None)
                    out.pop('reported_at', None)
            out['state'] = new_state
            out.setdefault('last_seen', now if new_state == 'alive' else 0)
            changed['old'] = (cur or {}).get('state')
            changed['new'] = new_state
            return out
        try:
            new = self.kv.update('m:' + name, fn)
        except _NoChange:
            return False
        self._accept_lineage(name, cert, (new or {}).get('record', {}).get('url', ''))
        self._after_change(name, new, changed.get('old'))
        return True

    def _after_change(self, name: str, m: Dict[str, Any], old_state: Optional[str]) -> None:
        prio = False
        try:
            prio = int(m['record']['digests'].get('revocations', 0)) > self._held_revocation_version()
        except Exception:
            pass
        self._enqueue(name, self._entry_of(m), priority=prio)
        self._mark_dirty()
        if old_state != m['state']:
            self.event('member_state', member=name, state=m['state'], previous=old_state,
                       url=m['record'].get('url'))

    def _about_self(self, entry: Dict[str, Any], via_net: str) -> bool:
        """§9.4 rule 6: refute suspect or dead at the current incarnation; ignore older claims."""
        rec = entry.get('record') or {}
        if via_net != self.net or rec.get('net') != self.net:
            return False
        keyid = (entry.get('signature') or {}).get('keyid')
        if keyid and keyid != self.signer.keyid and entry.get('certificate'):
            try:
                chain = crypto.chain_from_b64(entry['certificate'])
                if self.lineage_conflict(self.name, chain[0]) is not None:
                    self.event('name_conflict_seen', claimant=self.name, claimant_url=rec.get('url'),
                               claimant_thumbprint=crypto.thumbprint(crypto.cert_der(chain[0])),
                               holder_url=self.cfg.base_url, holder_thumbprint=self.signer.keyid,
                               holder_state='alive')
            except crypto.CryptoError:
                pass
            return False
        if entry.get('state') in ('suspect', 'dead') and int(rec.get('incarnation') or 0) >= self.incarnation():
            inc = new_incarnation(int(self.clock() * 1000), self.incarnation())
            self._resign(incarnation=inc)
            if self.peer_cache is not None:
                self.peer_cache.update(incarnation=inc)
            logger.info(f'SAJHA Net {self.net}: refuted {entry.get("state")} with incarnation {inc}')
            return True
        return False

    def _set_state(self, name: str, state: str) -> None:
        old = {}

        def fn(cur):
            if not cur or cur['state'] == state:
                raise _NoChange()
            old['s'] = cur['state']
            return dict(cur, state=state, since=self.clock(), reported_by=self.name,
                        reported_at=crypto.rfc3339(self.clock()))
        try:
            m = self.kv.update('m:' + name, fn)
        except _NoChange:
            return
        self._after_change(name, m, old.get('s'))

    def _remove(self, name: str, why: str) -> None:
        if self.kv.delete('m:' + name):
            self.kv.delete('dq:' + name)
            self._mark_dirty()
            self.event('member_removed', member=name, reason=why)

    # ── dissemination (§9.6) ────────────────────────────────────────

    def _enqueue(self, name: str, entry: Dict[str, Any], priority: bool) -> None:
        self.kv.set('dq:' + name, {'entry': entry, 'sent': 0, 'priority': bool(priority)})

    def take_updates(self, limit: int = MAX_UPDATES - 1, about: Optional[str] = None) -> List[Dict[str, Any]]:
        n = len(self.members()) + 1
        cap = dissemination_limit(n, self.cfg.gossip.dissemination_factor)
        queued = [(k[3:], v) for k, v in self.kv.scan('dq:') if k[3:] != self.name]
        queued.sort(key=lambda kv: (not kv[1].get('priority'), kv[1].get('sent', 0)))
        out = []
        for name, v in queued[:limit]:
            out.append(v['entry'])
            sent = int(v.get('sent', 0)) + 1
            if sent >= cap:
                self.kv.delete('dq:' + name)
            else:
                self.kv.update('dq:' + name, lambda cur, s=sent: dict(cur, sent=s) if cur else None)
        if about and about != self.name and not any(e['record']['name'] == about for e in out):
            m = self.member(about)
            if m and m['state'] in ('suspect', 'dead'):
                out.append(self._entry_of(m))           # tell a suspect or dead member, so it can refute
        return [self.own_entry()] + out[:limit]

    # ── outbound requests ───────────────────────────────────────────

    def request(self, base_url: str, path: str, body: Optional[Dict[str, Any]], to: str,
                method: str = 'POST', timeout: Optional[float] = None) -> Exchange:
        """Send a signed request and verify the signed response (§8.5, §8.8). Raises
        :class:`PeerUnreachable` (also for a response that fails verification, §8.8), or
        :class:`PeerRefused` for a verified refusal."""
        raw = dumps(body) if method != 'GET' else b''
        headers = httpsig.sign_request(self.signer, method, path, '', {'content-type': 'application/json'}
                                       if method != 'GET' else {}, raw, self.net, self.name, to, now=self.clock())
        req_sig = httpsig.request_signature_bytes(headers)
        url = base_url.rstrip('/') + path
        r = self.connector.send(method, url, headers, raw, timeout or max(self.timeout * 4, 2.0))
        if r.status == 404 and not r.body and 'signature' not in {k.lower() for k in r.headers}:
            raise PeerUnreachable(f'{url}: 404 (not in net {self.net}, or SAJHA Net disabled)')
        try:
            v = httpsig.verify_response(self.trust, self.name, to, r.status, r.headers, r.body, req_sig,
                                        now=self.clock(), max_age=self.cfg.signature_max_age_seconds)
        except NetError as e:
            raise ResponseInvalid(e.reason, f'{url}: response failed verification ({e.detail})')
        holder = self.lineage_conflict(v.sender, v.certificate) if v.sender != self.name else None
        if holder is not None:
            self.event('name_conflict_seen', claimant=v.sender, claimant_url=base_url, claimant_thumbprint=v.keyid,
                       **holder)
            raise ResponseInvalid('name_conflict', f'{url}: {v.sender} answers with a key outside its holder\'s '
                                                   f'lineage')
        try:
            data = json.loads(r.body.decode('utf-8')) if r.body else None
        except ValueError:
            raise PeerUnreachable(f'{url}: response is not JSON')
        if r.status >= 400:
            raise PeerRefused(r.status, data if isinstance(data, dict) else {'reason': 'unknown'}, v.sender)
        return Exchange(r.status, data, v.sender, v)

    def ping(self, m: Dict[str, Any]) -> bool:
        body = {'type': 'ping', 'seq': self._next_seq(), 'updates': self.take_updates(about=m['name'])}
        try:
            x = self.request(m['record']['url'], P + '/gossip/ping', body, m['name'], timeout=self.timeout)
        except (PeerUnreachable, PeerRefused, NetError):
            return False
        if not isinstance(x.body, dict) or x.body.get('type') != 'ack':
            return False
        for e in (x.body.get('updates') or [])[:MAX_UPDATES]:
            self.merge(e, sender=x.sender)
        self._touch(m['name'])
        return True

    def ping_req(self, via: Dict[str, Any], target: str) -> bool:
        body = {'type': 'ping-req', 'seq': self._next_seq(), 'target': target, 'updates': self.take_updates()}
        try:
            x = self.request(via['record']['url'], P + '/gossip/ping-req', body, via['name'],
                             timeout=self.timeout * 2 + 0.5)
        except (PeerUnreachable, PeerRefused, NetError):
            return False
        for e in (x.body.get('updates') or [])[:MAX_UPDATES]:
            self.merge(e, sender=x.sender)
        return bool(x.body.get('reachable')) and x.body.get('target') == target

    def sync(self, base_url: str, to: str, reason: str = 'anti_entropy') -> Exchange:
        members = [self.own_entry()] + [self._entry_of(m) for m in self.members() if m.get('certificate')]
        x = self.request(base_url, P + '/membership/sync', {'type': 'sync', 'reason': reason,
                                                            'members': members[:1024]}, to)
        if not isinstance(x.body, dict) or not schemas.is_valid('sync', x.body):
            raise PeerUnreachable(f'{base_url}: the sync response fails its schema')
        for e in x.body.get('members') or []:
            self.merge(e, sender=x.sender)
        self._touch(x.sender)
        self._check_revocations()
        return x

    def _mark_dirty(self) -> None:
        """The membership changed: the gossip agent saves the peer list at its next tick (any worker
        may have made the change, so the flag lives in the store)."""
        self.kv.set('peers_dirty', True)

    def _touch(self, name: str) -> None:
        def fn(cur):
            if not cur:
                raise _NoChange()
            return dict(cur, last_seen=self.clock())
        try:
            self.kv.update('m:' + name, fn)
        except _NoChange:
            pass

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    # ── the protocol period ─────────────────────────────────────────

    def _alive_or_suspect(self) -> List[Dict[str, Any]]:
        return [m for m in self.members() if m['state'] in ('alive', 'suspect')]

    def _next_target(self) -> Optional[Dict[str, Any]]:
        live = {m['name']: m for m in self._alive_or_suspect()}
        self._probe_order = [n for n in self._probe_order if n in live]
        if not self._probe_order:
            self._probe_order = list(live)
            self.rng.shuffle(self._probe_order)
        while self._probe_order:
            n = self._probe_order.pop(0)
            if n in live:
                return live[n]
        return None

    def probe(self, m: Dict[str, Any]) -> bool:
        """§9.5: direct ping, then ping-req through ``indirect_probes`` others; suspect on no answer."""
        if self.ping(m):
            return True
        others = [o for o in self._alive_or_suspect() if o['name'] != m['name']]
        self.rng.shuffle(others)
        for via in others[:max(0, self.cfg.gossip.indirect_probes)]:
            if self.ping_req(via, m['name']):
                return True
        if m['state'] == 'alive':
            self._set_state(m['name'], 'suspect')
            logger.info(f'SAJHA Net {self.net}: {m["name"]} is suspect (no direct or indirect ack)')
        return False

    def tick(self) -> None:
        """One protocol period of the gossip agent (run by one worker per instance and net)."""
        if not self.started:
            self.start()
        if self.refused():
            return
        st = self.status()
        if not st.get('joined'):
            if self.clock() >= float(st.get('next_join_at') or 0):
                self.try_join()
            if not self.joined():
                return
        now = self.clock()
        g = self.cfg.gossip
        if self.gossiping:
            target = self._next_target()
            if target is not None:
                self.probe(target)
        elif now - self._last_full_sync >= g.full_sync_interval_seconds:
            for url in self.membership.peers(self.cfg):
                try:
                    self.sync(url, httpsig.ANY, reason='anti_entropy')
                except (PeerUnreachable, PeerRefused, NetError):
                    pass
        for m in self.members():
            age = now - float(m.get('since') or now)
            if m['state'] == 'suspect' and age >= g.suspect_timeout_seconds:
                self._set_state(m['name'], 'dead')
                logger.warning(f'SAJHA Net {self.net}: {m["name"]} is dead (suspect for {int(age)} s)')
            elif m['state'] in ('dead', 'left') and age >= g.dead_retention_minutes * 60:
                self._remove(m['name'], 'retention ended')
            elif m['state'] == 'dead' and now - float(m.get('last_probe') or 0) >= g.dead_probe_interval_seconds:
                self.kv.update('m:' + m['name'], lambda cur: dict(cur, last_probe=now) if cur else None)
                self.ping(m)
        if self.gossiping and now - self._last_full_sync >= g.full_sync_interval_seconds:
            live = self._alive_or_suspect()
            if live:
                m = self.rng.choice(live)
                try:
                    self.sync(m['record']['url'], m['name'], reason='anti_entropy')
                except (PeerUnreachable, PeerRefused, NetError):
                    pass
        if now - self._last_full_sync >= g.full_sync_interval_seconds:
            self._last_full_sync = now
        self._check_revocations()
        self._check_certificate()
        self.save_peers()
        for hook in list(self.tick_hooks):
            try:
                hook()
            except Exception as e:                       # one part failing never stops the gossip agent
                logger.warning(f'SAJHA Net {self.net}: tick hook failed: {e}', exc_info=True)

    # ── revocation list (§13) ───────────────────────────────────────

    def revocation_list(self) -> Optional[Dict[str, Any]]:
        return self.kv.get('rl')

    def _accept_revocations(self, doc: Any, local: bool = False) -> bool:
        if self.manual or not verify_revocation_list(doc, self.ca_certificate, self.net):
            return False
        if int(doc['version']) <= self._held_revocation_version() and self.kv.get('rl') is not None:
            return False
        self.kv.set('rl', doc)
        self.kv.set('rl_at', self.clock())
        for m in self.members():
            serial = ''
            try:
                if m.get('certificate'):
                    serial = crypto.serial_hex(crypto.chain_from_b64(m['certificate'])[0])
            except crypto.CryptoError:
                pass
            if revocation_reason(doc, serial, m['name']):
                self._remove(m['name'], 'revoked')
        if self.started:
            self._resign()
        self.event('revocations_updated', version=int(doc['version']), local=local)
        return True

    def accept_revocations(self, doc: Any) -> bool:
        return self._accept_revocations(doc)

    def _check_revocations(self) -> None:
        if self.manual:
            return
        mine = self._held_revocation_version()
        behind = False
        for m in self.members():
            if m['state'] not in ('alive', 'suspect'):
                continue
            try:
                theirs = int(m['record']['digests'].get('revocations') or 0)
            except Exception:
                continue
            if theirs > mine:
                try:
                    x = self.request(m['record']['url'], P + '/revocations', None, m['name'], method='GET')
                    if self._accept_revocations(x.body):
                        mine = self._held_revocation_version()
                except (PeerUnreachable, PeerRefused, NetError):
                    pass
                behind = behind or theirs > mine
        if behind:
            since = self.kv.get('rl_behind_since')
            if since is None:
                self.kv.set('rl_behind_since', self.clock())
            elif self.clock() - float(since) >= REVOCATIONS_STALE_SECONDS:
                self.event('revocations_stale', detail=f'a member holds a newer revocation list of {self.net} '
                                                       f'than this server (version {mine}) and it could not be fetched')
        else:
            self.kv.delete('rl_behind_since')

    # ── certificate expiry and renewal (§14.2) ──────────────────────

    def _check_certificate(self) -> None:
        if self.manual:
            return
        leaf = self.signer.chain[0]
        start, end = leaf.not_valid_before_utc.timestamp(), leaf.not_valid_after_utc.timestamp()
        now = self.clock()
        if now >= end - (end - start) / 3.0:
            self.event('certificate_expiring', not_after=crypto.rfc3339(end), expired=now >= end)
            st = self.status()
            if now >= float(st.get('next_renew_at') or 0):
                try:
                    self.renew()
                except Exception as e:
                    b = min(3600.0, max(60.0, float(st.get('renew_backoff') or 0) * 2 or 60.0))
                    self._set_status(renew_backoff=b, next_renew_at=now + b)
                    self.event('renewal_failed', detail=str(e)[:300])

    def renew(self, ca_url: Optional[str] = None, ca_name: Optional[str] = None,
              alg: str = crypto.ED25519) -> Any:
        """Renew this node's certificate with a new key pair at the CA participant (§14.2)."""
        key = crypto.generate_key(alg)
        host = urlsplit(self.cfg.base_url).hostname or ''
        csr = crypto.make_csr(key, self.net, self.name, host)
        if self.ca is not None and ca_url is None:
            _resp, cert = self.ca.renew(self.signer.chain[0], {'csr': crypto.b64(csr)})
        else:
            if ca_url is None:
                cas = [m for m in self._alive_or_suspect() if 'ca' in (m['record'].get('features') or [])]
                if not cas:
                    raise RuntimeError(f'no CA participant is known in {self.net}')
                ca_url, ca_name = cas[0]['record']['url'], cas[0]['name']
            x = self.request(ca_url, P + '/ca/renew', {'csr': crypto.b64(csr)}, ca_name or httpsig.ANY)
            schemas.validate('enroll_response', x.body)
            cert = crypto.chain_from_b64(x.body['certificate'])[0]
        if crypto.subject_of(cert) != (self.net, self.name) or \
                crypto.thumbprint(crypto.cert_der(cert)) == self.signer.keyid:
            raise RuntimeError('the CA returned an unexpected certificate')
        self.signer = httpsig.Signer(key, [cert])
        self._register_lineage(self.name, cert)
        if self.write_identity is not None:
            self.write_identity(key, cert)
        self._resign()
        self._set_status(renew_backoff=0, next_renew_at=0)
        self.event('renewed', serial=crypto.serial_hex(cert), not_after=crypto.rfc3339(
            cert.not_valid_after_utc.timestamp()))
        return cert

    # ── the saved peer list (§9.9) ──────────────────────────────────

    def save_peers(self, force: bool = False) -> bool:
        if self.peer_cache is None:
            return False
        now = self.clock()
        interval = self.cfg.peer_cache.interval_minutes * 60
        if not (force or self.kv.get('peers_dirty') or now - self._last_cache_save >= interval):
            return False
        out = []
        for m in self.members():
            th = ''
            if m.get('certificate'):
                try:
                    th = crypto.thumbprint(crypto.unb64(m['certificate'][0]))
                except Exception:
                    th = ''
            out.append({'name': m['name'], 'url': m['record']['url'], 'thumbprint': th, 'state': m['state'],
                        'last_seen': float(m.get('last_seen') or 0)})
        self.peer_cache.update(net=self.net, name=self.name, saved_at=now, incarnation=self.incarnation(),
                               members=out)
        self._last_cache_save = now
        self.kv.delete('peers_dirty')
        return True

    # ── inbound: the endpoints ──────────────────────────────────────

    def _respond(self, status: int, body: Optional[Dict[str, Any]], req_headers: Dict[str, str],
                 to: str, extra: Optional[Dict[str, str]] = None, bound: bool = True) -> PeerResponse:
        raw = dumps(body) if body is not None else b''
        h = {'content-type': 'application/problem+json' if status >= 400 else 'application/json'} if raw else {}
        h.update(extra or {})
        req_sig = None
        if bound:
            try:
                req_sig = httpsig.request_signature_bytes(req_headers)
            except Exception:
                req_sig = None
        out = httpsig.sign_response(self.signer, status, h, raw, req_sig, self.net, self.name, to or httpsig.ANY,
                                    now=self.clock())
        out['cache-control'] = 'no-store'
        return PeerResponse(status, out, raw)

    def _problem(self, err: NetError, req_headers: Dict[str, str], to: str, bound: bool = True) -> PeerResponse:
        extra = {}
        if err.status in (429, 503):
            extra['retry-after'] = str(int(err.extra.pop('retry_after', 30) or 30))
        return self._respond(err.status, problem_from(err), req_headers, to, extra, bound=bound)

    def handle(self, method: str, path: str, query: str, headers: Dict[str, str], body: bytes,
               secure: bool = True, source: str = '') -> PeerResponse:
        h = httpsig.lower_headers(headers)
        route = ROUTES.get(path)
        if route is None:
            return empty_404()
        want, feature, schema, limit, signed = route
        if feature is not None and feature not in self.features:
            return empty_404()
        claimed = h.get('sajha-net-from', '').strip()
        if method.upper() != want:
            return self._respond(405, problem('invalid_request', f'use {want}', status=405), h, claimed,
                                 {'allow': want})
        if sum(len(k) + len(v) for k, v in h.items()) > MAX_HEADERS or (limit and len(body or b'') > limit):
            return self._problem(NetError('too_large', 'the request exceeds the protocol limits'), h, claimed)
        if want == 'POST' and h.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            return self._respond(415, problem('invalid_request', 'the body must be application/json', status=415),
                                 h, claimed)
        if not signed:
            return self._enroll(h, body, secure, source)
        try:
            v = httpsig.verify_request(
                self.trust, self.name, method, path, query, h, body, now=self.clock(),
                max_age=self.cfg.signature_max_age_seconds, seen_nonce=self._seen_nonce,
                allow_any_recipient=path == P + '/membership/sync')
        except NetError as e:
            if e.reason == 'name_conflict':
                e.extra.update(holder_url=self.cfg.base_url, holder_thumbprint=self.signer.keyid,
                               holder_state='alive')
            return self._problem(e, h, claimed)
        holder = self.lineage_conflict(v.sender, v.certificate)
        if holder is not None:
            logger.warning(f'SAJHA Net {self.net}: refused {v.sender} from a key outside its holder\'s lineage '
                           f'({holder["holder_url"]})')
            self.event('name_conflict_seen', claimant=v.sender, claimant_thumbprint=v.keyid, **holder)
            return self._problem(NetError('name_conflict', f'the name {v.sender} is held by another key', **holder),
                                 h, v.sender)
        data: Any = None
        if want == 'POST':
            try:
                data = json.loads((body or b'{}').decode('utf-8'))
            except ValueError:
                return self._problem(NetError('invalid_request', 'the body is not JSON'), h, v.sender)
            if schema:
                errs = schemas.errors(schema, data)
                if errs:
                    return self._problem(NetError('invalid_request', errs[0]), h, v.sender)
        try:
            out = self._dispatch(path, data, v)
        except NetError as e:
            return self._problem(e, h, v.sender)
        except PeerUnreachable as e:
            return self._problem(NetError('unavailable', str(e)[:200], retry_after=5), h, v.sender)
        return self._respond(200, out, h, v.sender)

    def _seen_nonce(self, keyid: str, nonce: str, ttl: float) -> bool:
        return not self.kv.add(f'nonce:{keyid}:{nonce}', 1, ttl=ttl)

    def _dispatch(self, path: str, data: Any, v: httpsig.Verified) -> Dict[str, Any]:
        if path == P + '/gossip/ping':
            for e in data['updates'][:MAX_UPDATES]:
                self.merge(e, sender=v.sender)
            self._touch(v.sender)
            return {'type': 'ack', 'seq': data['seq'], 'updates': self.take_updates(about=v.sender)}
        if path == P + '/gossip/ping-req':
            for e in data['updates'][:MAX_UPDATES]:
                self.merge(e, sender=v.sender)
            target = self.member(data['target'])
            if target is None or data['target'] == self.name:
                raise NetError('unknown_member', 'the target is not a member this participant holds')
            ok = self.ping(target)
            return {'type': 'ack', 'seq': data['seq'], 'target': data['target'], 'reachable': ok,
                    'updates': self.take_updates()}
        if path == P + '/membership/sync':
            for e in data['members'][:1024]:
                self.merge(e, sender=v.sender)
            self._touch(v.sender)
            members = [self.own_entry()] + [self._entry_of(m) for m in self.members() if m.get('certificate')]
            return {'type': 'sync', 'reason': data.get('reason', 'anti_entropy'), 'members': members[:1024]}
        if path == P + '/membership/leave':
            entry = data['entry']
            if entry['record'].get('name') != v.sender or entry['signature'].get('keyid') != v.keyid:
                raise NetError('invalid_request', 'a leave must be signed by the departing participant itself')
            if not self.merge(entry, sender=v.sender) and (self.member(v.sender) or {}).get('state') != 'left':
                raise NetError('invalid_request', 'the leave entry was not accepted')
            return {}
        if path == P + '/revocations':
            rl = self.kv.get('rl')
            if not rl:
                raise NetError('unavailable', 'no revocation list is held', retry_after=60)
            return rl
        if path == P + '/ca/renew':
            if self.ca is None:
                raise NetError('unavailable', 'the CA key is not loaded', retry_after=300)
            resp, _cert = self.ca.renew(v.certificate, data)
            return resp
        handler = self.handlers.get(path)
        if handler is not None:
            return handler(data, v)
        raise NetError('unavailable', 'this endpoint is not served yet', retry_after=3600)

    def _enroll(self, h: Dict[str, str], body: bytes, secure: bool, source: str) -> PeerResponse:
        try:
            data = json.loads((body or b'{}').decode('utf-8'))
        except ValueError:
            data = None
        to = (data or {}).get('instance') if isinstance(data, dict) else ''
        to = to if names.is_instance_name(to) else httpsig.ANY
        if self.ca is None:
            return self._problem(NetError('unavailable', 'the CA key is not loaded', retry_after=300), h, to,
                                 bound=False)
        if not isinstance(data, dict) or schemas.errors('enroll_request', data):
            return self._problem(NetError('enrollment_refused', 'refused'), h, to, bound=False)
        try:
            resp, _cert = self.ca.enroll(data, h.get('sajha-net-name', ''), source=source, secure=secure,
                                         allow_plain_http=not self.cfg.require_https)
        except NetError as e:
            if e.reason == 'enrollment_refused':
                logger.warning(f'SAJHA Net CA {self.net}: enrollment of {to} refused: {e.detail}')
                e = NetError('enrollment_refused', 'refused')        # one reason, no oracle (§14.1)
            return self._problem(e, h, to, bound=False)
        return self._respond(200, resp, h, to, bound=False)


class _NoChange(Exception):
    pass


class Participant:
    """Every net of one server on its one port: selects the node by ``Sajha-Net-Name`` (§7.7)."""

    def __init__(self, nodes: Optional[Dict[str, NetNode]] = None, enabled: bool = True):
        self.nodes: Dict[str, NetNode] = dict(nodes or {})
        self.enabled = enabled

    def handle(self, method: str, path: str, query: str, headers: Dict[str, str], body: bytes,
               secure: bool = True, source: str = '') -> PeerResponse:
        h = httpsig.lower_headers(headers)
        if not self.enabled or not path.startswith('/sajhanet/'):
            return empty_404()
        if h.get('sec-fetch-mode', '').strip().lower() == 'navigate':
            return empty_404()
        net = h.get('sajha-net-name', '').strip()
        node = self.nodes.get(net) if names.is_net_name(net) else None
        if node is None or not node.started:
            return empty_404()
        return node.handle(method, path, query, h, body, secure=secure, source=source)

    def handle_mcp(self, method: str, path: str, query: str, headers: Dict[str, str], body: bytes,
                   secure: bool = True, source: str = '') -> Optional[PeerResponse]:
        """A request to the MCP endpoint carrying ``Sajha-Net-*`` headers (protocol §15): the node of
        its net serves it; None when SAJHA Net is off or the net is not one of this participant's,
        in which case the caller answers an unsigned 404 (§7.7)."""
        h = httpsig.lower_headers(headers)
        if not self.enabled:
            return None
        net = h.get('sajha-net-name', '').strip()
        node = self.nodes.get(net) if names.is_net_name(net) else None
        if node is None or not node.started or node.mcp_server is None:
            return None
        return node.mcp_server(method, path, query, h, body, secure=secure, source=source)

    def extension(self, net: Optional[str] = None) -> Dict[str, Any]:
        """The ``io.sajha/net`` capability object (§6.1): reduced unless ``net`` names a net of this
        participant (a request signed for that net)."""
        out: Dict[str, Any] = {'protocol_versions': list(SUPPORTED_VERSIONS), 'endpoint': ENDPOINT}
        node = self.nodes.get(net or '')
        if node is not None:
            out.update(net=node.net, instance=node.name, kind=node.cfg.kind, features=node.features,
                       user_identity=list(node.cfg.user_identity),
                       signature_algorithms=[crypto.ED25519, crypto.P256])
        return out
