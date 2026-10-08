"""
SAJHA Net configuration (design §19): ``sajhanet.*`` in config/application.yml.

* Server-wide scalars resolve as every ``_get`` key does (``SAJHA_SAJHANET_<KEY>`` → YAML → default).
* ``sajhanet.nets`` is a list read from the YAML (or ``SAJHA_SAJHANET_NETS`` as a JSON list,
  :func:`sajha.core.net_extension.configured_nets`); an entry without a name is the net ``default``;
  list order is preference order.
* Every key that is not net-only or server-wide-only is a shared default a net entry may override.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sajha.net import names
from sajha.net.models import EXTERNAL_KEY, CASettings, GossipSettings, IdentitySettings, NetConfig, PeerCacheSettings

GOSSIP_KEYS = ('gossip_interval_ms', 'ping_timeout_ms', 'indirect_probes', 'suspect_timeout_seconds',
               'full_sync_interval_seconds', 'dead_retention_minutes', 'dead_probe_interval_seconds')
NET_ONLY = ('name', 'instance_name', 'advertise_address', 'founder', 'seeds', 'identity', 'ca', 'static_peers',
            'export', 'import')


def _ca_auto_default() -> bool:
    """``sajhanet.ca_auto_init`` (default true, owner decision): a net of one creates its CA at first
    start unless its net entry says ``ca.auto_init: false``."""
    from sajha.core.config import _get
    v = _get('sajhanet.ca_auto_init', True)
    return str(v).strip().lower() not in ('false', '0', 'no', 'off') if v is not None else True


def _raw() -> Dict[str, Any]:
    """The ``sajhanet`` section of the YAML as written (lists and maps intact)."""
    path = Path(os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml'))
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {} if path.exists() else {}
    except Exception:
        data = {}
    sec = data.get('sajhanet') if isinstance(data, dict) else None
    return sec if isinstance(sec, dict) else {}


def _g(key: str, default: Any) -> str:
    from sajha.core.config import _get
    v = _get('sajhanet.' + key, None)
    return default if v is None or v == '' else v


def _bool(v: Any, default: bool) -> bool:
    from sajha.core.config import parse_bool
    return parse_bool(v, default)


def _num(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class Shared:
    enabled: bool = False
    base_url: str = ''
    region: str = ''
    labels: Dict[str, str] = field(default_factory=dict)
    signature_max_age_seconds: float = 30
    require_https: bool = True
    min_protocol_version: int = 1
    mtls: str = 'off'
    membership: str = 'gossip'
    admission: str = 'builtin_ca'
    connector: str = 'sajha_native'
    data_dir: str = 'data/sajhanet'
    gossip: GossipSettings = field(default_factory=GossipSettings)
    peer_cache: PeerCacheSettings = field(default_factory=PeerCacheSettings)
    max_injections_per_minute: int = 6
    agent_lease_seconds: float = 15
    plugin_modules: List[str] = field(default_factory=list)     # sajhanet.plugins.modules (third-party plug-ins)
    vendor: str = 'sajha'                    # sajhanet.vendor (protocol §5.5)
    rename: Dict[str, str] = field(default_factory=dict)        # sajhanet.rename: local tool -> published name


def shared() -> Shared:
    raw = _raw()
    s = Shared()
    s.enabled = _bool(_g('enabled', 'false'), False)
    s.base_url = str(_g('base_url', '')).rstrip('/')
    s.region = str(_g('region', ''))
    labels = raw.get('labels')
    s.labels = {str(k): str(v) for k, v in labels.items()} if isinstance(labels, dict) else {}
    s.signature_max_age_seconds = min(300.0, max(1.0, _num(_g('signature_max_age_seconds', 30), 30)))
    s.require_https = _bool(_g('require_https', 'true'), True)
    s.min_protocol_version = int(_num(_g('min_protocol_version', 1), 1))
    s.mtls = str(_g('mtls', 'off')).lower()
    s.membership = str(_g('plugins.membership', 'gossip'))
    s.admission = str(_g('plugins.admission', 'builtin_ca'))
    s.connector = str(_g('plugins.connector', 'sajha_native'))
    s.data_dir = str(_g('data_dir', 'data/sajhanet'))
    s.max_injections_per_minute = int(_num(_g('max_injections_per_minute', 6), 6))
    s.agent_lease_seconds = max(3.0, _num(_g('agent_lease_seconds', 15), 15))
    mods = _g('plugins.modules', None)
    if mods is None:
        mods = (raw.get('plugins') or {}).get('modules') if isinstance(raw.get('plugins'), dict) else None
    if isinstance(mods, str):
        mods = [m.strip() for m in mods.strip('[]').split(',')]
    s.plugin_modules = [str(m).strip().strip('\'"') for m in mods or [] if str(m).strip().strip('\'"')]
    s.vendor = str(_g('vendor', 'sajha')).strip()
    s.rename = _rename(_g('rename', None) or raw.get('rename'))
    g = GossipSettings()
    for k in GOSSIP_KEYS:
        setattr(g, k, type(getattr(g, k))(_num(_g('gossip.' + k, getattr(g, k)), getattr(g, k))))
    s.gossip = g
    pc = raw.get('peer_cache') if isinstance(raw.get('peer_cache'), dict) else {}
    s.peer_cache = PeerCacheSettings(path=str(_g('peer_cache.path', pc.get('path') or '')),
                                     interval_minutes=_num(_g('peer_cache.interval_minutes', 10), 10),
                                     max_age_days=_num(_g('peer_cache.max_age_days', 7), 7))
    return s


def _rename(v: Any) -> Dict[str, str]:
    """A ``rename`` map (``{local tool: published name}``), from YAML or a JSON string."""
    if isinstance(v, str) and v.strip():
        import json
        try:
            v = json.loads(v)
        except ValueError:
            v = None
    return {str(k): str(x) for k, x in v.items() if str(k).strip() and str(x).strip()} if isinstance(v, dict) else {}


def naming_problem(vendor: str, rename: Dict[str, str]) -> Optional[str]:
    """Why a vendor and rename map are unusable (None: usable)."""
    if vendor and not names.is_vendor(vendor):
        return (f'vendor {vendor!r} is not a vendor name: a lowercase letter, then lowercase letters, digits and '
                f'"_", at most 24 characters, never "__" and not ending with "_"')
    for local, pub in rename.items():
        if not names.is_published_name(pub):
            return f'rename {local}: {pub!r} is not a valid published tool name'
    return None


@dataclass
class ExternalServer:
    """A federation upstream this server offers into its nets as an external server (design §5.6): its
    tools under ``<vendor>__<tool>``, never a member of a net."""
    upstream: str
    vendor: str
    tools: List[str] = field(default_factory=lambda: ['*'])
    rename: Dict[str, str] = field(default_factory=dict)    # upstream tool name -> published name
    nets: List[str] = field(default_factory=list)           # nets it is offered into (empty: every net)
    prefix: str = ''                                         # published as <prefix>__<tool> (default: the vendor)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ExternalServer':
        up = str(d.get('upstream') or '').strip()
        if not up:
            raise ValueError('upstream: the federation upstream id of the external server')
        vendor = str(d.get('vendor') or '').strip()
        if not vendor:
            raise ValueError(f'{up}: vendor is required (the organisation that answers for its tools, e.g. acme)')
        rename = _rename(d.get('rename'))
        bad = naming_problem(vendor, rename)
        if bad:
            raise ValueError(f'{up}: {bad}')
        tools = d.get('tools') or ['*']
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(',') if t.strip()]
        nets = d.get('nets') or []
        if isinstance(nets, str):
            nets = [n.strip() for n in nets.split(',') if n.strip()]
        prefix = str(d.get('prefix') or '').strip()
        if prefix and (not names.is_published_name(prefix) or '__' in prefix or prefix.endswith('_')):
            raise ValueError(f'{up}: prefix {prefix!r} must be letters, digits, "_" and "-", without "__" and not '
                             f'ending with "_"')
        return cls(upstream=up, vendor=vendor, tools=[str(t) for t in tools], rename=rename,
                   nets=[str(n) for n in nets], prefix=prefix)

    @property
    def effective_prefix(self) -> str:
        return self.prefix or self.vendor

    def published(self, tool: str) -> str:
        return self.rename.get(tool) or names.published_name(tool, self.effective_prefix, True)

    def to_dict(self) -> Dict[str, Any]:
        return {'upstream': self.upstream, 'vendor': self.vendor, 'prefix': self.effective_prefix,
                'tools': list(self.tools), 'rename': dict(self.rename), 'nets': list(self.nets)}


def external_servers(raw: Optional[Dict[str, Any]] = None) -> Tuple[List[ExternalServer], List[str]]:
    """``sajhanet.external_servers`` (YAML list, or JSON in ``SAJHA_SAJHANET_EXTERNAL_SERVERS``) and the
    configuration errors found in it."""
    v = _g('external_servers', None)
    if v is None or v == []:
        v = (raw if raw is not None else _raw()).get('external_servers')
    if isinstance(v, str):
        import json
        try:
            v = json.loads(v)
        except ValueError:
            return [], ['sajhanet.external_servers is not a list']
    out: List[ExternalServer] = []
    errors: List[str] = []
    for d in v or []:
        try:
            x = ExternalServer.from_dict(d if isinstance(d, dict) else {})
        except ValueError as e:
            errors.append(f'sajhanet.external_servers: {e}')
            continue
        if any(o.upstream == x.upstream for o in out):
            errors.append(f'sajhanet.external_servers: {x.upstream} is listed twice')
            continue
        out.append(x)
    return out, errors


def _file_ref(ref: str, default_path: str) -> str:
    return ref if ref else 'file:' + default_path


def ref_path(ref: str) -> Optional[str]:
    """The file path of a ``file:`` reference (SAJHA Net writes only files it was given a path for)."""
    if isinstance(ref, str) and ref.startswith('file:'):
        return ref[5:]
    return None


def net_configs(s: Optional[Shared] = None, bind_host: str = '0.0.0.0', port: int = 3002
                ) -> Tuple[List[NetConfig], Dict[str, str]]:
    """Every configured net as a :class:`NetConfig`, and configuration errors by net name."""
    from sajha.core.net_extension import configured_nets
    s = s or shared()
    out: List[NetConfig] = []
    errors: Dict[str, str] = {}
    seen = set()
    for entry in configured_nets() or ([{'name': 'default'}] if s.enabled else []):
        nm = str(entry.get('name') or 'default')
        try:
            names.net_name_or_default(nm)
        except names.NameError_ as e:
            errors[nm] = str(e)
            continue
        if nm in seen:
            errors[nm] = f'net {nm} is listed twice in sajhanet.nets'
            continue
        seen.add(nm)
        d = os.path.join(s.data_dir, nm)
        ident = entry.get('identity') if isinstance(entry.get('identity'), dict) else {}
        ca = entry.get('ca') if isinstance(entry.get('ca'), dict) else {}
        pc = entry.get('peer_cache') if isinstance(entry.get('peer_cache'), dict) else {}
        gossip = GossipSettings(**vars(s.gossip))
        for k, v in (entry.get('gossip') or {}).items() if isinstance(entry.get('gossip'), dict) else ():
            if k in GOSSIP_KEYS:
                setattr(gossip, k, type(getattr(gossip, k))(_num(v, getattr(gossip, k))))
        cfg = NetConfig(
            name=nm,
            instance_name=str(entry.get('instance_name') or ''),
            advertise_address=str(entry.get('advertise_address') or ''),
            founder=_bool(entry.get('founder'), False),
            seeds=[str(x).rstrip('/') for x in (entry.get('seeds') or []) if x],
            identity=IdentitySettings(
                cert_ref=_file_ref(str(ident.get('cert_ref') or ''), os.path.join(d, 'instance.crt')),
                key_ref=_file_ref(str(ident.get('key_ref') or ''), os.path.join(d, 'instance.key')),
                ca_ref=_file_ref(str(ident.get('ca_ref') or ''), os.path.join(d, 'ca.pem')),
                revocation_list_ref=_file_ref(str(ident.get('revocation_list_ref') or ''),
                                              os.path.join(d, 'revoked.json')),
                pins=[str(p) for p in (ident.get('pins') or [])]),
            ca=CASettings(enabled=_bool(ca.get('enabled'), False),
                          key_ref=_file_ref(str(ca.get('key_ref') or ''), os.path.join(d, 'ca.key')),
                          cert_ref=_file_ref(str(ca.get('cert_ref') or ''), os.path.join(d, 'ca.pem')),
                          cert_validity_days=_num(ca.get('cert_validity_days'), 30),
                          enrollment_token_minutes=_num(ca.get('enrollment_token_minutes'), 30),
                          enrollments_per_minute=int(_num(ca.get('enrollments_per_minute'), 10)),
                          auto_init=(None if ca.get('auto_init') is None else _bool(ca.get('auto_init'), True))),
            peer_cache=PeerCacheSettings(
                path=str(pc.get('path') or (s.peer_cache.path.replace('<net>', nm) if s.peer_cache.path
                                            else os.path.join(d, 'peers.json'))),
                interval_minutes=_num(pc.get('interval_minutes'), s.peer_cache.interval_minutes),
                max_age_days=_num(pc.get('max_age_days'), s.peer_cache.max_age_days)),
            static_peers=[str(x) for x in (entry.get('static_peers') or [])],
            base_url=str(entry.get('base_url') or s.base_url).rstrip('/'),
            region=str(entry.get('region') or s.region),
            labels={str(k): str(v) for k, v in (entry.get('labels') or s.labels or {}).items()},
            signature_max_age_seconds=min(300.0, _num(entry.get('signature_max_age_seconds'),
                                                      s.signature_max_age_seconds)),
            require_https=_bool(entry.get('require_https'), s.require_https),
            min_protocol_version=int(_num(entry.get('min_protocol_version'), s.min_protocol_version)),
            admission=s.admission, membership=s.membership, gossip=gossip,
            max_injections_per_minute=s.max_injections_per_minute,
            vendor=str(entry.get('vendor') or s.vendor).strip(),
            rename=_rename(entry.get('rename')) if entry.get('rename') is not None else dict(s.rename))
        bad = naming_problem(cfg.vendor, cfg.rename)
        if not bad and entry.get(EXTERNAL_KEY) is not None:
            bad = (f'{EXTERNAL_KEY} is not a key of a net entry: this server is always a member of its nets; to '
                   f'offer another server\'s tools under its vendor\'s prefix, list it in sajhanet.external_servers')
        if bad:
            errors[nm] = bad
        name, why = names.resolve_instance_name(cfg.instance_name, cfg.advertise_address, bind_host, port)
        if name is None:
            errors[nm] = why
        elif bad:
            pass
        else:
            cfg.instance_name = name
            if not cfg.base_url:
                if names.is_address_name(name):
                    cfg.base_url = ('https://' if cfg.require_https else 'http://') + name
                else:
                    errors[nm] = 'sajhanet.base_url (or the net entry\'s base_url) is required with a configured name'
        out.append(cfg)
    return out, errors
