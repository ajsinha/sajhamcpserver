"""
Names, resolution, forwarded calls and waterfall fallback (protocol §5.3, §15, §16, §17;
design §8.2, §8.4, §9, §9.1, §14, §15).

* :class:`Router` spans every net of a participant, in configured order. It resolves a **qualified
  name** (``<net>__<prefix>__<tool part>``: exactly that host, never elsewhere) and a **plain name**
  (the local tool; else the tool's preference list ``sajhanet.preferences``; else the nets in order,
  each ordered by the routing strategy), keeps the reason for every place and for every host that
  is not eligible (``suspect``, ``blocked``, ``quarantined``, ``import rule``, ``other contract``,
  ``held``, ``invalid``), and forwards ``tools/call`` to the chosen host as a signed MCP request with
  the hop headers and the identity headers of the :class:`~sajha.net.plugins.IdentityResolver`.
  A call by plain name falls back to the next eligible host, at most ``max_fallbacks`` times, only
  after an availability failure that was certainly not executed, or, after one that may have been,
  for read-only or idempotent non-destructive tools (§15.8). Each peer has its own breaker, rate
  limit and timeout (design §15).
* :class:`HostServer` serves signed requests to the MCP endpoint (§15.4): verification, version,
  blocks, hops, identity, the remote user's block, the tool's block, export rules (and the one name,
  one contract quarantine), then the host's own access, policy and execution through a callback, and
  a signed answer. Every refusal before execution carries ``executed: false``.

Rule names asked of the :class:`~sajha.net.plugins.RuleEvaluator` (stream D implements them; the
shipped ``allow_all`` allows everything): ``import`` (net, host, tool, user), ``block_peer`` (net, peer,
direction), ``service_call`` (net, peer), ``block_user`` (net, peer, user), ``block_tool`` (net, peer,
tool), ``export`` (net, peer, tool, user), ``residency_offer`` (net, host, tool, user, definition: may the
tool be offered at all), ``residency_arguments`` and ``residency_result`` (net, host, tool, user, and the
arguments or result; a decision's ``value`` replaces them, redacted), ``reexport`` (net, peer, tool, user,
origin, source: may this caller use a tool this participant re-exports, §16). A decision's ``reason``
becomes the refusal reason when it is a protocol reason.

Re-export (§16): a call to a candidate whose catalog entry names an ``origin`` tells the identity resolver
(``user['_origin']``), which then sends a user assertion with ``aud`` = origin; an intermediary relays the
caller's assertion unchanged (``relay`` on :meth:`Router.call`) and never a raw key. Hop count and visited
list continue, and the home refuses a chain that would revisit the origin (``loop``).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import copy
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.net import EXTENSION_ID, crypto, httpsig, names, sfv
from sajha.net.catalog import CatalogBook, is_safe_to_repeat
from sajha.net.errors import (NetError, RPC_AUTHORIZATION, RPC_BLOCKED, RPC_HOP, RPC_IDENTITY, RPC_IMPORT,
                              RPC_PEER, RPC_RESIDENCY, RPC_UNAVAILABLE, RPC_VERSION)
from sajha.net.plugins import (AllowAll, HostOption, IdentityResolver, LocalFirst, NoIdentity, PeerResponse,
                               PeerUnreachable, RoutingStrategy, RuleEvaluator)

logger = logging.getLogger(__name__)

MODERN = '2026-07-28'
MAX_HOPS_CAP = 8
MAX_CHAIN_CAP = 32                 # hops plus nesting depth, end to end (§16)
MAX_MCP_BODY = 8 * 1024 * 1024
AVAILABILITY = ('unreachable', 'circuit_open', 'unavailable', 'rate_limited', 'draining', 'overloaded', 'no_host')
RETRYABLE = ('timeout', 'unreachable', 'rate_limited', 'draining', 'overloaded')

#: reason -> JSON-RPC code (§17.1); contract_conflict is -32011 at a host and -32018 at a home
CODES: Dict[str, int] = {}
for _c, _rs in ((RPC_AUTHORIZATION, ('export', 'access', 'policy', 'approval_required', 'remote_admin')),
                (RPC_RESIDENCY, ('residency_arguments', 'residency_result')),
                (RPC_IDENTITY, ('key_unknown', 'key_disabled', 'key_expired', 'key_revoked', 'key_not_from_home',
                                'no_account', 'assertion_invalid', 'token_invalid', 'https_required', 'anonymous',
                                'ambiguous_credentials')),
                (RPC_BLOCKED, ('instance', 'inbound', 'outbound', 'tool', 'user')),
                (RPC_HOP, ('hop_limit', 'loop', 'hop_inconsistent', 'chain_limit')),
                (RPC_VERSION, ('unsupported_version',)),
                (RPC_IMPORT, ('import',)),
                (RPC_UNAVAILABLE, ('draining', 'overloaded', 'rate_limited', 'unreachable', 'timeout', 'circuit_open',
                                   'unavailable', 'response_invalid', 'no_host'))):
    for _r in _rs:
        CODES[_r] = _c

SAFE_WORDS = {
    'export': 'the tool is not offered to you there', 'access': 'you do not have access to the tool there',
    'policy': 'a policy rule refused the call', 'approval_required': 'the call needs approval there',
    'contract_conflict': 'the tool is quarantined because its hosts disagree on its contract',
    'import': 'this server does not import the tool for you', 'no_account': 'you have no account there',
    'hop_limit': 'the call passed through too many servers', 'loop': 'the call would loop between servers',
    'chain_limit': 'the call chain is too long (servers passed plus tools nested in one another)',
    'unreachable': 'the server could not be reached', 'timeout': 'the server did not answer in time',
    'circuit_open': 'the server is failing and calls to it are paused', 'unavailable': 'the server is unavailable',
    'no_host': 'no server offering the tool is available', 'rate_limited': 'too many calls; try again shortly',
    'draining': 'the server is shutting down', 'overloaded': 'the server is overloaded',
    'response_invalid': 'the server\'s answer could not be verified', 'anonymous': 'the call needs a signed-in user',
    'https_required': 'your key may travel only over HTTPS',
    'assertion_invalid': 'the identity assertion for you was not accepted there',
    'token_invalid': 'the token for you was not accepted there',
    'residency_arguments': 'the arguments carry data that may not go to that server (data residency); '
                           'use a tool on a server where the data may go',
    'residency_result': 'the result carries data that may not come to this server (data residency)',
}


class HostRefusal(Exception):
    """A refusal by the host's own checks (access, policy, approvals, residency) from the execute callback."""

    def __init__(self, reason: str, message: str = '', executed: bool = False, code: Optional[int] = None,
                 **extra: Any):
        super().__init__(message or reason)
        self.reason = reason
        self.message = message or SAFE_WORDS.get(reason, reason)
        self.executed = executed
        self.code = code or CODES.get(reason, RPC_AUTHORIZATION)
        self.extra = extra                 # more members of data["io.sajha/net"] (a relayed refusal: ``refused_by``)


def refusal(code: int, reason: str, side: str, net: str, instance: str, tool: str = '', trace_id: str = '',
            executed: Optional[bool] = False, message: str = '', **extra) -> Dict[str, Any]:
    """A JSON-RPC ``error`` object for a net refusal (§17.1)."""
    data: Dict[str, Any] = {'reason': reason, 'side': side, 'net': net, 'instance': instance}
    if tool:
        data['tool'] = tool
    if trace_id:
        data['trace_id'] = trace_id
    if executed is not None:
        data['executed'] = bool(executed)
    data['retryable'] = reason in RETRYABLE
    for k, v in extra.items():
        if v is not None:
            data[k] = v
    return {'code': code, 'message': message or f'Refused by {instance}: {SAFE_WORDS.get(reason, reason)}',
            'data': {EXTENSION_ID: data}}


def _decide(rules: RuleEvaluator, rule: str, subject: Dict[str, Any]):
    """The rule evaluator's whole decision (residency may carry a redacted ``value``); refuse on error."""
    try:
        return rules.decide(rule, subject)
    except Exception as e:
        logger.warning(f'SAJHA Net rule {rule}: {e}')
        from sajha.net.plugins import Decision
        return Decision(False, rule)


def new_traceparent(trace_id: Optional[str] = None) -> str:
    return f'00-{trace_id or secrets.token_hex(16)}-{secrets.token_hex(8)}-01'


def trace_of(traceparent: Optional[str]) -> Optional[str]:
    parts = (traceparent or '').split('-')
    if len(parts) == 4 and len(parts[1]) == 32 and all(c in '0123456789abcdef' for c in parts[1]):
        return parts[1]
    return None


# ── per-peer isolation (design §15) ────────────────────────────────

class PeerBreaker:
    """Closed → open after ``threshold`` consecutive availability failures; half-open after ``reset``."""

    def __init__(self, threshold: int = 5, reset_seconds: float = 30.0, clock: Callable[[], float] = time.time):
        self.threshold, self.reset, self.clock = threshold, reset_seconds, clock
        self.failures = 0
        self.opened_at: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return 'closed'
        return 'half_open' if self.clock() - self.opened_at >= self.reset else 'open'

    def allow(self) -> bool:
        return self.state != 'open'

    def success(self) -> None:
        with self._lock:
            self.failures, self.opened_at = 0, None

    def failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold or self.opened_at is not None:
                self.opened_at = self.clock()


class PeerWindow:
    """A per-peer calls-per-minute window (sliding)."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.time):
        self.per_minute, self.clock = per_minute, clock
        self.calls: List[float] = []
        self._lock = threading.Lock()

    def take(self) -> bool:
        if self.per_minute <= 0:
            return True
        with self._lock:
            now = self.clock()
            self.calls = [t for t in self.calls if now - t < 60]
            if len(self.calls) >= self.per_minute:
                return False
            self.calls.append(now)
            return True


@dataclass
class PeerSettings:
    timeout_seconds: float = 30.0
    breaker_threshold: int = 5
    breaker_reset_seconds: float = 30.0
    calls_per_minute: int = 600


class CallPaths:
    """Observed call paths of one participant, per process (the topology view's ``calls`` edges):
    ``(net, from, to) -> {calls, tools}``. Kept per process on purpose, like metrics."""

    MAX_EDGES = 2000

    def __init__(self):
        self._edges: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def add(self, net: str, frm: str, to: str, tool: str) -> None:
        if not frm or not to or frm == to:
            return
        with self._lock:
            e = self._edges.get((net, frm, to))
            if e is None:
                if len(self._edges) >= self.MAX_EDGES:
                    return
                e = self._edges[(net, frm, to)] = {'calls': 0, 'tools': set()}
            e['calls'] += 1
            if len(e['tools']) < 200:
                e['tools'].add(tool)

    def add_chain(self, net: str, visited: List[str], me: str, tool: str) -> None:
        """Every step of a chain that reached ``me`` in ``net`` (steps through other nets are left out)."""
        steps = [str(v) for v in visited or []] + [f'{net}/{me}']
        for a, b in zip(steps, steps[1:]):
            na, _, ia = a.partition('/')
            nb, _, ib = b.partition('/')
            if na == net and nb == net:
                self.add(net, ia, ib, tool)

    def edges(self, net: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            return [{'net': n, 'from': f, 'to': t, 'calls': e['calls'], 'tools': sorted(e['tools'])}
                    for (n, f, t), e in sorted(self._edges.items()) if net is None or n == net]


def origin_of(row: Optional[Dict[str, Any]]) -> str:
    """The participant that really hosts a re-exported tool (its catalog entry's ``origin``), else ''."""
    return str((((row or {}).get('entry') or {}).get('meta') or {}).get('origin') or '')


# ── resolution ──────────────────────────────────────────────────────

@dataclass
class Candidate:
    """One host offering a tool (a row of the host and tool table)."""
    net: str
    host: str
    host_tool: str
    qualified_name: str
    part: str
    contract_hash: str
    state: str
    book: Any = None
    row: Dict[str, Any] = field(default_factory=dict)
    place: int = 0
    reason: str = ''
    eligible: bool = True
    why_not: str = ''

    @property
    def annotations(self) -> Dict[str, Any]:
        return dict((self.row.get('entry') or {}).get('annotations') or {})

    def public(self) -> Dict[str, Any]:
        out = {'net': self.net, 'host': self.host, 'qualified_name': self.qualified_name, 'state': self.state,
               'contract_hash': self.contract_hash}
        if self.eligible:
            out['place'] = self.place
            out['reason'] = self.reason
        else:
            out['not_eligible'] = self.why_not
        return out


@dataclass
class Resolution:
    name: str
    kind: str                                     # local | qualified | plain | unknown
    candidates: List[Candidate] = field(default_factory=list)
    skipped: List[Candidate] = field(default_factory=list)
    error: Optional[Tuple[int, str, str]] = None   # (code, reason, message)
    conflict: Optional[Dict[str, Any]] = None
    local: bool = False

    def public(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {'name': self.name, 'kind': self.kind,
                               'order': [c.public() for c in self.candidates],
                               'skipped': [c.public() for c in self.skipped]}
        if self.local:
            out['order'].insert(0, {'place': 1, 'reason': 'local'})
        if self.error:
            out['error'] = {'code': self.error[0], 'reason': self.error[1], 'message': self.error[2]}
        return out


class Router:
    """Every net of this participant, in configured order (see the module docstring)."""

    def __init__(self, books: List[CatalogBook], *, local_tools: Callable[[], List[str]] = lambda: [],
                 preferences: Optional[Dict[str, List[str]]] = None, routing: Optional[RoutingStrategy] = None,
                 bare_aliases: str = 'on', max_fallbacks: int = 3, default_timeout: float = 30.0,
                 identity: Optional[IdentityResolver] = None, rules: Optional[RuleEvaluator] = None,
                 peer: Optional[PeerSettings] = None, clock: Callable[[], float] = time.time,
                 audit: Optional[Callable[[str, Dict[str, Any]], None]] = None,
                 screen_result: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
                 max_hops: int = 1, max_chain: int = 8):
        self.books = list(books)
        self.local_tools = local_tools
        self.preferences = {str(k): [str(x) for x in (v or [])] for k, v in (preferences or {}).items()}
        self.routing = routing or LocalFirst()
        self.bare_aliases = str(bare_aliases).lower() if str(bare_aliases).lower() in ('on', 'preferences_only', 'off') \
            else ('on' if bare_aliases in (True, 'true', 'yes') else 'off')
        self.max_fallbacks = max(0, int(max_fallbacks))
        self.default_timeout = float(default_timeout)
        self.identity = identity or NoIdentity()
        self.rules = rules or AllowAll()
        self.peer = peer or PeerSettings()
        self.clock = clock
        self.audit = audit
        self.screen_result = screen_result
        self.max_hops = max(1, min(MAX_HOPS_CAP, int(max_hops)))
        self.max_chain = max(1, min(MAX_CHAIN_CAP, int(max_chain)))
        self._breakers: Dict[Tuple[str, str], PeerBreaker] = {}
        self._windows: Dict[Tuple[str, str], PeerWindow] = {}
        self._latency: Dict[Tuple[str, str], List[float]] = {}
        self.counters: Dict[Tuple[str, ...], int] = {}
        self.paths = CallPaths()
        self._lock = threading.Lock()
        self._ids = 0

    # ── helpers ────────────────────────────────────────────────────

    def book(self, net: str) -> Optional[CatalogBook]:
        return next((b for b in self.books if b.net == net), None)

    def count(self, *key: str) -> None:
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + 1

    def breaker(self, net: str, host: str) -> PeerBreaker:
        k = (net, host)
        with self._lock:
            if k not in self._breakers:
                self._breakers[k] = PeerBreaker(self.peer.breaker_threshold, self.peer.breaker_reset_seconds, self.clock)
            return self._breakers[k]

    def window(self, net: str, host: str) -> PeerWindow:
        k = (net, host)
        with self._lock:
            if k not in self._windows:
                self._windows[k] = PeerWindow(self.peer.calls_per_minute, self.clock)
            return self._windows[k]

    def latency_p50(self, net: str, host: str) -> Optional[float]:
        xs = sorted(self._latency.get((net, host)) or [])
        return xs[len(xs) // 2] if xs else None

    def _observe_latency(self, net: str, host: str, ms: float) -> None:
        with self._lock:
            xs = self._latency.setdefault((net, host), [])
            xs.append(ms)
            del xs[:-100]

    def _allowed(self, rule: str, subject: Dict[str, Any]) -> Tuple[bool, str]:
        try:
            d = self.rules.decide(rule, subject)
            return bool(d.allow), d.reason or rule
        except Exception as e:
            logger.warning(f'SAJHA Net rule {rule}: {e}')
            return False, rule

    # ── the host and tool table ────────────────────────────────────

    def rows(self) -> List[Dict[str, Any]]:
        out = []
        for b in self.books:
            out.extend(b.rows())
        return out

    def _candidates(self, part: str) -> List[Candidate]:
        out = []
        for b in self.books:
            for r in b.rows():
                if r['part'] == part:
                    out.append(Candidate(net=b.net, host=r['host_instance'], host_tool=r['host_tool'],
                                         qualified_name=r['qualified_name'], part=part,
                                         contract_hash=r['contract_hash'], state=r['state'], book=b, row=r))
        return out

    def local_quarantine(self, name: str) -> Optional[Dict[str, Any]]:
        """The conflict report when local tool ``name`` is exported into a net where its name is quarantined."""
        part = names.tool_part(name)
        for b in self.books:
            q = b.quarantined().get(part)
            if q and any(t['name'] == name for t in b.exports(None)):
                return q
        return None

    def aliases(self) -> Dict[str, List[str]]:
        """Plain names offered for remote tools -> qualified names in resolution order (design §8.2)."""
        if self.bare_aliases == 'off':
            return {}
        local = set(self.local_tools() or [])
        parts = sorted({r['part'] for r in self.rows()})
        out = {}
        for part in parts:
            if part in local:
                continue
            if self.bare_aliases == 'preferences_only' and part not in self.preferences:
                continue
            res = self.resolve(part)
            if res.candidates:
                out[part] = [c.qualified_name for c in res.candidates]
        return out

    def resolve(self, name: str, user: Optional[Dict[str, Any]] = None) -> Resolution:
        q = names.split_qualified(name)
        if q is not None and self.book(q[0]) is not None:
            return self._resolve_qualified(name, q, user)
        return self._resolve_plain(name, user)

    def _ineligible(self, c: Candidate, user) -> str:
        if c.state == 'unavailable':
            return 'suspect'
        if c.state != 'active':
            return {'quarantined': 'quarantined', 'blocked': 'blocked', 'held': 'held', 'hidden': 'pinned trust',
                    'invalid': 'invalid'}.get(c.state, c.state)
        ok, _ = self._allowed('import', {'net': c.net, 'host': c.host, 'tool': c.host_tool, 'user': user})
        if not ok:
            return 'import rule'
        ok, _ = self._allowed('residency_offer', {'net': c.net, 'host': c.host, 'tool': c.host_tool, 'user': user,
                                                  'qualified_name': c.qualified_name,
                                                  'entry': c.row.get('entry')})
        if not ok:
            return 'residency rule'                      # the data every call sends may not go there (§13)
        return ''

    def _resolve_qualified(self, name: str, q: Tuple[str, str, str], user) -> Resolution:
        net, prefix, part = q
        res = Resolution(name=name, kind='qualified')
        for c in self._candidates(part):
            if c.net != net:
                continue
            try:
                if names.safe_prefix(c.host) != prefix:
                    continue
            except names.NameError_:
                continue
            why = self._ineligible(c, user)
            if why == 'quarantined':
                res.conflict = c.book.quarantined().get(part)
                res.error = (RPC_IMPORT, 'contract_conflict', f'{part} is quarantined in {net}: its hosts disagree '
                                                              f'on its contract')
            elif why == 'suspect':
                res.error = (RPC_UNAVAILABLE, 'unavailable', f'{c.host} is unavailable')
            elif why == 'residency rule':
                res.error = (RPC_RESIDENCY, 'residency_arguments', f'{name}: the data it needs may not go to {c.host}')
            elif why in ('import rule', 'blocked', 'pinned trust', 'held', 'invalid'):
                res.error = (RPC_IMPORT, 'import', f'{name} is not available to you on this server')
            if why:
                c.eligible, c.why_not = False, why
                res.skipped.append(c)
            else:
                c.place, c.reason = 1, 'qualified name'
                res.candidates.append(c)
            return res
        res.kind = 'unknown'
        return res

    def _resolve_plain(self, name: str, user) -> Resolution:
        part = names.tool_part(name)
        res = Resolution(name=name, kind='plain')
        if name in set(self.local_tools() or []):
            res.kind, res.local = 'local', True
            lq = self.local_quarantine(name)
            if lq:
                res.conflict = lq
                res.error = (RPC_IMPORT, 'contract_conflict', f'{name} is quarantined: its hosts disagree on its '
                                                              f'contract')
            return res
        if self.bare_aliases == 'off' or (self.bare_aliases == 'preferences_only' and part not in self.preferences):
            res.kind = 'unknown'
            return res
        all_c = self._candidates(part)
        if not all_c:
            res.kind = 'unknown'
            return res
        ordered: List[Tuple[Candidate, str]] = []
        seen = set()

        def add(c: Candidate, reason: str):
            k = (c.net, c.host)
            if k not in seen:
                seen.add(k)
                ordered.append((c, reason))
        by_net: Dict[str, List[Candidate]] = {}
        for c in all_c:
            by_net.setdefault(c.net, []).append(c)

        def strategy(net: str, cs: List[Candidate]) -> List[Candidate]:
            opts = [HostOption(instance=c.host, latency_ms=self.latency_p50(net, c.host)) for c in cs]
            order = [o.instance for o in self.routing.order(part, opts)]
            return sorted(cs, key=lambda c: order.index(c.host) if c.host in order else len(order))
        for i, pref in enumerate(self.preferences.get(part) or self.preferences.get(name) or [], start=1):
            net, _, host = pref.partition('/')
            for c in strategy(net, by_net.get(net, [])):
                if not host or c.host == host:
                    add(c, f'preference {i}' + ('' if host else f' ({net}, by routing)'))
        n_pref = len(ordered)
        for net_i, b in enumerate(self.books, start=1):
            for j, c in enumerate(strategy(b.net, by_net.get(b.net, [])), start=1):
                add(c, f'net order: {b.net}, {_ordinal(j)} by routing')
        # a tool re-exported by an intermediary comes after every host offering it directly (§16)
        rest = ordered[n_pref:]
        ordered = ordered[:n_pref] + [x for x in rest if not origin_of(x[0].row)] + \
            [(c, f'{r}; re-exported by {c.host} from {origin_of(c.row)}') for c, r in rest if origin_of(c.row)]
        reference = None
        quarantined = None
        place = 0
        for c, reason in ordered:
            why = self._ineligible(c, None if user is None else user)
            if why == 'quarantined' and quarantined is None:
                quarantined = c.book.quarantined().get(part)
            if not why:
                if reference is None:
                    reference = c.contract_hash
                elif c.contract_hash != reference:
                    why = 'other contract'
            if why:
                c.eligible, c.why_not = False, why
                res.skipped.append(c)
            else:
                place += 1
                c.place, c.reason = place, reason
                res.candidates.append(c)
        if not res.candidates:
            if quarantined is not None and all(c.why_not in ('quarantined', 'other contract') for c in res.skipped):
                res.conflict = quarantined
                res.error = (RPC_IMPORT, 'contract_conflict', f'{name} is quarantined: its hosts disagree on its '
                                                              f'contract')
            elif any(c.why_not == 'suspect' for c in res.skipped):
                res.error = (RPC_UNAVAILABLE, 'no_host', f'no host offering {name} is available')
            elif any(c.why_not == 'residency rule' for c in res.skipped):
                res.error = (RPC_RESIDENCY, 'residency_arguments', f'{name}: the data it needs may not go to any '
                                                                    f'host offering it')
            elif quarantined is not None:
                res.conflict = quarantined
                res.error = (RPC_IMPORT, 'contract_conflict', f'{name} is quarantined: its hosts disagree on its '
                                                              f'contract')
            else:
                res.error = (RPC_IMPORT, 'import', f'{name} is not available to you on this server')
        return res

    # ── calls ──────────────────────────────────────────────────────

    def _home_result(self, res: Resolution, code: int, reason: str, message: str, trace_id: str,
                     attempts: Optional[List[Dict[str, Any]]] = None, net: str = '', tool: str = '',
                     first_refusal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        b = self.book(net) or (self.books[0] if self.books else None)
        if first_refusal is not None:
            data = dict(first_refusal)
        else:
            extra = {}
            if reason == 'contract_conflict' and res.conflict:
                extra['conflict'] = {'tool': res.conflict.get('tool'), 'offers': res.conflict.get('offers') or []}
            data = refusal(code, reason, 'home', net or (b.net if b else ''), b.node.name if b else '',
                           tool or res.name, trace_id, executed=False, message=message, **extra)['data'][EXTENSION_ID]
        meta: Dict[str, Any] = {'refusal': data}
        if attempts:
            meta['attempts'] = attempts
            data['attempt'] = len(attempts)
        side = 'This server' if data.get('side') == 'home' else (data.get('instance') or 'The host')
        text = f'{side} refused the call to {res.name}: {SAFE_WORDS.get(data.get("reason"), data.get("reason"))}.'
        if reason == 'contract_conflict' and res.conflict:
            text += ' ' + ' '.join(res.conflict.get('text', '').splitlines()[:1])
        return {'content': [{'type': 'text', 'text': text}], 'isError': True, '_meta': {EXTENSION_ID: meta}}

    def call(self, name: str, arguments: Dict[str, Any], *, user: Optional[Dict[str, Any]] = None,
             traceparent: Optional[str] = None, timeout: Optional[float] = None,
             hop_in: Optional[Tuple[int, List[str]]] = None, depth: int = 0,
             relay: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Call ``name`` (qualified or plain) at its host(s); always returns a CallToolResult. ``hop_in``
        is the chain a call made while serving a forwarded call arrived on (hop count, visited list);
        ``depth`` the tools nested in one another so far on every instance passed (§16). ``relay``: the
        identity headers to send instead of the resolver's (an intermediary relaying a re-exported call
        forwards the caller's user assertion unchanged, §16)."""
        res = self.resolve(name, user)
        tp = traceparent if trace_of(traceparent) else new_traceparent()
        trace_id = trace_of(tp)
        if res.kind == 'local' and not res.error:
            raise LookupError(f'{name} is a local tool')
        if res.kind == 'unknown' and not res.error:
            res.error = (RPC_UNAVAILABLE, 'no_host', f'no host offers {name} now')
        if res.error and not res.candidates:
            code, reason, message = res.error
            self.count('calls', reason)
            self._audit('net.call', {'name': name, 'trace_id': trace_id, 'outcome': reason, 'resolution': res.public()})
            return self._home_result(res, code, reason, message, trace_id)
        deadline = self.clock() + float(timeout or self.default_timeout)
        attempts: List[Dict[str, Any]] = []
        first_refusal: Optional[Dict[str, Any]] = None
        tries = res.candidates[:1 + (self.max_fallbacks if res.kind == 'plain' else 0)]
        for i, c in enumerate(tries, start=1):
            if i > 1 and self.clock() >= deadline:
                break
            outcome = self._attempt(c, arguments, user, tp, trace_id, i, deadline, hop_in, depth, relay)
            outcome['attempt'] = i
            attempts.append({k: outcome[k] for k in ('attempt', 'net', 'host', 'qualified_name', 'outcome', 'executed')
                             if k in outcome})
            self._audit('net.call_attempt', {'name': name, 'trace_id': trace_id, 'attempt': i, 'net': c.net,
                                             'host': c.host, 'qualified_name': c.qualified_name,
                                             'reason': c.reason, 'outcome': outcome['outcome'],
                                             'executed': outcome.get('executed'),
                                             'identity': outcome.get('identity'),
                                             'origin': origin_of(c.row) or None,
                                             'relayed': bool(relay) or None,
                                             'remote_usage': _remote_usage(outcome.get('result'))})
            if outcome['outcome'] == 'answered':
                self.count('calls', 'answered')
                self.paths.add(c.net, c.book.node.name, c.host, c.host_tool)
                if i > 1:
                    self.count('fallbacks', 'answered')
                result = outcome['result']
                meta = dict((result.get('_meta') or {}).get(EXTENSION_ID) or {})
                meta.update(net=c.net, instance=c.host, qualified_name=c.qualified_name, trace_id=trace_id)
                if len(attempts) > 1:
                    meta['attempts'] = attempts
                result = dict(result, _meta=dict(result.get('_meta') or {}, **{EXTENSION_ID: meta}))
                return result
            if first_refusal is None:
                first_refusal = outcome.get('refusal')
            if i > 1:
                self.count('fallbacks', outcome['outcome'])
            if res.kind != 'plain':
                break
            availability = outcome['outcome'] in AVAILABILITY and outcome.get('executed') is False
            maybe = outcome.get('executed') is not False
            home_residency = outcome['outcome'] == 'residency_arguments' and \
                (outcome.get('refusal') or {}).get('side') == 'home'   # the next host may receive the data
            if outcome['outcome'] == 'loop' and (outcome.get('refusal') or {}).get('side') == 'home':
                continue                                   # that host already served this chain: the next may not
            if i == 1 and not availability and not maybe and not home_residency:
                break                                      # a refusal by the first host is its answer (§15.8 rule 2)
            if maybe and not is_safe_to_repeat(c.annotations):
                break                                      # may have run: never repeat a destructive tool (rule 3)
        self.count('calls', 'refused')
        if first_refusal is None:
            first_refusal = refusal(RPC_UNAVAILABLE, 'no_host', 'home', res.candidates[0].net,
                                    res.candidates[0].book.node.name, name, trace_id)['data'][EXTENSION_ID]
        return self._home_result(res, 0, '', '', trace_id, attempts, first_refusal=first_refusal)

    def _audit(self, what: str, details: Dict[str, Any]) -> None:
        if self.audit is not None:
            try:
                self.audit(what, details)
            except Exception as e:
                logger.debug(f'SAJHA Net audit {what}: {e}')

    def _attempt(self, c: Candidate, arguments, user, tp: str, trace_id: str, attempt: int, deadline: float,
                 hop_in, depth: int = 0, relay: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        out = self._attempt_once(c, arguments, user, tp, trace_id, attempt, deadline, hop_in, depth, relay)
        forget = getattr(self.identity, 'forget', None)
        if out.get('outcome') == 'token_invalid' and relay is None and callable(forget) and \
                (out.get('refusal') or {}).get('side') == 'host' and self.clock() < deadline:
            try:
                forget(c.net, c.host, user)                 # a host-scoped token the host no longer knows
            except Exception as e:
                logger.debug(f'SAJHA Net: forgetting the token for {c.host}: {e}')
            out = self._attempt_once(c, arguments, user, tp, trace_id, attempt, deadline, hop_in, depth, relay)
        return out

    def _attempt_once(self, c: Candidate, arguments, user, tp: str, trace_id: str, attempt: int, deadline: float,
                      hop_in, depth: int = 0, relay: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        book = c.book
        node = book.node
        out: Dict[str, Any] = {'net': c.net, 'host': c.host, 'qualified_name': c.qualified_name}

        def home(reason: str, executed: Optional[bool] = False, **extra) -> Dict[str, Any]:
            out.update(outcome=reason, executed=executed,
                       refusal=refusal(CODES.get(reason, RPC_UNAVAILABLE), reason, 'home', c.net, node.name,
                                       c.qualified_name, trace_id, executed=executed, **extra)['data'][EXTENSION_ID])
            return out
        m = node.member(c.host)
        if m is None or m['state'] not in ('alive',):
            return home('unavailable')
        d = _decide(self.rules, 'residency_arguments', {'net': c.net, 'host': c.host, 'tool': c.host_tool, 'user': user,
                                                         'arguments': arguments, 'qualified_name': c.qualified_name,
                                                         'entry': c.row.get('entry'),
                                                         'trace_id': trace_id})
        if not d.allow:
            return home('residency_arguments')
        if isinstance(d.value, dict):
            arguments = d.value                              # fields of a class that may not go there, redacted
        br = self.breaker(c.net, c.host)
        if not br.allow():
            return home('circuit_open')
        if not self.window(c.net, c.host).take():
            return home('rate_limited')
        hop, visited = 1, []
        if hop_in:
            hop, visited = int(hop_in[0]) + 1, list(hop_in[1])
        visited.append(f'{c.net}/{node.name}')
        depth = max(0, int(depth or 0))
        origin = origin_of(c.row)
        if f'{c.net}/{c.host}' in visited or (origin and f'{c.net}/{origin}' in visited):
            return home('loop', hops=hop)                # the host (or the origin) already served this chain
        if hop > self.max_hops and hop_in:
            return home('hop_limit', hops=hop, limit=self.max_hops)
        if hop + depth > self.max_chain:
            return home('chain_limit', hops=hop, depth=depth, limit=self.max_chain)
        url = m['record']['url'].rstrip('/')
        try:
            if relay is not None:
                ident = dict(relay)                      # the caller's assertion, unchanged (§16)
                out['identity'] = 'relayed'
            else:
                if isinstance(user, dict):
                    user['_target'] = (c.net, c.host)    # lets the resolver pick a key configured for this member
                    user['_origin'] = origin or None     # a re-exported tool: an assertion for its origin
                    user['_trace_id'] = trace_id
                    user.pop('_identity', None)
                ident = self.identity.outbound_headers(user) or {}
                if isinstance(user, dict) and user.get('_identity'):
                    out['identity'] = user['_identity']
        except NetError as e:
            return home(e.reason)
        ident = httpsig.lower_headers(ident)
        if (origin or relay is not None) and 'sajha-net-api-key' in ident:
            return home('assertion_invalid')             # a re-exported call never carries a raw key (§16)
        if 'sajha-net-api-key' in ident and not url.startswith('https://') and node.cfg.require_https:
            return home('https_required')
        my_tp = new_traceparent(trace_id)
        with self._lock:
            self._ids += 1
            rid = self._ids
        meta = {'home': node.name, 'qualified_name': c.qualified_name}
        if attempt > 1:
            meta['attempt'] = attempt
        if depth:
            meta['depth'] = depth
        body = {'jsonrpc': '2.0', 'id': rid, 'method': 'tools/call',
                'params': {'name': c.host_tool, 'arguments': arguments,
                           '_meta': {'io.modelcontextprotocol/protocolVersion': MODERN, 'traceparent': my_tp,
                                     EXTENSION_ID: meta}}}
        raw = json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        headers = {'content-type': 'application/json', 'accept': 'application/json, text/event-stream',
                   'mcp-protocol-version': MODERN, 'mcp-method': 'tools/call', 'mcp-name': c.host_tool,
                   'sajha-net-hop': str(hop), 'sajha-net-visited': sfv.ser_list([(v, {}) for v in visited]),
                   'traceparent': my_tp}
        headers.update(ident)
        path = m['record'].get('mcp_path') or '/mcp'
        signed = httpsig.sign_request(node.signer, 'POST', path, '', headers, raw, c.net, node.name, c.host, mcp=True,
                                      now=node.clock())
        req_sig = httpsig.request_signature_bytes(signed)
        remaining = max(0.05, min(self.peer.timeout_seconds, deadline - self.clock()))
        t0 = time.perf_counter()
        try:
            r = node.connector.send('POST', url + path, signed, raw, remaining)
        except PeerUnreachable as e:
            br.failure()
            if getattr(e, 'sent', False):
                return home('timeout', executed=None)
            return home('unreachable')
        self._observe_latency(c.net, c.host, (time.perf_counter() - t0) * 1000)
        if 'signature' not in {k.lower() for k in r.headers}:
            br.failure()
            return home('response_invalid' if r.status < 500 else 'unreachable', executed=None)
        try:
            v = httpsig.verify_response(node.trust, node.name, c.host, r.status, r.headers, r.body, req_sig,
                                        now=node.clock(), max_age=node.cfg.signature_max_age_seconds)
        except NetError:
            br.failure()
            return home('response_invalid', executed=None)
        try:
            msg = json.loads(r.body.decode('utf-8'))
        except ValueError:
            br.failure()
            return home('response_invalid', executed=None)
        if not isinstance(msg, dict):
            return home('response_invalid', executed=None)
        if isinstance(msg.get('result'), dict):
            br.success()
            result = msg['result']
            if self.screen_result is not None:
                try:
                    result = self.screen_result(result)
                except Exception as e:
                    logger.warning(f'SAJHA Net: result screening failed: {e}')
            out.update(outcome='answered', executed=True, result=result)
            return out
        err = msg.get('error') if isinstance(msg.get('error'), dict) else {}
        data = (err.get('data') or {}).get(EXTENSION_ID) if isinstance(err.get('data'), dict) else None
        if not isinstance(data, dict):
            out.update(outcome='error', executed=None,
                       refusal=refusal(int(err.get('code') or -32603), 'error', 'host', c.net, c.host, c.host_tool,
                                       trace_id, executed=None, message='the host failed the call')['data'][EXTENSION_ID])
            return out
        reason = str(data.get('reason') or 'error')
        executed = data.get('executed') if isinstance(data.get('executed'), bool) else None
        if reason in ('draining', 'overloaded', 'rate_limited'):
            br.failure() if reason != 'rate_limited' else None
        else:
            br.success()
        clean = {k: data[k] for k in ('reason', 'side', 'net', 'instance', 'tool', 'trace_id', 'executed', 'retryable',
                                      'conflict', 'refused_by') if k in data}
        out.update(outcome=reason, executed=executed, refusal=clean)
        return out


def _remote_usage(result: Any) -> Optional[Dict[str, Any]]:
    """The model spend a host reported for a remote LLM tool (charged there, recorded here for audit)."""
    if not isinstance(result, dict) or not isinstance(result.get('_meta'), dict):
        return None
    u = (result['_meta'].get(EXTENSION_ID) or {}).get('usage')
    return u if isinstance(u, dict) else None


def _ordinal(n: int) -> str:
    return f'{n}{"th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")}'


# ── host side (§15.4) ───────────────────────────────────────────────

@dataclass
class CallContext:
    net: str
    peer: str
    user: Optional[Dict[str, Any]]
    tool: str
    trace_id: str
    traceparent: str
    hop: int
    visited: List[str]
    home: str = ''
    qualified_name: str = ''
    attempt: int = 1
    key_id: str = ''
    depth: int = 0                 # tools nested in one another on the instances before this one (§16)
    relay: Dict[str, str] = field(default_factory=dict)        # the caller's assertion, for a re-exported call
    reexport: Optional[Dict[str, Any]] = None                   # the re-exported tool (with ``_source``), if any


class HostServer:
    """Serves signed requests to the MCP endpoint for one net (see the module docstring)."""

    def __init__(self, book: CatalogBook, *, execute: Callable[[CallContext, Dict[str, Any]], Dict[str, Any]],
                 identity: Optional[IdentityResolver] = None, rules: Optional[RuleEvaluator] = None,
                 max_hops: int = 1, own_identities: Callable[[], List[str]] = lambda: [], max_chain: int = 8,
                 other: Optional[Callable[[Dict[str, Any], Any], Dict[str, Any]]] = None,
                 calls_per_minute: int = 600, audit: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.book = book
        self.node = book.node
        self.execute = execute
        self.identity = identity or NoIdentity()
        self.rules = rules or AllowAll()
        self.max_hops = max(1, min(MAX_HOPS_CAP, int(max_hops)))
        self.max_chain = max(1, min(MAX_CHAIN_CAP, int(max_chain)))
        self.own_identities = own_identities
        self.other = other
        self.calls_per_minute = calls_per_minute
        self.audit = audit
        self.paths = CallPaths()
        self.draining = False
        self._windows: Dict[str, PeerWindow] = {}
        self._lock = threading.Lock()

    def attach(self) -> 'HostServer':
        self.node.mcp_server = self
        return self

    def _window(self, peer: str) -> PeerWindow:
        with self._lock:
            if peer not in self._windows:
                self._windows[peer] = PeerWindow(self.calls_per_minute, self.node.clock)
            return self._windows[peer]

    def _respond(self, status: int, msg: Dict[str, Any], req_headers: Dict[str, str], to: str,
                 extra: Optional[Dict[str, str]] = None) -> PeerResponse:
        raw = json.dumps(msg, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        h = {'content-type': 'application/json'}
        h.update(extra or {})
        try:
            req_sig = httpsig.request_signature_bytes(req_headers)
        except Exception:
            req_sig = None
        out = httpsig.sign_response(self.node.signer, status, h, raw, req_sig, self.node.net, self.node.name,
                                    to or httpsig.ANY, now=self.node.clock())
        out['cache-control'] = 'no-store'
        return PeerResponse(status, out, raw)

    def _err(self, rid, err: Dict[str, Any], h, to, status: int = 200, retry_after: Optional[int] = None):
        extra = {'retry-after': str(retry_after)} if retry_after else None
        return self._respond(status, {'jsonrpc': '2.0', 'id': rid, 'error': err}, h, to, extra)

    def _allowed(self, rule: str, subject: Dict[str, Any]) -> Tuple[bool, str]:
        try:
            d = self.rules.decide(rule, subject)
            return bool(d.allow), d.reason or ''
        except Exception as e:
            logger.warning(f'SAJHA Net rule {rule}: {e}')
            return False, ''

    def __call__(self, method: str, path: str, query: str, h: Dict[str, str], body: bytes, secure: bool = True,
                 source: str = '') -> PeerResponse:
        node = self.node
        net, me = node.net, node.name
        claimed = h.get('sajha-net-from', '').strip()
        try:
            msg = json.loads((body or b'').decode('utf-8')) if body else None
        except ValueError:
            msg = None
        rid = msg.get('id') if isinstance(msg, dict) else None
        if method.upper() != 'POST' or len(body or b'') > MAX_MCP_BODY:
            return self._err(rid, refusal(RPC_PEER, 'invalid_request', 'host', net, me, executed=False,
                                          message='a forwarded request is a POST within the size limits'),
                             h, claimed, 405 if method.upper() != 'POST' else 413)
        # 1, 2: verification and version (§8.7)
        try:
            v = httpsig.verify_request(node.trust, me, 'POST', path, query, h, body or b'', mcp=True,
                                       now=node.clock(), max_age=node.cfg.signature_max_age_seconds,
                                       seen_nonce=node._seen_nonce)
        except NetError as e:
            code = RPC_VERSION if e.reason == 'unsupported_version' else RPC_PEER
            extra = {'supported_versions': [1]} if e.reason == 'unsupported_version' else {}
            return self._err(rid, refusal(code, e.reason, 'host', net, me, executed=False,
                                          message=f'Refused by {me}: {e.detail}', **extra), h, claimed, e.status)
        holder = node.lineage_conflict(v.sender, v.certificate)
        if holder is not None:
            return self._err(rid, refusal(RPC_PEER, 'name_conflict', 'host', net, me, executed=False), h, v.sender, 409)
        if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0' or not isinstance(msg.get('method'), str):
            return self._respond(400, {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32600,
                                                                              'message': 'invalid JSON-RPC request'}},
                                 h, v.sender)
        mth = msg['method']
        if mth == 'tools/list':
            tools = [t for t in self.book.exports(v.sender)]
            return self._respond(200, {'jsonrpc': '2.0', 'id': rid, 'result': {'tools': tools}}, h, v.sender)
        if mth != 'tools/call':
            if self.other is not None:
                return self._respond(200, self.other(msg, v), h, v.sender)
            return self._respond(200, {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601,
                                                                              'message': f'{mth} is not served to '
                                                                                         f'net peers'}}, h, v.sender)
        params = msg.get('params') if isinstance(msg.get('params'), dict) else {}
        tool = str(params.get('name') or '')
        arguments = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
        tp = h.get('traceparent') or (params.get('_meta') or {}).get('traceparent') or ''
        trace_id = trace_of(tp) or ''
        nmeta = ((params.get('_meta') or {}).get(EXTENSION_ID)) or {}

        def no(reason: str, status: int = 200, retry_after: Optional[int] = None, executed: bool = False, **extra):
            code = RPC_AUTHORIZATION if reason == 'contract_conflict' else CODES.get(reason, RPC_AUTHORIZATION)
            self._log('net.host_refused', v.sender, tool, trace_id, reason, executed)
            return self._err(rid, refusal(code, reason, 'host', net, me, tool, trace_id, executed=executed, **extra),
                             h, v.sender, status, retry_after)
        if self.draining:
            return no('draining', 503, 30)
        if not self._window(v.sender).take():
            return no('rate_limited', 429, 60)
        # 3: blocks on the sending participant
        ok, why = self._allowed('block_peer', {'net': net, 'peer': v.sender, 'direction': 'inbound'})
        if not ok:
            return no(why if why in ('instance', 'inbound') else 'inbound')
        # 4: hops and loops (§16)
        try:
            hop = int(sfv.parse_item(h.get('sajha-net-hop', ''))[0])
            visited = [str(x) for x, _p in sfv.parse_list(h.get('sajha-net-visited', ''))]
        except Exception:
            return no('hop_inconsistent')
        if hop > self.max_hops:
            return no('hop_limit')
        mine = {f'{net}/{me}'} | set(self.own_identities() or [])
        if any(x in mine for x in visited):
            return no('loop')
        if hop < 1 or len(visited) != hop or visited[-1] != f'{net}/{v.sender}':
            return no('hop_inconsistent')
        depth = nmeta.get('depth', 0) if isinstance(nmeta, dict) else 0
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            return no('hop_inconsistent')
        if hop + depth > self.max_chain:
            return no('chain_limit')
        # a re-exported tool (§16): the caller's assertion names its origin as the audience
        rx = self.book.reexport_of(tool, v.sender) if getattr(self.book, 'reexport', False) else None
        rx_origin = str(((rx or {}).get('_net') or {}).get('origin') or '')
        # 5: identity (§15.3, §15.5, §15.9)
        if 'authorization' in h or 'x-api-key' in h:
            return no('ambiguous_credentials')
        try:
            import inspect
            params = inspect.signature(self.identity.resolve).parameters
            offer = {'secure': secure, 'audience': rx_origin or me, 'hop': hop, 'visited': list(visited),
                     'trace_id': trace_id}
            if any(p.kind == p.VAR_KEYWORD for p in params.values()):
                kw = offer
            else:
                kw = {k: val for k, val in offer.items() if k in params}
            user = self.identity.resolve(h, v.sender, **kw)
        except NetError as e:
            return no(e.reason if e.reason in CODES else 'no_account')
        if user is None:
            ok, _ = self._allowed('service_call', {'net': net, 'peer': v.sender})
            if not ok:
                return no('anonymous')
        # 6: block on the remote user
        if user is not None:
            ok, _ = self._allowed('block_user', {'net': net, 'peer': v.sender, 'user': user})
            if not ok:
                return no('user')
        # 8: block on the tool
        ok, _ = self._allowed('block_tool', {'net': net, 'peer': v.sender, 'tool': tool})
        if not ok:
            return no('tool')
        # 9: export rules for this peer and user, and the one name, one contract quarantine
        exported = {t['name'] for t in self.book.exports(v.sender)}
        if tool not in exported:
            return no('export')
        if rx is not None:                               # re-export rules, not export rules (§16)
            ok, _ = self._allowed('reexport', {'net': net, 'peer': v.sender, 'tool': tool, 'user': user,
                                               'origin': rx_origin or None, 'source': rx.get('_source')})
        else:
            ok, _ = self._allowed('export', {'net': net, 'peer': v.sender, 'tool': tool, 'user': user})
        if not ok:
            return no('export')
        q = self.book.is_quarantined(tool)
        if q:
            return no('contract_conflict', conflict={'tool': q.get('tool'), 'offers': q.get('offers') or []})
        ctx = CallContext(net=net, peer=v.sender, user=user, tool=tool, trace_id=trace_id, traceparent=tp, hop=hop,
                          visited=visited, home=str(nmeta.get('home') or ''),
                          qualified_name=str(nmeta.get('qualified_name') or ''),
                          attempt=int(nmeta.get('attempt') or 1) if str(nmeta.get('attempt') or 1).isdigit() else 1,
                          key_id=str((user or {}).get('key_id') or ''), depth=depth,
                          relay={'Sajha-Net-User-Assertion': h['sajha-net-user-assertion']}
                          if h.get('sajha-net-user-assertion') else {}, reexport=rx)
        # 10, 11: the host's own access, policy and approvals; execution
        try:
            result = self.execute(ctx, arguments)
        except HostRefusal as e:
            return no(e.reason, executed=e.executed, **(getattr(e, 'extra', None) or {}))
        # 12: residency of the result
        d = _decide(self.rules, 'residency_result', {'net': net, 'host': me, 'peer': v.sender, 'tool': tool,
                                                      'user': user, 'result': result, 'trace_id': trace_id})
        if not d.allow:
            return no('residency_result', executed=True)
        result = dict(d.value if isinstance(d.value, dict) else (result or {}))
        rm = dict((result.get('_meta') or {}).get(EXTENSION_ID) or {})
        rm.setdefault('instance', me)
        result['_meta'] = dict(result.get('_meta') or {}, **{EXTENSION_ID: rm})
        self._log('net.host_call', v.sender, tool, trace_id, 'error' if result.get('isError') else 'ok', True,
                  ctx=ctx)
        self.paths.add_chain(net, visited, me, tool)
        return self._respond(200, {'jsonrpc': '2.0', 'id': rid, 'result': result}, h, v.sender)

    def _log(self, what: str, peer: str, tool: str, trace_id: str, outcome: str, executed: bool, ctx=None) -> None:
        if self.audit is None:
            return
        try:
            d = {'net': self.node.net, 'peer': peer, 'tool': tool, 'trace_id': trace_id, 'outcome': outcome,
                 'executed': executed}
            if ctx is not None:
                d.update(home=ctx.home, qualified_name=ctx.qualified_name, attempt=ctx.attempt, key_id=ctx.key_id,
                         user=(ctx.user or {}).get('name') if ctx.user else None,
                         identity=(ctx.user or {}).get('identity') if ctx.user else None,
                         mapping=(ctx.user or {}).get('mapping') if ctx.user else None,
                         hop=ctx.hop, visited=list(ctx.visited))
                if ctx.reexport is not None:
                    d['reexport'] = {'origin': ((ctx.reexport.get('_net') or {}).get('origin')),
                                     'source': (ctx.reexport.get('_source') or {}).get('qualified_name')}
            self.audit(what, d)
        except Exception as e:
            logger.debug(f'SAJHA Net audit {what}: {e}')
