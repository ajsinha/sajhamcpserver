"""
Sponsored MCP servers (design §5.1, kind ``sponsored``): a plain MCP server that knows nothing of
SAJHA Net, connected to this server as a federation upstream, represented in a net under an
instance name of its own.

* The sponsor runs a node for it (:class:`sajha.net.node.NetNode`, ``kind: sponsored``, ``sponsor``:
  this server's name in the net) on its own URL; requests reach that node by ``Sajha-Net-To``
  (:class:`sajha.net.node.Participant`). Its key and certificate are the sponsor's to hold
  (``<sajhanet.data_dir>/<net>/sponsored/<instance>/``): self-signed under ``admission: open`` or
  manual mode, issued by this server's CA when it is the CA participant, else by enrollment
  (``POST /api/sajhanet/sponsored/{net}/{instance}/enroll``).
* Its catalog is the upstream's tools (the federation tools of that upstream in the registry, by
  the upstream's own names, filtered by ``tools`` globs), with the sponsor's data classes; a
  ``rename`` entry offers one under a name of the operator's choosing (protocol §5.5). A sponsored
  server is a member, so it is never external (``external: true`` is refused; an external server is
  ``sajhanet.external_servers``, design §5.6).
* A forwarded call to it is verified and authorized by the sponsor exactly as a call to the sponsor
  (identity, blocks, export rules under the tool's local name, access, policy and approvals,
  residency, audit) and runs through federation's connection to the server.

Configuration: ``sajhanet.sponsored`` (a list), plus the entries added through the admin API (kept
in ``<sajhanet.data_dir>/sponsored.json``). Each entry: ``net``, ``instance_name``, ``upstream``,
``vendor`` (required), ``rename`` (``{upstream tool: published name}``),
``tools`` (globs of the upstream's tool names, default all), ``region`` and ``labels`` (default the
sponsor's).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import copy
import fnmatch
import logging
import os
import threading
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from sajha.net import crypto, httpsig, names, plugins
from sajha.net.catalog import CatalogBook
from sajha.net.library import IdentityFiles, enroll as core_enroll, self_signed
from sajha.net.membership import PeerCache
from sajha.net.models import EXTERNAL_KEY, CASettings, IdentitySettings, PeerCacheSettings, PrefixKV
from sajha.net.node import NetNode
from sajha.net.plugins import CatalogSource
from sajha.net.routing import CallContext, HostRefusal, HostServer

logger = logging.getLogger(__name__)


@dataclass
class SponsoredSpec:
    net: str
    instance_name: str
    upstream: str
    tools: List[str] = field(default_factory=lambda: ['*'])
    region: str = ''
    labels: Dict[str, str] = field(default_factory=dict)
    source: str = 'config'                 # config | admin
    vendor: str = ''                       # required: who answers for the server's tools (protocol §5.5)
    rename: Dict[str, str] = field(default_factory=dict)     # upstream tool name -> published name

    @classmethod
    def from_dict(cls, d: Dict[str, Any], source: str = 'config') -> 'SponsoredSpec':
        net = names.net_name_or_default(str(d.get('net') or '') or None)
        name = str(d.get('instance_name') or d.get('instance') or '').strip()
        upstream = str(d.get('upstream') or '').strip()
        if not names.is_net_name(net):
            raise ValueError(f'{net!r} is not a net name')
        if not names.is_configured_name(name):
            raise ValueError(f'{name!r} is not an instance name (protocol §5.2)')
        if not upstream:
            raise ValueError('upstream: the federation upstream id of the server to sponsor')
        tools = d.get('tools') or ['*']
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(',') if t.strip()]
        labels = d.get('labels') if isinstance(d.get('labels'), dict) else {}
        from sajha.core.config import parse_bool
        from sajha.net.integration.config import _rename, naming_problem
        vendor = str(d.get('vendor') or '').strip()
        if not vendor:
            raise ValueError(f'{name}: vendor is required (the organisation that answers for the server\'s tools, '
                             f'e.g. acme; protocol §5.5)')
        if parse_bool(d.get(EXTERNAL_KEY), False):
            raise ValueError(f'{name}: a sponsored server is a member of the net and cannot be external; to offer '
                             f'{upstream}\'s tools under its vendor\'s prefix without making it a member, list it in '
                             f'sajhanet.external_servers ({{upstream: {upstream}, vendor: {vendor}}})')
        rename = _rename(d.get('rename'))
        bad = naming_problem(vendor, rename)
        if bad:
            raise ValueError(f'{name}: {bad}')
        return cls(net=net, instance_name=name, upstream=upstream, tools=[str(t) for t in tools],
                   region=str(d.get('region') or ''), labels={str(k): str(v) for k, v in labels.items()},
                   source=source, vendor=vendor, rename=rename)

    def to_dict(self) -> Dict[str, Any]:
        return {'net': self.net, 'instance_name': self.instance_name, 'upstream': self.upstream,
                'tools': list(self.tools), 'region': self.region, 'labels': dict(self.labels), 'source': self.source,
                'vendor': self.vendor, 'rename': dict(self.rename)}


@dataclass
class Sponsored:
    spec: SponsoredSpec
    node: Optional[NetNode] = None
    book: Optional[CatalogBook] = None
    host: Optional[HostServer] = None
    error: str = ''


def _federated_tools(registry, upstream: str) -> List[Any]:
    if registry is None:
        return []
    try:
        from sajha.federation.tool import FederatedTool
    except Exception:
        return []
    with registry._tools_lock:
        items = list(registry.tools.values())
    return [t for t in items if isinstance(t, FederatedTool) and t.upstream_id == upstream and t.enabled]


class SponsoredCatalog(CatalogSource):
    """The sponsored server's tools, by the server's own names, with the sponsor's data classes."""
    name = 'sponsored'

    def __init__(self, sponsors: 'Sponsorships', spec: SponsoredSpec):
        self.sponsors = sponsors
        self.spec = spec

    def _tools(self) -> List[Tuple[str, Any]]:
        out = []
        for t in _federated_tools(self.sponsors.registry, self.spec.upstream):
            part = str(getattr(t, 'upstream_name', '') or t.name)
            if any(fnmatch.fnmatchcase(part, p) for p in self.spec.tools):
                out.append((part, t))
        return out

    def tool(self, name: str):
        return next((t for part, t in self._tools() if part == name), None)

    def tools(self, net, peer=None):
        out = []
        for part, t in self._tools():
            try:
                d = copy.deepcopy(t.to_mcp_format())
            except Exception as e:
                logger.debug(f'SAJHA Net sponsored {self.spec.instance_name}: {part}: {e}')
                continue
            d['name'] = part
            meta = dict(d.get('_meta') or {})
            meta.pop('sajha/federation', None)
            if meta:
                d['_meta'] = meta
            else:
                d.pop('_meta', None)
            extra: Dict[str, Any] = {'version': str(getattr(t, 'version', '') or '')}
            try:
                from sajha.net.integration.residency import catalog_summary
                dc = catalog_summary(t)
                if dc:
                    extra['data_classes'] = dc
            except Exception as e:
                logger.debug(f'SAJHA Net sponsored residency summary of {part}: {e}')
            d['_net'] = {k: v for k, v in extra.items() if v not in ('', None)}
            out.append(d)
        return out


class _Rules(plugins.RuleEvaluator):
    """The sponsor's rule evaluator, with a sponsored tool named by its local (registry) name in
    export decisions, so the sponsor's export rules govern it as one of its own tools; its published
    and upstream names are in ``tool_names`` (protocol §5.5), so a rule may name it by any of them."""
    name = 'sponsored'

    def __init__(self, inner: plugins.RuleEvaluator, catalog: SponsoredCatalog):
        self.inner = inner
        self.catalog = catalog

    @property
    def version(self):
        return getattr(self.inner, 'version', None)

    def decide(self, rule, subject):
        s = dict(subject or {})
        if rule in ('export', 'block_tool') and s.get('tool'):
            known = [str(n) for n in s.get('tool_names') or []] or [str(s['tool'])]
            t = self.catalog.tool(known[-1])
            if t is not None:
                s['tool_names'] = list(dict.fromkeys(known + [str(s['tool']), t.name]))
                s['tool'] = t.name
        if rule in ('import', 'pull', 'reexport'):
            return plugins.Decision(False, rule)          # a sponsored participant imports nothing
        return self.inner.decide(rule, s)


class _Identity(plugins.IdentityResolver):
    """The sponsor's resolvers, the sponsored participant counting as the call's audience."""
    name = 'sponsored'

    def __init__(self, inner: plugins.IdentityResolver):
        self.inner = inner

    def outbound_headers(self, user):
        return {}

    def resolve(self, headers, sender, **kw):
        kw = dict(kw)
        kw['audience'] = None
        import inspect
        params = inspect.signature(self.inner.resolve).parameters
        if not any(p.kind == p.VAR_KEYWORD for p in params.values()):
            kw = {k: v for k, v in kw.items() if k in params}
        return self.inner.resolve(headers, sender, **kw)


class Sponsorships:
    """Every sponsored participant of one SajhaNetService."""

    def __init__(self, svc):
        self.svc = svc
        self.items: Dict[Tuple[str, str], Sponsored] = {}
        self._lock = threading.RLock()

    @property
    def registry(self):
        cat = getattr(self.svc, 'catalogs', None)
        reg = getattr(self.svc, 'tools_registry', None)
        if reg is not None:
            return reg
        return cat.registry if cat is not None else None

    # ── configuration ──────────────────────────────────────────────

    def _doc(self):
        return self.svc._doc_io(f'{self.svc.shared.data_dir}/sponsored.json')

    def configured(self) -> Tuple[List[SponsoredSpec], List[str]]:
        specs: List[SponsoredSpec] = []
        errors: List[str] = []
        raw = list(getattr(self.svc, 'sponsored_config', None) or [])
        if not raw and getattr(self.svc, 'sponsored_config', None) is None:
            try:
                from sajha.net.integration.config import _raw
                raw = list(_raw().get('sponsored') or [])
            except Exception:
                raw = []
        read, _ = self._doc()
        extra = list((read() or {}).get('items') or [])
        for d, source in [(x, 'config') for x in raw] + [(x, 'admin') for x in extra]:
            try:
                sp = SponsoredSpec.from_dict(d if isinstance(d, dict) else {}, source)
            except ValueError as e:
                errors.append(f'sajhanet.sponsored: {e}')
                continue
            if any(o.net == sp.net and o.instance_name == sp.instance_name for o in specs):
                errors.append(f'sajhanet.sponsored: {sp.net}/{sp.instance_name} is listed twice')
                continue
            specs.append(sp)
        return specs, errors

    # ── building ───────────────────────────────────────────────────

    def build_net(self, net: str) -> None:
        """(Re)build the sponsored participants of ``net`` on top of its running node."""
        with self._lock:
            for key in [k for k in self.items if k[0] == net]:
                self._drop(key)
            rt = self.svc.runtimes.get(net)
            if rt is None or rt.node is None:
                return
            specs, errors = self.configured()
            for e in errors:
                logger.warning(e)
            for sp in specs:
                if sp.net != net:
                    continue
                item = Sponsored(sp)
                self.items[(net, sp.instance_name)] = item
                try:
                    self._build(rt, item)
                except Exception as e:
                    item.error = str(e)
                    logger.warning(f'SAJHA Net {net}: sponsored {sp.instance_name} not started: {e}', exc_info=True)
                if item.error:
                    from sajha.net.integration import _notice
                    _notice(f'sajhanet.sponsored:{net}:{sp.instance_name}', 'warning',
                            f'Sponsored server {sp.instance_name} is not in {net}', item.error, ttl=0)
            main = rt.node
            hook = getattr(main, '_sponsored_hook', None)
            if hook is None:
                def hook(net=net):
                    self.tick(net)
                main._sponsored_hook = hook
                main.tick_hooks.append(hook)

    def _files(self, net: str, name: str) -> IdentityFiles:
        return IdentityFiles(os.path.join(self.svc.shared.data_dir, net, 'sponsored', name))

    def _identity(self, rt, sp: SponsoredSpec):
        """The sponsored participant's key and certificate: held, self-signed, or from this server's CA."""
        files = self._files(sp.net, sp.instance_name)
        held = files.load()
        if held is not None and crypto.subject_of(held[1]) == (sp.net, sp.instance_name):
            return held
        host = urlsplit(rt.cfg.base_url).hostname or ''
        main = rt.node
        if main.manual:                                    # open or manual: self-signed
            key, cert = self_signed(sp.net, sp.instance_name, host, now=self.svc.clock())
        elif rt.ca is not None:                            # this server is the CA participant
            key = crypto.generate_key()
            cert = rt.ca.issue_own(key, sp.instance_name, host)
        else:
            raise RuntimeError(f'no certificate for the sponsored {sp.instance_name}: enroll it with a token from the '
                               f'CA participant (POST /api/sajhanet/sponsored/{sp.net}/{sp.instance_name}/enroll)')
        files.save(key, cert)
        return key, cert

    def _build(self, rt, item: Sponsored) -> None:
        sp = item.spec
        main = rt.node
        if sp.instance_name == main.name:
            raise RuntimeError(f'{sp.instance_name} is this server\'s own name in {sp.net}')
        key, cert = self._identity(rt, sp)
        listed = [i for i in (main.cfg.user_identity or []) if i in ('api_key', 'none')]
        files = self._files(sp.net, sp.instance_name)
        cfg = replace(rt.cfg, instance_name=sp.instance_name, kind='sponsored', sponsor=main.name,
                      vendor=sp.vendor, rename=dict(sp.rename),
                      seeds=[rt.cfg.base_url], founder=False, static_peers=[], identity=IdentitySettings(),
                      ca=CASettings(), peer_cache=PeerCacheSettings(path=files.peers_path),
                      region=sp.region or rt.cfg.region, labels=dict(sp.labels or rt.cfg.labels),
                      user_identity=listed or ['none'])
        kv = PrefixKV(self.svc.store, f'sajhanet:{sp.net}:sponsored:{sp.instance_name}:')
        from sajha.net.integration import on_event
        node = NetNode(cfg, sp.instance_name, httpsig.Signer(key, [cert]), main.trust, kv, self.svc.connector,
                       clock=self.svc.clock, events=on_event, ca_certificate=main.ca_certificate,
                       peer_cache=PeerCache(files.peers_path), membership=main.membership, manual=main.manual,
                       pins=main.pins, write_identity=lambda k, c, files=files: files.save(k, c))
        if main.revocation_list():
            node.accept_revocations(main.revocation_list())
        catalogs = getattr(self.svc, 'catalogs', None)
        if catalogs is None:
            from sajha.net.integration.catalogs import get_net_catalogs
            catalogs = get_net_catalogs(self.svc)
        identity, rules = catalogs._authz_parts()
        source = SponsoredCatalog(self, sp)
        srules = _Rules(rules, source)
        s = catalogs.settings
        book = CatalogBook(node, source, rules=srules, refresh_interval=float(s.for_net(sp.net, 'refresh_interval_seconds')),
                           limits=s.limits).attach()
        if 'residency' in main.extra_features and 'residency' not in node.extra_features:
            node.extra_features.append('residency')
        book.start()

        def execute(ctx: CallContext, arguments: Dict[str, Any], source=source):
            tool = source.tool(ctx.local_tool or ctx.tool)       # §5.5: the upstream's own name
            if tool is None:
                raise HostRefusal('export')
            return catalogs.execute_tool(ctx, arguments, tool, local_name=tool.name)

        def other(msg, v, node=node):
            rid = msg.get('id')
            ext = self._extension(node)
            if msg.get('method') == 'ping':
                return {'jsonrpc': '2.0', 'id': rid, 'result': {}}
            if msg.get('method') == 'initialize':
                return {'jsonrpc': '2.0', 'id': rid, 'result': {
                    'protocolVersion': '2025-11-25', 'serverInfo': {'name': sp.instance_name, 'version': ''},
                    'capabilities': {'tools': {}, 'experimental': {'io.sajha/net': ext}}}}
            if msg.get('method') == 'server/discover':
                return {'jsonrpc': '2.0', 'id': rid, 'result': {
                    'supportedVersions': ['2026-07-28', '2025-11-25'],
                    'capabilities': {'tools': {}, 'extensions': {'io.sajha/net': ext}}}}
            return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601,
                                                          'message': f'{msg.get("method")} is not served to net peers'}}
        host = HostServer(book, execute=execute, identity=_Identity(identity), rules=srules,
                          max_hops=int(s.for_net(sp.net, 'max_hops')), max_chain=s.max_call_chain,
                          own_identities=lambda n=sp.net, nm=sp.instance_name: [f'{n}/{nm}'], other=other,
                          calls_per_minute=s.host_calls_per_minute, audit=catalogs._audit).attach()
        node.start()
        item.node, item.book, item.host, item.error = node, book, host, ''
        self.svc.participant.sponsored.setdefault(sp.net, {})[sp.instance_name] = node

    @staticmethod
    def _extension(node: NetNode) -> Dict[str, Any]:
        return {'protocol_versions': [1], 'net': node.net, 'instance': node.name, 'kind': 'sponsored',
                'sponsor': node.cfg.sponsor, 'endpoint': '/sajhanet/v1/', 'features': node.features,
                'user_identity': list(node.cfg.user_identity),
                'signature_algorithms': [crypto.ED25519, crypto.P256]}

    def _drop(self, key: Tuple[str, str]) -> None:
        item = self.items.pop(key, None)
        nodes = self.svc.participant.sponsored.get(key[0]) or {}
        nodes.pop(key[1], None)
        if item is not None and item.node is not None:
            try:
                item.node.leave()
            except Exception as e:
                logger.debug(f'SAJHA Net sponsored {key}: leave: {e}')

    def tick(self, net: str) -> None:
        for (n, name), item in list(self.items.items()):
            if n != net or item.node is None:
                continue
            try:
                item.node.tick()
            except Exception as e:
                logger.warning(f'SAJHA Net {net}: sponsored {name}: tick failed: {e}', exc_info=True)

    def stop(self) -> None:
        for key in list(self.items):
            self._drop(key)

    # ── views and operations (admin API) ───────────────────────────

    def view(self) -> List[Dict[str, Any]]:
        out = []
        specs, errors = self.configured()
        for sp in specs:
            item = self.items.get((sp.net, sp.instance_name))
            row = sp.to_dict()
            node = item.node if item is not None else None
            row.update(sponsor=(self.svc.runtimes.get(sp.net).node.name
                                if self.svc.runtimes.get(sp.net) and self.svc.runtimes[sp.net].node else ''),
                       kind='sponsored', running=node is not None, error=(item.error if item else 'not built'),
                       joined=bool(node and node.joined()),
                       tools=[t['name'] for t in item.book.exports(None)] if item and item.book else [])
            if node is not None:
                row['certificate'] = crypto.thumbprint(crypto.cert_der(node.signer.chain[0]))
            out.append(row)
        return out

    def add(self, data: Dict[str, Any], by: str = '') -> Dict[str, Any]:
        from sajha.net.integration import ServiceError, _audit
        try:
            sp = SponsoredSpec.from_dict(data, 'admin')
        except ValueError as e:
            raise ServiceError(400, str(e))
        if sp.net not in self.svc.runtimes:
            raise ServiceError(404, f'this server is not configured for net {sp.net!r}')
        specs, _ = self.configured()
        if any(o.net == sp.net and o.instance_name == sp.instance_name for o in specs):
            raise ServiceError(409, f'{sp.net}/{sp.instance_name} is already sponsored')
        read, write = self._doc()
        items = list((read() or {}).get('items') or [])
        items.append({k: v for k, v in sp.to_dict().items() if k != 'source'})
        write({'items': items})
        _audit('sponsored_added', by, sp.to_dict())
        self.build_net(sp.net)
        return next((r for r in self.view() if r['net'] == sp.net and r['instance_name'] == sp.instance_name), {})

    def remove(self, net: str, instance: str, by: str = '') -> bool:
        from sajha.net.integration import ServiceError, _audit
        read, write = self._doc()
        items = list((read() or {}).get('items') or [])
        keep = [x for x in items if not (str(x.get('net')) == net and str(x.get('instance_name')) == instance)]
        if len(keep) == len(items):
            if any(sp.net == net and sp.instance_name == instance for sp in self.configured()[0]):
                raise ServiceError(409, f'{net}/{instance} is in sajhanet.sponsored; remove it from the configuration')
            return False
        write({'items': keep})
        _audit('sponsored_removed', by, {'net': net, 'instance': instance})
        self.build_net(net)
        return True

    def enroll(self, net: str, instance: str, ca_url: str, token: str, by: str = '') -> Dict[str, Any]:
        from sajha.net.integration import ServiceError, _audit
        from sajha.net.library import EnrollmentError
        rt = self.svc.runtimes.get(net)
        if rt is None or rt.node is None:
            raise ServiceError(409, f'net {net} is not running')
        if not any(sp.net == net and sp.instance_name == instance for sp in self.configured()[0]):
            raise ServiceError(404, f'{net}/{instance} is not sponsored here')
        host = urlsplit(rt.cfg.base_url).hostname or ''
        try:
            key, cert, ca_cert = core_enroll(self.svc.connector, net, instance, host, ca_url, token,
                                             require_https=rt.cfg.require_https, ca_certificate=rt.node.ca_certificate,
                                             clock=self.svc.clock, max_age=rt.cfg.signature_max_age_seconds)
        except EnrollmentError as e:
            raise ServiceError(502, str(e))
        self._files(net, instance).save(key, cert)
        _audit('sponsored_enrolled', by, {'net': net, 'instance': instance, 'serial': crypto.serial_hex(cert)})
        self.build_net(net)
        return {'net': net, 'instance': instance, 'serial': crypto.serial_hex(cert)}


def get_sponsorships(svc) -> Sponsorships:
    sp = getattr(svc, 'sponsorships', None)
    if sp is None:
        sp = Sponsorships(svc)
        svc.sponsorships = sp
    return sp
