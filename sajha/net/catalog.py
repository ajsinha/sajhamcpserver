# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Catalog exchange and one name, one contract (protocol §10; design §7, §8.4, §8.5, §8.7).

One :class:`CatalogBook` per :class:`~sajha.net.node.NetNode` (one net):

* **Host side.** :meth:`CatalogBook.exports` is what this participant offers a peer: every tool of its
  :class:`~sajha.net.plugins.CatalogSource` the export rule lets that peer see, complete (name, title,
  description, both schemas, annotations, ``_meta``) minus MCP Apps links, with
  ``_meta["io.sajha/net"]`` (net, instance, version, contract and description hashes). It serves
  ``POST /sajhanet/v1/catalog`` (``if_none_match`` against the §10.2 hash) and
  ``POST /sajhanet/v1/conflicts``, and publishes ``digests.catalog`` and ``digests.conflicts`` in its
  member record.
* **Home side.** :meth:`CatalogBook.tick` pulls a peer's catalog when its digest or incarnation
  changed, when this run has not pulled it yet, and every refresh interval (§10.1); a response is
  verified, each tool's ``contract_hash`` recomputed (a mismatch is not imported and flags the peer),
  schemas checked, text screened and capped, and the peer's trust level applied (``auto``,
  ``review``, ``pinned``). The held copy persists (for ``if_none_match``), but a tool is *live* only
  after a signed answer from its host in this run (§10.6 restart rule).
* **Offline removal.** On ``left``, ``dead`` or revocation a peer's catalog stops being live at once;
  while it is ``suspect`` its tools are listed as ``unavailable`` (§10.6).
* **One name, one contract.** :meth:`CatalogBook.evaluate` groups every live offer of a tool part
  (its own exports included) by contract hash; any difference, or a conflicts document of an alive
  or suspect member naming the tool, quarantines it. Entering and leaving a quarantine are events
  (``tool_quarantined``, ``tool_reactivated``) carrying a report that names the differing host(s)
  and the first differing JSON Pointer (§10.7, CON-06). The own observations are a signed
  ``conflicts`` document.

Rule names asked of the :class:`~sajha.net.plugins.RuleEvaluator` here: ``export`` (subject: net,
peer, tool, user) and ``offer`` (net, host, tool: False hides a host's offer from this view, as a
block does). The rules of calls are in :mod:`sajha.net.routing`.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.net import EXTENSION_ID, crypto, jcs, names, schemas
from sajha.net.errors import NetError
from sajha.net.plugins import AllowAll, CatalogSource, PeerUnreachable, RuleEvaluator

logger = logging.getLogger(__name__)

TRUST_LEVELS = ('auto', 'review', 'pinned')
HINTS = ('readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint')
MAX_CATALOG_RESPONSE = 8 * 1024 * 1024          # §18
RUN_TTL_FLOOR = 60.0


# ── hashes (§10.2) ──────────────────────────────────────────────────

def sha(data: bytes) -> str:
    return 'sha-256:' + crypto.b64url(hashlib.sha256(data).digest())


def contract_of(tool: Dict[str, Any]) -> Dict[str, Any]:
    return {'inputSchema': tool.get('inputSchema'),
            'outputSchema': tool.get('outputSchema') if tool.get('outputSchema') else None,
            'annotations': tool.get('annotations') or {}}


def contract_hash(tool: Dict[str, Any]) -> str:
    return sha(jcs.canonicalize(contract_of(tool)))


def description_hash(tool: Dict[str, Any]) -> str:
    return sha(jcs.canonicalize({'title': tool.get('title') or '', 'description': tool.get('description') or ''}))


def catalog_hash(tools: List[Dict[str, Any]]) -> str:
    return sha(jcs.canonicalize(sorted(tools, key=lambda t: str(t.get('name')))))


def strip_ui(tool: Dict[str, Any]) -> Dict[str, Any]:
    """§10.2: MCP Apps links (``_meta.ui`` and any ``ui://`` reference) are not shared."""
    t = copy.deepcopy(tool)
    meta = t.get('_meta')
    if isinstance(meta, dict):
        meta.pop('ui', None)
        for k in [k for k, v in meta.items() if 'ui://' in json.dumps(v, default=str)]:
            meta.pop(k, None)
        if not meta:
            t.pop('_meta', None)
    return t


def is_safe_to_repeat(annotations: Optional[Dict[str, Any]]) -> bool:
    """§15.8 rule 3: read-only, or idempotent and explicitly not destructive (MCP's default for
    ``destructiveHint`` is true)."""
    a = annotations if isinstance(annotations, dict) else {}
    if a.get('readOnlyHint') is True:
        return True
    return a.get('idempotentHint') is True and a.get('destructiveHint') is False


# ── differences and conflict reports (§10.7 "Reporting a conflict") ─

def _escape(token: str) -> str:
    return str(token).replace('~', '~0').replace('/', '~1')


def first_difference(a: Any, b: Any, pointer: str = '') -> Optional[Tuple[str, Any, Any]]:
    """The first place two JSON values differ, as ``(JSON Pointer, value in a, value in b)``; keys in
    sorted order, so every participant names the same place. None when equal."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return pointer + '/' + _escape(k), a.get(k, _ABSENT), b.get(k, _ABSENT)
            d = first_difference(a[k], b[k], pointer + '/' + _escape(k))
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            if i >= len(a) or i >= len(b):
                return pointer + f'/{i}', a[i] if i < len(a) else _ABSENT, b[i] if i < len(b) else _ABSENT
            d = first_difference(a[i], b[i], pointer + f'/{i}')
            if d:
                return d
        return None
    if a == b and type(a) is type(b):
        return None
    return pointer or '', a, b


class _Absent:
    def __repr__(self):
        return '(absent)'


_ABSENT = _Absent()


def _show(v: Any) -> str:
    if v is _ABSENT:
        return '(absent)'
    return json.dumps(v, sort_keys=True, default=str)[:120]


def contract_difference(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Where two contracts differ: ``{"where": "inputSchema"|"outputSchema", "pointer", "a", "b"}`` or
    ``{"where": "annotations", "name", "a", "b"}``."""
    for part in ('inputSchema', 'outputSchema'):
        d = first_difference(a.get(part), b.get(part))
        if d:
            return {'where': part, 'pointer': d[0] or '/', 'a': _show(d[1]), 'b': _show(d[2])}
    d = first_difference(a.get('annotations') or {}, b.get('annotations') or {})
    if d:
        nm = d[0].lstrip('/').split('/')[0].replace('~1', '/').replace('~0', '~') if d[0] else ''
        return {'where': 'annotations', 'name': nm or '(all)', 'a': _show(d[1]), 'b': _show(d[2])}
    return None


def conflict_report(net: str, tool: str, offers: List[Dict[str, Any]],
                    contracts: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Group the offers by contract hash; a strictly largest group is ``agreeing`` and the others
    ``differing`` (on a tie every group is listed, nobody is named differing). ``contracts`` maps an
    instance to its contract, to name the first differing place of each differing group."""
    groups: Dict[str, List[str]] = {}
    for o in offers:
        groups.setdefault(o['contract_hash'], []).append(o['instance'])
    ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    out: Dict[str, Any] = {'net': net, 'tool': tool,
                           'offers': sorted(({'instance': o['instance'], 'contract_hash': o['contract_hash']}
                                             for o in offers), key=lambda o: o['instance']),
                           'groups': [{'contract_hash': h, 'instances': sorted(i)} for h, i in ordered],
                           'agreeing': [], 'differing': [], 'differences': []}
    majority = len(ordered) > 1 and len(ordered[0][1]) > len(ordered[1][1])
    if majority:
        out['agreeing'] = sorted(ordered[0][1])
        out['differing'] = sorted(i for _h, inst in ordered[1:] for i in inst)
    contracts = contracts or {}
    base = ordered[0][1][0] if ordered else None
    for h, inst in ordered[1:]:
        ref = sorted(inst)[0]
        if base in contracts and ref in contracts:
            d = contract_difference(contracts[base], contracts[ref])
            if d:
                out['differences'].append(dict(d, instances=sorted(inst), others=sorted(ordered[0][1])))
    out['text'] = report_text(out)
    return out


def report_text(r: Dict[str, Any]) -> str:
    net, tool = r['net'], r['tool']
    if r['differing']:
        head = f'Tool {tool} quarantined in {net}: {", ".join(r["differing"])} ' \
               f'offer{"s" if len(r["differing"]) == 1 else ""} a different contract.'
    else:
        head = f'Tool {tool} quarantined in {net}: its hosts offer {len(r["groups"])} different contracts ' \
               f'(no majority).'
    lines = [head]
    for d in r.get('differences') or []:
        if d['where'] == 'annotations':
            lines.append(f'Differs: annotation {d["name"]} ({", ".join(d["instances"])}: {d["b"]}; '
                         f'others: {d["a"]}).')
        else:
            lines.append(f'Differs: {d["where"]} {d["pointer"]} ({", ".join(d["instances"])}: {d["b"]}; '
                         f'others: {d["a"]}).')
    if r['differing']:
        lines.append(f'Agreeing: {", ".join(r["agreeing"])} ({len(r["agreeing"])}). '
                     f'Differing: {", ".join(r["differing"])} ({len(r["differing"])}).')
        lines.append(f'Fix: correct {tool} on {", ".join(r["differing"])}, or stop exporting it there. The tool '
                     f'is unavailable everywhere in {net} until then.')
    else:
        lines.append('Groups: ' + '; '.join(f'{", ".join(g["instances"])} ({g["contract_hash"][:16]}...)'
                                            for g in r['groups']) + '.')
        lines.append(f'Fix: make every host offer one contract for {tool}, or stop exporting it on all but one. '
                     f'The tool is unavailable everywhere in {net} until then.')
    return '\n'.join(lines)


# ── screening defaults (SAJHA passes federation's) ──────────────────

def basic_schema_problem(schema: Any, what: str = 'inputSchema', required: bool = True) -> Optional[str]:
    if schema is None or schema == {}:
        return None if not required else f'{what} is missing'
    if not isinstance(schema, dict) or schema.get('type') != 'object':
        return f'{what} must be a JSON Schema object with "type": "object"'
    return None


def basic_screen_text(text: Any, limit: int) -> Tuple[str, bool]:
    s = '' if text is None else str(text)
    return (s[:max(0, limit - 1)] + '…', False) if len(s) > limit else (s, False)


def screen_schema_with(screen_text: Callable[[Any, int], Tuple[str, bool]], schema: Any, limit: int,
                       depth: int = 0) -> Tuple[Any, bool]:
    if depth > 32:
        return schema, False
    if isinstance(schema, dict):
        out, flagged = {}, False
        for k, v in schema.items():
            if k in ('description', 'title') and isinstance(v, str):
                out[k], f = screen_text(v, limit)
            else:
                out[k], f = screen_schema_with(screen_text, v, limit, depth + 1)
            flagged = flagged or f
        return out, flagged
    if isinstance(schema, list):
        res = [screen_schema_with(screen_text, v, limit, depth + 1) for v in schema]
        return [r[0] for r in res], any(r[1] for r in res)
    return schema, False


@dataclass
class Limits:
    max_tools_per_peer: int = 2000
    max_catalog_bytes: int = 5 * 1024 * 1024
    max_description_chars: int = 1024
    schema_text_chars: int = 512
    title_chars: int = 200


# ── the book ────────────────────────────────────────────────────────

class CatalogBook:
    """One participant's catalogs in one net (see the module docstring)."""

    def __init__(self, node, source: Optional[CatalogSource] = None, *, rules: Optional[RuleEvaluator] = None,
                 trust_of: Optional[Callable[[str], Tuple[str, List[str]]]] = None,
                 approvals: Optional[Callable[[str], Dict[str, Dict[str, Any]]]] = None,
                 screen_text: Callable[[Any, int], Tuple[str, bool]] = basic_screen_text,
                 schema_problem: Callable[..., Optional[str]] = basic_schema_problem,
                 limits: Optional[Limits] = None, refresh_interval: float = 300.0,
                 default_trust: str = 'auto', reexport: bool = False, run_ttl: float = RUN_TTL_FLOOR,
                 reexports: Optional[Callable[[Optional[str]], List[Dict[str, Any]]]] = None):
        self.node = node
        self.net = node.net
        self.kv = node.kv
        self.clock = node.clock
        self.source = source
        self.rules = rules or AllowAll()
        self.default_trust = default_trust if default_trust in TRUST_LEVELS else 'auto'
        self._trust_of = trust_of
        self._approvals = approvals
        self.screen_text = screen_text
        self.schema_problem = schema_problem
        self.limits = limits or Limits()
        self.refresh_interval = max(5.0, float(refresh_interval))
        self.reexport = reexport
        # re-export (§16): tools imported from other participants that this one offers ``peer`` (None: any
        # peer), as tool objects with ``_net`` (``origin`` within one net, none for a bridge) and ``_source``
        # (where the call goes; never served). Only used while ``reexport`` is on for this net.
        self.reexports = reexports
        self.run_ttl = max(RUN_TTL_FLOOR, float(run_ttl))
        self.counters: Dict[str, int] = {}
        self._own_cache: Optional[Tuple[float, List[Dict[str, Any]]]] = None
        self._local_of: Dict[str, str] = {}             # published name -> local name of each own tool (§5.5)
        self.refused: Dict[str, Dict[str, str]] = {}    # own tools not offered: local name -> published, reason
        self.started = False

    # ── wiring ─────────────────────────────────────────────────────

    def attach(self) -> 'CatalogBook':
        """Serve the catalog feature on the node: endpoints, digests and the member-state observer."""
        n = self.node
        if 'catalog' not in n.extra_features:
            n.extra_features.append('catalog')
        P = '/sajhanet/v1'
        n.handlers[P + '/catalog'] = self.serve_catalog
        n.handlers[P + '/conflicts'] = self.serve_conflicts
        n.digest_sources['catalog'] = self.own_digest
        n.digest_sources['conflicts'] = lambda: int((self.kv.get('conf_doc') or {}).get('version') or 0)
        n.observers.append(self.on_event)
        n.tick_hooks.append(self.tick)                   # pulls ride on the gossip agent's period
        n.catalog = self
        return self

    def start(self) -> None:
        """A new run: a peer's tools are listed only after it answers in this run (§10.6)."""
        cur = self.kv.get('run')
        if not cur:
            cur = secrets.token_hex(8)
            self.kv.set('run', cur, ttl=self.run_ttl)
        self.started = True
        self._recompute_digest(resign=False)

    @property
    def run(self) -> str:
        r = self.kv.get('run')
        if not r:
            r = secrets.token_hex(8)
            self.kv.set('run', r, ttl=self.run_ttl)
        return r

    def count(self, what: str, n: int = 1) -> None:
        self.counters[what] = self.counters.get(what, 0) + n

    def trust_of(self, peer: str) -> Tuple[str, List[str]]:
        if self._trust_of is not None:
            try:
                level, pinned = self._trust_of(peer)
                if level in TRUST_LEVELS:
                    return level, list(pinned or [])
            except Exception as e:
                logger.debug(f'SAJHA Net {self.net}: trust of {peer}: {e}')
        return self.default_trust, []

    def approvals(self, peer: str) -> Dict[str, Dict[str, Any]]:
        if self._approvals is not None:
            try:
                return dict(self._approvals(peer) or {})
            except Exception as e:
                logger.debug(f'SAJHA Net {self.net}: approvals of {peer}: {e}')
        return {}

    # ── host side (§10.2) ──────────────────────────────────────────

    def _source_tools(self) -> List[Dict[str, Any]]:
        """The own tools as offered: each under its published name (protocol §5.5)."""
        now = self.clock()
        if self._own_cache and now - self._own_cache[0] < 1.0:
            return self._own_cache[1]
        tools = []
        if self.source is not None:
            try:
                tools = list(self.source.tools(self.net) or [])
            except Exception as e:
                logger.warning(f'SAJHA Net {self.net}: catalog source failed: {e}')
        tools = self._publish(tools)
        self._own_cache = (now, tools)
        return tools

    def rename(self) -> Dict[str, str]:
        """This participant's ``rename`` map (local tool -> published name; its net configuration)."""
        return {str(k): str(v) for k, v in (getattr(self.node.cfg, 'rename', None) or {}).items()}

    def _publish(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Offer the source's tools under their published names (§5.5): the participant's ``rename``
        entry, else the source's ``_net.publish_as`` (an external server's ``<vendor>__<tool>``), else
        the tool's own name. A name that is invalid, taken by another own tool, or too long for a
        qualified name (MAX_QUALIFIED) is refused, with an event."""
        rename = self.rename()
        try:
            room = names.max_tool_part(self.net, self.node.name)
        except Exception:
            room = names.MAX_QUALIFIED
        out, local_of, refused = [], {}, {}
        for raw in sorted((t for t in tools if isinstance(t, dict)), key=lambda t: str(t.get('name') or '')):
            local = raw.get('name')
            if not isinstance(local, str) or not local:
                continue
            pub = rename.get(local) or str((raw.get('_net') or {}).get('publish_as') or '') or local
            why = None
            if not names.is_published_name(pub):
                why = (f'{pub!r} is not a valid published tool name (letters, digits, "_", "-" and ".", '
                       f'at most 128 characters)')
            elif len(names.tool_part(pub)) > room:
                why = (f'its published name {pub} is {len(names.tool_part(pub))} characters; in {self.net} a tool '
                       f'of {self.node.name} may have at most {room} (qualified names are at most '
                       f'{names.MAX_QUALIFIED}); give it a shorter name with rename')
            elif names.tool_part(pub) in local_of:
                why = f'its published name {pub} is already taken by {local_of[names.tool_part(pub)]}'
            if why:
                refused[local] = {'published': pub, 'reason': why}
                continue
            local_of[names.tool_part(pub)] = local
            if pub != local:
                raw = dict(raw, name=pub)
            out.append(raw)
        self._local_of = {t['name']: local_of[names.tool_part(t['name'])] for t in out}
        if refused != self.refused:
            for local in sorted(set(refused) - set(self.refused)):
                logger.warning(f'SAJHA Net {self.net}: tool {local} is not offered: {refused[local]["reason"]}')
                self.node.event('tool_name_refused', tool=local, published=refused[local]['published'],
                                detail=refused[local]['reason'])
            self.refused = refused
        return out

    def local_name(self, published: str) -> Optional[str]:
        """The local name of the own tool offered as ``published`` (None: not an own tool)."""
        self._source_tools()
        return self._local_of.get(published)

    def published_name(self, local: str) -> Optional[str]:
        """The name the own tool ``local`` is offered under (None: not offered)."""
        self._source_tools()
        return next((p for p, l in self._local_of.items() if l == local), None)

    def invalidate(self) -> None:
        """The local catalog may have changed (a tool, schema, description or export rule)."""
        self._own_cache = None
        self._recompute_digest()

    def _exported(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        t = strip_ui({k: v for k, v in raw.items() if k not in ('_net', '_source')})
        t.setdefault('inputSchema', {'type': 'object', 'properties': {}})
        extra = dict(raw.get('_net') or {})
        meta = {'net': self.net, 'instance': self.node.name}
        if self.node.cfg.region:
            meta['region'] = self.node.cfg.region
        if self.node.cfg.labels:
            meta['labels'] = dict(self.node.cfg.labels)
        for k in ('version', 'deprecated', 'data_classes', 'llm_tool', 'latency_ms_p50', 'health', 'per_user_results',
                  'origin', 'vendor', 'external'):
            if extra.get(k) is not None:
                meta[k] = extra[k]
        if 'version' in meta:
            meta['version'] = str(meta['version'])
        meta['contract_hash'] = contract_hash(t)
        meta['description_hash'] = description_hash(t)
        t['_meta'] = dict(t.get('_meta') or {}, **{EXTENSION_ID: meta})
        return t

    def tool_names(self, name: str) -> List[str]:
        """Every name an own tool goes by in rules (§5.5): its published name, then its local name."""
        self._source_tools()
        local = self._local_of.get(name)
        return [name] if not local or local == name else [name, local]

    def _export_allowed(self, peer: Optional[str], name: str) -> bool:
        try:
            return bool(self.rules.decide('export', {'net': self.net, 'peer': peer, 'tool': name, 'user': None,
                                                     'tool_names': self.tool_names(name)}).allow)
        except Exception as e:
            logger.warning(f'SAJHA Net {self.net}: export rule for {name}: {e}')
            return False

    def exports(self, peer: Optional[str] = None) -> List[Dict[str, Any]]:
        """The tools this participant offers ``peer`` (None: any peer), sorted by name: its own, then,
        with re-export on, the tools it re-exports (an own tool always wins its name)."""
        out = []
        seen = set()
        for raw in self._source_tools():
            name = raw.get('name')
            if not isinstance(name, str) or not name:
                continue
            seen.add(name)
            if self._export_allowed(peer, name):
                out.append(self._exported(raw))
        for raw in self._reexported(peer):
            if raw['name'] not in seen:
                seen.add(raw['name'])
                out.append(self._exported(raw))
        return sorted(out, key=lambda t: t['name'])

    def _reexported(self, peer: Optional[str]) -> List[Dict[str, Any]]:
        if not self.reexport or self.reexports is None:
            return []
        try:
            raws = list(self.reexports(peer) or [])
        except Exception as e:
            logger.warning(f'SAJHA Net {self.net}: re-export source failed: {e}')
            return []
        out = []
        for raw in raws:
            origin = (raw.get('_net') or {}).get('origin')
            if not isinstance(raw.get('name'), str) or not raw['name']:
                continue
            if peer is not None and origin == peer:
                continue                                  # never offer a tool back to the participant hosting it
            if origin == self.node.name:
                continue                                  # our own tool, come back through someone else
            out.append(raw)
        return out

    def reexport_of(self, name: str, peer: Optional[str]) -> Optional[Dict[str, Any]]:
        """The re-exported tool ``name`` as offered to ``peer`` (with ``_net`` and ``_source``), or None
        when ``name`` is an own tool or not re-exported to ``peer``."""
        if any(raw.get('name') == name for raw in self._source_tools()):
            return None
        return next((raw for raw in self._reexported(peer) if raw['name'] == name), None)

    def own_digest(self) -> str:
        return str(self.kv.get('own_digest') or 'none')

    def _recompute_digest(self, resign: bool = True) -> bool:
        tools = self.exports(None)
        rules_version = getattr(self.rules, 'version', None)          # an export rule change changes the digest
        d = 'sha256:' + hashlib.sha256(jcs.canonicalize([tools, str(rules_version)])).hexdigest()[:32]
        if d != self.kv.get('own_digest'):
            self.kv.set('own_digest', d)
            if resign:
                self.node.refresh_record()
            return True
        return False

    def serve_catalog(self, data: Dict[str, Any], v) -> Dict[str, Any]:
        tools = self.exports(v.sender)
        h = catalog_hash(tools)
        out = {'net': self.net, 'instance': self.node.name, 'catalog_digest': self.own_digest(), 'hash': h,
               'generated_at': crypto.rfc3339(self.clock())}
        if data.get('if_none_match') == h:
            out['unchanged'] = True
        else:
            out['unchanged'] = False
            out['tools'] = tools
        return out

    def serve_conflicts(self, data: Dict[str, Any], v) -> Dict[str, Any]:
        doc = self.kv.get('conf_doc')
        if not doc:
            doc = self._sign_doc(0, [])
            self.kv.set('conf_doc', doc)
        return doc

    # ── home side: pulling (§10.1) ─────────────────────────────────

    def _held(self, peer: str) -> Dict[str, Any]:
        return self.kv.get('cat:' + peer) or {}

    def live_peers(self) -> Dict[str, Dict[str, Any]]:
        """Peers whose catalog arrived in this run and who are alive or suspect: name -> held catalog."""
        run = self.run
        out = {}
        for m in self.node.members():
            if m['state'] not in ('alive', 'suspect'):
                continue
            held = self._held(m['name'])
            if held.get('run') == run and held.get('incarnation') == m['record'].get('incarnation'):
                out[m['name']] = dict(held, state=m['state'], member=m)
        return out

    def _needs_pull(self, m: Dict[str, Any], now: float) -> Optional[str]:
        held = self._held(m['name'])
        rec = m['record']
        if 'catalog' not in (rec.get('features') or []):
            return None
        if held.get('run') != self.run:
            return 'new_run' if held else 'new_peer'
        if held.get('incarnation') != rec.get('incarnation'):
            return 'incarnation'
        if held.get('catalog_digest') != rec.get('digests', {}).get('catalog'):
            return 'digest'
        if now - float(held.get('pulled_at') or 0) >= self.refresh_interval:
            return 'refresh'
        return None

    def tick(self) -> None:
        """Pull what changed, pull conflicts documents, re-evaluate (run by the agent of the net)."""
        if not self.started:
            self.start()
        self.kv.update('run', lambda cur: cur or secrets.token_hex(8), ttl=self.run_ttl)   # keep this run
        self._recompute_digest()
        now = self.clock()
        changed = False
        for m in self.node.members():
            if m['state'] != 'alive':
                continue
            if self._blocked_outbound(m['name']):
                continue
            why = self._needs_pull(m, now)
            if why:
                changed = self.pull(m, why) or changed
            changed = self._pull_conflicts(m) or changed
        self.evaluate()

    def _blocked_outbound(self, peer: str) -> bool:
        try:
            return not self.rules.decide('pull', {'net': self.net, 'peer': peer}).allow
        except Exception:
            return False

    def pull(self, m: Dict[str, Any], why: str = 'manual') -> bool:
        """One catalog pull from member ``m``. True when what is live changed."""
        peer = m['name']
        held = self._held(peer)
        body: Dict[str, Any] = {}
        if held.get('hash'):
            body['if_none_match'] = held['hash']
        try:
            x = self.node.request(m['record']['url'], '/sajhanet/v1/catalog', body, peer)
        except Exception as e:                                       # unreachable, refused, invalid
            self.count('pull_failed')
            self._flag(peer, 'pull_failed', f'{getattr(e, "reason", "") or e.__class__.__name__}: {str(e)[:200]}',
                       keep=False)
            return False
        data = x.body
        if not isinstance(data, dict) or schemas.errors('catalog_response', data):
            self.count('pull_invalid')
            self._flag(peer, 'invalid_catalog', 'the catalog response fails its schema', keep=False)
            return False
        if data.get('net') != self.net or data.get('instance') != peer:
            self._flag(peer, 'invalid_catalog', 'the catalog names another net or instance', keep=False)
            return False
        self.count('pulls')
        inc = m['record'].get('incarnation')
        if data.get('unchanged'):
            if not held or held.get('hash') != data.get('hash'):
                self._flag(peer, 'invalid_catalog', 'unchanged against a hash this server does not hold', keep=False)
                return False
            new = dict(held, run=self.run, incarnation=inc, catalog_digest=data.get('catalog_digest'),
                       pulled_at=self.clock())
            was_live = held.get('run') == self.run and held.get('incarnation') == inc
            self.kv.set('cat:' + peer, new)
            if not was_live:
                self.node.event('catalog_live', peer=peer, tools=len(new.get('tools') or []), why=why)
            return not was_live
        raw_tools = data.get('tools') or []
        if catalog_hash(raw_tools) != data.get('hash'):
            self._flag(peer, 'hash_mismatch', 'the catalog hash does not match its tools', keep=False)
            return False
        accepted, flags = self._accept(peer, raw_tools)
        new = {'run': self.run, 'incarnation': inc, 'catalog_digest': data.get('catalog_digest'),
               'hash': data['hash'], 'pulled_at': self.clock(), 'tools': accepted, 'flags': flags,
               'first_seen': held.get('first_seen') or self.clock()}
        self._history(peer, held.get('tools') or [], accepted)
        self.kv.set('cat:' + peer, new)
        self.node.event('catalog_pulled', peer=peer, tools=len(accepted), flags=flags, why=why)
        return True

    def _flag(self, peer: str, what: str, detail: str, keep: bool = True) -> None:
        self.node.event('catalog_flag', peer=peer, flag=what, detail=detail)
        if keep:
            self.kv.update('cat:' + peer, lambda cur: dict(cur or {}, flags=sorted(set((cur or {}).get('flags', []))
                                                                                  | {what})))

    def _history(self, peer: str, old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> None:
        before = {t['name']: t for t in old}
        after = {t['name']: t for t in new}
        for name in sorted(set(before) | set(after)):
            a, b = before.get(name), after.get(name)
            if a and not b:
                self.node.event('tool_withdrawn', peer=peer, tool=name)
            elif b and not a:
                self.node.event('tool_offered', peer=peer, tool=name, contract_hash=b['contract_hash'])
            elif a['contract_hash'] != b['contract_hash'] or a['description_hash'] != b['description_hash']:
                self.node.event('tool_changed', peer=peer, tool=name, contract_hash=b['contract_hash'],
                                previous_contract_hash=a['contract_hash'],
                                description_changed=a['description_hash'] != b['description_hash'])

    def _accept(self, peer: str, raw_tools: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Validate, screen and cap a peer's tools; apply its trust level (design §7.3)."""
        lim = self.limits
        flags: List[str] = []
        level, pinned = self.trust_of(peer)
        approved = self.approvals(peer) if level == 'review' else {}
        out: List[Dict[str, Any]] = []
        size = 0
        for raw in raw_tools:
            if len(out) >= lim.max_tools_per_peer:
                flags.append('too_many_tools')
                break
            try:
                size += len(json.dumps(raw, default=str))
            except Exception:
                continue
            if size > lim.max_catalog_bytes:
                flags.append('catalog_too_large')
                break
            entry = self._accept_one(peer, raw, flags)
            if entry is None:
                continue
            if level == 'pinned' and entry['name'] not in pinned:
                entry['state'] = 'hidden'
            elif level == 'review':
                ok = approved.get(entry['name'])
                if not ok:
                    entry['state'] = 'held'
                elif ok.get('contract_hash') != entry['contract_hash'] or \
                        ok.get('description_hash') != entry['description_hash']:
                    if isinstance(ok.get('entry'), dict):
                        prev = dict(ok['entry'], state='active', held_change=entry['contract_hash'])
                        entry = prev                                # held at the approved version
                    else:
                        entry['state'] = 'held'
            out.append(entry)
        if flags:
            self.node.event('catalog_flag', peer=peer, flag=','.join(sorted(set(flags))),
                            detail=f'{peer}: {", ".join(sorted(set(flags)))}')
        return out, sorted(set(flags))

    def _accept_one(self, peer: str, raw: Dict[str, Any], flags: List[str]) -> Optional[Dict[str, Any]]:
        lim = self.limits
        name = raw.get('name') if isinstance(raw, dict) else None
        if not isinstance(name, str) or not name or len(name) > 128:
            flags.append('invalid_tool')
            return None
        meta = ((raw.get('_meta') or {}).get(EXTENSION_ID)) if isinstance(raw.get('_meta'), dict) else None
        if not isinstance(meta, dict) or schemas.errors('tool_net_meta', meta) or meta.get('net') != self.net or \
                meta.get('instance') != peer:
            flags.append('invalid_meta')
            return None
        if meta.get('origin') == self.node.name:
            return None                                               # our own tool, re-exported back to us (§16)
        ch = contract_hash(raw)
        if ch != meta.get('contract_hash'):
            flags.append('contract_hash_mismatch')
            self.node.event('catalog_flag', peer=peer, flag='contract_hash_mismatch',
                            detail=f'{peer} states a contract hash for {name} that does not match its schemas; '
                                   f'the tool is not imported')
            return None
        problem = self.schema_problem(raw.get('inputSchema'), 'inputSchema') or \
            self.schema_problem(raw.get('outputSchema'), 'outputSchema', required=False)
        entry: Dict[str, Any] = {'name': name, 'part': names.tool_part(name), 'contract_hash': ch,
                                 'description_hash': description_hash(raw),
                                 'version': str(meta.get('version') or ''), 'meta': meta,
                                 'annotations': copy.deepcopy(raw.get('annotations') or {}),
                                 'contract': contract_of(raw), 'state': 'active'}
        if problem:
            entry['state'] = 'invalid'
            entry['problem'] = problem[:300]
            flags.append('invalid_schema')
        clean = strip_ui(raw)
        desc = clean.get('description') or ''
        if len(desc) > lim.max_description_chars:
            flags.append('description_too_long')
        d, f1 = self.screen_text(desc, lim.max_description_chars)
        title, f2 = self.screen_text(clean.get('title') or '', lim.title_chars)
        ins, f3 = screen_schema_with(self.screen_text, clean.get('inputSchema') or {'type': 'object'},
                                     lim.schema_text_chars)
        outs, f4 = screen_schema_with(self.screen_text, clean.get('outputSchema') or {}, lim.schema_text_chars)
        if f1 or f2 or f3 or f4:
            flags.append('screened')
            entry['screened'] = True
        definition = {'name': name, 'description': d, 'inputSchema': ins}
        if title:
            definition['title'] = title
        if isinstance(outs, dict) and outs.get('type') == 'object':
            definition['outputSchema'] = outs
        if clean.get('annotations'):
            definition['annotations'] = copy.deepcopy(clean['annotations'])
        other_meta = {k: v for k, v in (clean.get('_meta') or {}).items() if k != EXTENSION_ID}
        if other_meta:
            definition['_meta'] = other_meta
        entry['definition'] = definition
        return entry

    def _pull_conflicts(self, m: Dict[str, Any]) -> bool:
        if 'catalog' not in (m['record'].get('features') or []):
            return False
        want = int((m['record'].get('digests') or {}).get('conflicts') or 0)
        held = self.kv.get('cdoc:' + m['name']) or {}
        if want <= int(held.get('version') or 0) and held.get('run') == self.run:
            return False
        if want == 0 and not held:
            return False
        try:
            x = self.node.request(m['record']['url'], '/sajhanet/v1/conflicts', {}, m['name'])
        except Exception as e:
            logger.debug(f'SAJHA Net {self.net}: conflicts of {m["name"]}: {e}')
            return False
        doc = x.body
        if not self.accept_conflicts(doc, m['name'], x.verified.certificate):
            return False
        self.kv.set('cdoc:' + m['name'], dict(doc, run=self.run))
        return True

    def accept_conflicts(self, doc: Any, sender: str, certificate) -> bool:
        """NET-03, CON-04: a conflicts document counts only when it is the sender's own, of this net, signed."""
        if not isinstance(doc, dict) or schemas.errors('conflicts_document', doc):
            return False
        if doc.get('net') != self.net or doc.get('instance') != sender:
            return False
        if doc['signature'].get('keyid') != crypto.thumbprint(crypto.cert_der(certificate)):
            return False
        return crypto.verify_record('conflicts', doc, doc['signature'], certificate.public_key())

    # ── offline removal (§10.6) ────────────────────────────────────

    def on_event(self, kind: str, data: Dict[str, Any]) -> None:
        if kind == 'member_state' and data.get('state') in ('dead', 'left'):
            self.drop(data.get('member', ''), data['state'])
        elif kind == 'member_removed':
            self.drop(data.get('member', ''), data.get('reason') or 'removed')
        elif kind == 'member_state':
            self.evaluate()

    def drop(self, peer: str, why: str) -> None:
        """Stop listing and routing ``peer``'s tools at once; keep the stored copy for ``if_none_match``."""
        if not peer:
            return
        held = self._held(peer)
        if held.get('run'):
            self.kv.set('cat:' + peer, dict(held, run=None))
            self.node.event('catalog_withdrawn', peer=peer, why=why, tools=len(held.get('tools') or []))
        self.kv.delete('cdoc:' + peer)
        self.evaluate()

    # ── one name, one contract (§10.7) ─────────────────────────────

    def offers(self, include_own: bool = True) -> Dict[str, List[Dict[str, Any]]]:
        """Tool part -> every live offer in this net: ``{instance, host_tool, contract_hash, contract, entry,
        state, own}``. Offers hidden by the ``offer`` rule are left out."""
        out: Dict[str, List[Dict[str, Any]]] = {}
        if include_own:
            for t in self.exports(None):
                meta = t['_meta'][EXTENSION_ID]
                out.setdefault(names.tool_part(t['name']), []).append(
                    {'instance': self.node.name, 'host_tool': t['name'], 'contract_hash': meta['contract_hash'],
                     'contract': contract_of(t), 'own': True, 'state': 'alive', 'entry': None})
        for peer, held in self.live_peers().items():
            for e in held.get('tools') or []:
                if not self._offer_allowed(peer, e['name']):
                    continue
                out.setdefault(e['part'], []).append(
                    {'instance': peer, 'host_tool': e['name'], 'contract_hash': e['contract_hash'],
                     'contract': e.get('contract') or {}, 'own': False, 'state': held['state'], 'entry': e,
                     'member': held['member']})
        return out

    def _offer_allowed(self, peer: str, tool: str) -> bool:
        try:
            return bool(self.rules.decide('offer', {'net': self.net, 'host': peer, 'tool': tool}).allow)
        except Exception:
            return True

    def observed(self) -> Dict[str, Dict[str, Any]]:
        """Conflicts this participant observes itself: tool part -> report."""
        out = {}
        for part, offers in self.offers().items():
            if len({o['contract_hash'] for o in offers}) > 1:
                out[part] = conflict_report(self.net, part, offers, {o['instance']: o['contract'] for o in offers})
        return out

    def _published(self) -> Dict[str, List[str]]:
        """Tool part -> publishers, from current conflicts documents of alive or suspect members."""
        live = {m['name'] for m in self.node.members() if m['state'] in ('alive', 'suspect')}
        out: Dict[str, List[str]] = {}
        for k, doc in self.kv.scan('cdoc:'):
            who = k[5:]
            if who not in live or doc.get('run') != self.run:
                continue
            for c in doc.get('conflicts') or []:
                out.setdefault(names.tool_part(c.get('tool', '')), []).append(who)
        return out

    def _sign_doc(self, version: int, conflicts: List[Dict[str, Any]]) -> Dict[str, Any]:
        doc = {'type': 'conflicts', 'net': self.net, 'instance': self.node.name, 'version': int(version),
               'conflicts': conflicts[:1000]}
        doc['signature'] = crypto.sign_record('conflicts', doc, self.node.signer.key, self.node.signer.keyid)
        return doc

    def evaluate(self) -> Dict[str, Dict[str, Any]]:
        """Re-evaluate the rule; publish the own observations; quarantine and re-activate. Returns the
        quarantined tool parts with their reports."""
        observed = self.observed()
        prev_doc = self.kv.get('conf_doc') or {}
        prev_since = {c['tool']: c['since'] for c in prev_doc.get('conflicts') or []}
        conflicts = [{'tool': part, 'offers': r['offers'], 'since': prev_since.get(part) or crypto.rfc3339(self.clock())}
                     for part, r in sorted(observed.items())]
        key = lambda cs: [(c['tool'], c['offers']) for c in cs]                     # noqa: E731
        if key(conflicts) != key(prev_doc.get('conflicts') or []) or not prev_doc:
            version = int(prev_doc.get('version') or 0) + (1 if prev_doc or conflicts else 0)
            self.kv.set('conf_doc', self._sign_doc(version, conflicts))
            if prev_doc or conflicts:
                self.node.refresh_record()
        published = self._published()
        quarantined: Dict[str, Dict[str, Any]] = {}
        all_offers = None
        for part in set(observed) | set(published):
            if part in observed:
                r = dict(observed[part])
            elif part in (self.kv.get('quarantine') or {}):
                r = dict((self.kv.get('quarantine') or {})[part])        # keep what was last seen of the offers
            else:
                all_offers = all_offers if all_offers is not None else self.offers()
                offs = all_offers.get(part) or []
                r = {'net': self.net, 'tool': part,
                     'offers': sorted(({'instance': o['instance'], 'contract_hash': o['contract_hash']} for o in offs),
                                      key=lambda o: o['instance']),
                     'groups': [], 'agreeing': [], 'differing': [], 'differences': []}
                r['text'] = (f'Tool {part} quarantined in {self.net}: {", ".join(sorted(published[part]))} '
                             f'report{"s" if len(published[part]) == 1 else ""} a contract conflict this server '
                             f'cannot see (export rules show the differing offer only to some members).')
            r['reported_by'] = sorted(published.get(part, []))
            r['observed'] = part in observed
            quarantined[part] = r
        before = self.kv.get('quarantine') or {}
        for part in sorted(set(quarantined) - set(before)):
            r = quarantined[part]
            r['since'] = crypto.rfc3339(self.clock())
            logger.error(f'SAJHA Net {self.net}: {r["text"]}')
            self.count('quarantined')
            self.node.event('tool_quarantined', tool=part, report=r)
        for part in sorted(set(before) - set(quarantined)):
            change = self._why_lifted(part, before[part])
            text = f'Tool {part} active again in {self.net}: {change["text"]}'
            logger.warning(f'SAJHA Net {self.net}: {text}')
            self.node.event('tool_reactivated', tool=part, change=change['change'], text=text,
                            previous=before[part])
        for part in quarantined:
            if part in before:
                quarantined[part]['since'] = before[part].get('since') or quarantined[part].get('since')
        if quarantined != before:
            self.kv.set('quarantine', quarantined)
        return quarantined

    def _why_lifted(self, part: str, report: Dict[str, Any]) -> Dict[str, str]:
        """``fixed``, ``withdrawn``, ``left``, ``dead`` (§10.7 reporting), naming the hosts concerned."""
        offers = {o['instance']: o['contract_hash'] for o in (self.offers().get(part) or [])}
        odd = report.get('differing') or [o['instance'] for o in report.get('offers') or []]
        states = {m['name']: m['state'] for m in self.node.members()}
        for inst in odd:
            if inst == self.node.name:
                if inst not in offers:
                    return {'change': 'withdrawn', 'text': f'this server no longer exports {part}'}
                continue
            st = states.get(inst)
            if st in ('dead', 'left'):
                return {'change': st, 'text': f'{inst} is {st}'}
            if st is None:
                return {'change': 'dead', 'text': f'{inst} is no longer a member'}
            if inst not in offers:
                return {'change': 'withdrawn', 'text': f'{inst} no longer offers it'}
        return {'change': 'fixed', 'text': 'every host offering it now offers one contract'}

    def quarantined(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.kv.get('quarantine') or {})

    def is_quarantined(self, tool: str) -> Optional[Dict[str, Any]]:
        return self.quarantined().get(names.tool_part(tool))

    # ── the host and tool table (design §8.4) ──────────────────────

    def rows(self) -> List[Dict[str, Any]]:
        """Live remote entries of this net (the host and tool table's rows without resolution)."""
        q = self.quarantined()
        out = []
        for peer, held in sorted(self.live_peers().items()):
            level, _pinned = self.trust_of(peer)
            for e in held.get('tools') or []:
                state = e.get('state', 'active')
                if state == 'active' and not self._offer_allowed(peer, e['name']):
                    state = 'blocked'
                if state == 'active' and e['part'] in q:
                    state = 'quarantined'
                if state == 'active' and held['state'] == 'suspect':
                    state = 'unavailable'
                try:
                    qn = names.qualified_name(self.net, peer, e['name'])
                except names.NameError_:
                    continue
                out.append({'qualified_name': qn, 'net': self.net, 'host_instance': peer, 'host_tool': e['name'],
                            'part': e['part'], 'version': e.get('version') or '', 'contract_hash': e['contract_hash'],
                            'description_hash': e['description_hash'], 'trust': level, 'state': state,
                            'problem': e.get('problem'), 'first_seen': held.get('first_seen'),
                            'last_seen': held.get('pulled_at'), 'entry': e, 'member': held['member']})
        return out

    def status(self) -> Dict[str, Any]:
        live = self.live_peers()
        return {'net': self.net, 'own_digest': self.own_digest(), 'exported': len(self.exports(None)),
                'peers': {p: {'tools': len(h.get('tools') or []), 'hash': h.get('hash'), 'flags': h.get('flags') or [],
                              'state': h['state'], 'pulled_at': crypto.rfc3339(h['pulled_at']) if h.get('pulled_at')
                              else None} for p, h in live.items()},
                'conflicts_version': int((self.kv.get('conf_doc') or {}).get('version') or 0),
                'quarantined': {k: {kk: v for kk, v in r.items() if kk != 'groups'}
                                for k, r in self.quarantined().items()},
                'counters': dict(self.counters)}
