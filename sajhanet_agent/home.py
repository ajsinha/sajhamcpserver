# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The agent as a home (protocol §3: the participant that receives the caller's request): it serves MCP to
its local clients and calls other members' tools for them, and it re-exports tools it imports.

* **Local clients.** ``--client-listen`` opens a second listener (loopback by default) serving MCP over
  Streamable HTTP at ``/mcp`` (JSON answers; ``initialize``, ``ping``, ``tools/list``, ``tools/call``). A
  client presents one of the configuration file's keys (``Authorization: Bearer <key>`` or ``X-API-Key``);
  without one a call is refused unless ``anonymous_calls`` is on, and then it carries no user (a host
  serves it only if it accepts service calls). ``tools/list`` shows the fronted server's own tools under
  their own names and every imported tool as a proxy under its qualified name
  ``<net>__<host prefix>__<tool>`` and, while no own tool has the name, its plain name (bare alias), as a
  SAJHA home does (design §8.1, §8.2); the key's tool access is a ceiling on both.
* **Calls.** An own tool goes straight to the fronted server; anything else goes through the core's
  :class:`~sajha.net.routing.Router` (resolution, import rules, blocks, residency, signed forwarding,
  fallback between hosts, the identity resolver of :mod:`sajhanet_agent.identity`), and the home's own
  residency rules see the result as it arrives.
* **Re-export** (§16). With ``reexport.enabled`` and a matching rule, an imported tool is offered to other
  members with ``origin``; a call to it is relayed to its origin with the caller's assertion unchanged,
  hop count and visited list continued.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sajha.net import EXTENSION_ID, crypto, keydir, names
from sajha.net.library import key_ceiling
from sajha.net.routing import CODES, Candidate, HostRefusal, Router, StreamSettings, origin_of

logger = logging.getLogger('sajhanet_agent')

CLIENT_ERAS = ('2025-11-25', '2025-06-18', '2025-03-26')
SERVER_INFO = {'name': 'sajhanet-agent', 'version': '1'}


def _rpc(rid, result=None, error=None) -> Dict[str, Any]:
    out: Dict[str, Any] = {'jsonrpc': '2.0', 'id': rid}
    if error is not None:
        out['error'] = error
    else:
        out['result'] = result
    return out


class ClientError(Exception):
    def __init__(self, status: int, code: int, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Home:
    """The home side of one agent (see the module docstring)."""

    def __init__(self, agent):
        self.agent = agent
        p = agent.participant
        pol = agent.policy
        self.router = Router([p.book], local_tools=agent.local_names, bare_aliases=pol().bare_aliases,
                             identity=agent.identity, rules=agent.rules, clock=p.node.clock, audit=agent.audit,
                             max_hops=pol().max_hops, max_chain=pol().max_call_chain,
                             streaming=StreamSettings(enabled=False), tasks=False)
        self.calls = 0

    def apply(self) -> None:
        """The configuration changed: limits and aliases follow it."""
        pol = self.agent.policy()
        self.router.bare_aliases = pol.bare_aliases
        self.router.max_hops = max(1, min(8, pol.max_hops))
        self.router.max_chain = max(1, min(32, pol.max_call_chain))

    # ── the host and tool table ────────────────────────────────────

    def row(self, qualified: str) -> Optional[Dict[str, Any]]:
        return next((r for r in self.router.rows() if r['qualified_name'] == qualified), None)

    def _candidate(self, r: Dict[str, Any]) -> Candidate:
        return Candidate(net=r['net'], host=r['host_instance'], host_tool=r['host_tool'],
                         qualified_name=r['qualified_name'], part=r['part'], contract_hash=r['contract_hash'],
                         state=r['state'], book=self.agent.participant.book, row=r)

    @staticmethod
    def _proxy(r: Dict[str, Any], name: str, alias: Optional[str] = None) -> Dict[str, Any]:
        e = r.get('entry') or {}
        d = e.get('definition') or {}
        contract = e.get('contract') or {}
        ann = copy.deepcopy(contract.get('annotations') or {})
        ann.setdefault('openWorldHint', True)            # a remote tool is at least open world (design §8.1)
        t: Dict[str, Any] = {'name': name, 'description': d.get('description') or '',
                             'inputSchema': copy.deepcopy(d.get('inputSchema') or {'type': 'object', 'properties': {}}),
                             'annotations': ann}
        if d.get('title'):
            t['title'] = d['title']
        if d.get('outputSchema'):
            t['outputSchema'] = copy.deepcopy(d['outputSchema'])
        meta = e.get('meta') or {}
        net_meta = {'net': r['net'], 'instance': r['host_instance'], 'qualified_name': r['qualified_name'],
                    'host_tool': r['host_tool'], 'locality': 'remote'}
        for k in ('region', 'data_classes', 'vendor', 'origin'):
            if meta.get(k):
                net_meta[k] = meta[k]
        if alias:
            net_meta['alias'] = alias
        t['_meta'] = {EXTENSION_ID: net_meta}
        return t

    def proxies(self, user: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Every imported tool this caller may use: by qualified name, then by plain name (bare aliases)."""
        out = []
        rows = {}
        for r in self.router.rows():
            if self.router._ineligible(self._candidate(r), user):
                continue
            if user is not None and not key_ceiling(user, r['net'], r['host_instance'], r['host_tool']):
                continue
            rows[r['qualified_name']] = r
            out.append(self._proxy(r, r['qualified_name']))
        for plain, order in sorted(self.router.aliases().items()):
            first = next((rows[q] for q in order if q in rows), None)
            if first is not None:
                out.append(self._proxy(first, plain, alias=plain))
        return out

    # ── re-export (§16) ────────────────────────────────────────────

    def reexports(self, peer: Optional[str] = None) -> List[Dict[str, Any]]:
        """The tools this agent re-exports to ``peer`` (None: any peer): one per name, the first eligible
        host offering it directly (then re-exported ones), never back to its host or origin, never a tool
        whose origin is this agent, never a name of an own tool."""
        pol = self.agent.policy()
        if not pol.reexport or not pol.reexport_rules:
            return []
        me = self.agent.participant.node.name
        local = set(self.agent.local_names())
        by_part: Dict[str, List[Dict[str, Any]]] = {}
        for r in self.router.rows():
            if r['state'] == 'active' and r['part'] not in local:
                by_part.setdefault(r['part'], []).append(r)
        out = []
        for part in sorted(by_part):
            for r in sorted(by_part[part], key=lambda r: (bool(origin_of(r)), r['host_instance'])):
                origin = origin_of(r) or r['host_instance']
                if origin == me or (peer is not None and peer in (origin, r['host_instance'])):
                    continue
                try:
                    if self.router._ineligible(self._candidate(r), None):
                        continue
                except Exception:
                    continue
                if self.agent.rules.reexport_rule(r, peer) is None:
                    continue
                out.append(self._reexported_tool(r, origin))
                break
        return out

    @staticmethod
    def _reexported_tool(r: Dict[str, Any], origin: str) -> Dict[str, Any]:
        """The host's contract unchanged (so the contract hash is the same, §10.7), its description as screened."""
        e = r['entry']
        d = e.get('definition') or {}
        contract = e.get('contract') or {}
        tool: Dict[str, Any] = {'name': r['host_tool'], 'description': d.get('description') or '',
                                'inputSchema': copy.deepcopy(contract.get('inputSchema') or
                                                             {'type': 'object', 'properties': {}}),
                                'annotations': copy.deepcopy(contract.get('annotations') or {})}
        if contract.get('outputSchema'):
            tool['outputSchema'] = copy.deepcopy(contract['outputSchema'])
        if d.get('title'):
            tool['title'] = d['title']
        meta = e.get('meta') or {}
        extra = {k: meta[k] for k in ('version', 'data_classes', 'llm_tool', 'vendor', 'external')
                 if meta.get(k) is not None}
        extra['origin'] = origin
        tool['_net'] = extra
        tool['_source'] = {'net': r['net'], 'host': r['host_instance'], 'qualified_name': r['qualified_name'],
                           'origin': origin, 'contract_hash': r['contract_hash']}
        return tool

    def relay(self, ctx, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Run a re-exported tool: forward the call to its origin with the caller's assertion unchanged."""
        src = (ctx.reexport or {}).get('_source') or {}
        if not ctx.relay:
            raise HostRefusal('assertion_invalid')
        q = str(src.get('qualified_name') or '')
        out = self.router.call(q, dict(arguments or {}), user=dict(ctx.user or {}), traceparent=ctx.traceparent,
                               hop_in=(ctx.hop, list(ctx.visited)), depth=ctx.depth, relay=dict(ctx.relay))
        meta = ((out or {}).get('_meta') or {}).get(EXTENSION_ID) or {}
        rf = meta.get('refusal')
        if (out or {}).get('isError') and isinstance(rf, dict) and rf.get('executed') is False \
                and rf.get('reason') in CODES:
            raise HostRefusal(str(rf['reason']), executed=False,
                              refused_by=str(rf.get('refused_by') or rf.get('instance') or '') or None)
        out = self.agent.rules.on_arrival(self.row(q), out)
        m = dict(((out or {}).get('_meta') or {}).get(EXTENSION_ID) or {})
        m['via'] = {'net': src.get('net'), 'instance': src.get('host'), 'origin': src.get('origin')}
        return dict(out, _meta=dict((out or {}).get('_meta') or {}, **{EXTENSION_ID: m}))

    # ── local clients ──────────────────────────────────────────────

    def caller(self, headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """The local caller: the user of the presented key, or None (anonymous, where allowed)."""
        h = {str(k).lower(): v for k, v in (headers or {}).items()}
        raw = ''
        auth = str(h.get('authorization') or '')
        if auth.lower().startswith('bearer '):
            raw = auth[7:].strip()
        raw = raw or str(h.get('x-api-key') or '').strip()
        pol = self.agent.policy()
        if not raw:
            if pol.anonymous_calls:
                return None
            raise ClientError(401, -32001, 'this SAJHA Net agent needs one of its keys (Authorization: Bearer <key>)')
        hit = pol.user_by_key_hash(keydir.key_hash(raw))
        node = self.agent.participant.node
        if hit is None:
            raise ClientError(401, -32001, 'the key is not one of this agent\'s keys')
        u, k = hit
        if not (u.enabled and k.enabled):
            raise ClientError(401, -32001, 'the key is disabled')
        if k.expires_at and crypto.parse_rfc3339(k.expires_at) <= node.clock():
            raise ClientError(401, -32001, 'the key has expired')
        return {'name': names.net_user(u.user_name, node.name), 'user_id': u.user_name, 'user_name': u.user_name,
                'display_name': u.display_name, 'roles': list(u.roles), 'remote_roles': list(u.roles),
                'key_id': k.id, 'tool_access_mode': k.tool_access_mode, 'tool_access_list': list(k.tool_access_list),
                'net': node.net, 'home': node.name, 'authenticated': True, '_api_key': raw}

    def own_tools(self, user: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        node = self.agent.participant.node
        out = []
        for t in self.agent.catalog.tools(node.net):
            t = {k: v for k, v in t.items() if k != '_net'}
            if user is None or key_ceiling(user, node.net, node.name, t['name']):
                out.append(t)
        return out

    def tools_list(self, user: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self.own_tools(user) + self.proxies(user)

    def call(self, name: str, arguments: Dict[str, Any], user: Optional[Dict[str, Any]],
             traceparent: Optional[str] = None) -> Dict[str, Any]:
        node = self.agent.participant.node
        self.calls += 1
        if name in set(self.agent.local_names()):
            if user is not None and not key_ceiling(user, node.net, node.name, name):
                return _error_result(f'{name}: your key does not give access to this tool')
            return self.agent.call_own(name, arguments)
        if user is not None:
            res = self.router.resolve(name, user)
            if res.candidates and not any(key_ceiling(user, c.net, c.host, c.host_tool) for c in res.candidates):
                return _error_result(f'{name}: your key does not give access to this tool')
        try:
            out = self.router.call(name, dict(arguments or {}), user=dict(user) if user else None,
                                   traceparent=traceparent)
        except LookupError:
            return _error_result(f'{name} is not a tool here')
        meta = ((out or {}).get('_meta') or {}).get(EXTENSION_ID) or {}
        if not out.get('isError') and meta.get('qualified_name'):
            out = self.agent.rules.on_arrival(self.row(str(meta['qualified_name'])), out)
        return out

    def handle_client(self, method: str, path: str, headers: Dict[str, str], body: bytes) -> Tuple[int, Dict[str, str], bytes]:
        """One HTTP request from a local client: ``(status, headers, body)``."""
        js = {'content-type': 'application/json'}
        if path.rstrip('/') != '/mcp':
            return 404, {}, b''
        if method.upper() == 'DELETE':
            return 200, {}, b''
        if method.upper() != 'POST':
            return 405, {'allow': 'POST, DELETE'}, b''
        try:
            msg = json.loads((body or b'').decode('utf-8'))
        except ValueError:
            msg = None
        if not isinstance(msg, dict):
            return 400, js, json.dumps(_rpc(None, error={'code': -32700, 'message': 'parse error (one JSON-RPC '
                                                                                     'message per request)'})).encode()
        rid = msg.get('id')
        try:
            user = self.caller(headers)
        except ClientError as e:
            return e.status, js, json.dumps(_rpc(rid, error={'code': e.code, 'message': e.message})).encode()
        if 'id' not in msg:
            return 202, {}, b''
        m = msg.get('method')
        params = msg.get('params') if isinstance(msg.get('params'), dict) else {}
        if m == 'initialize':
            want = str(params.get('protocolVersion') or '')
            result = {'protocolVersion': want if want in CLIENT_ERAS else CLIENT_ERAS[0],
                      'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': SERVER_INFO,
                      'instructions': f'Tools of this server and of SAJHA Net {self.agent.participant.node.net}; '
                                      f'remote tools are named <net>__<host>__<tool>.'}
            out = _rpc(rid, result)
        elif m == 'ping':
            out = _rpc(rid, {})
        elif m == 'tools/list':
            out = _rpc(rid, {'tools': self.tools_list(user)})
        elif m == 'tools/call':
            name = str(params.get('name') or '')
            args = params.get('arguments') if isinstance(params.get('arguments'), dict) else {}
            pmeta = params.get('_meta') if isinstance(params.get('_meta'), dict) else {}
            tp = {str(k).lower(): v for k, v in (headers or {}).items()}.get('traceparent') or pmeta.get('traceparent')
            out = _rpc(rid, self.call(name, args, user, traceparent=tp))
        else:
            out = _rpc(rid, error={'code': -32601, 'message': f'{m} is not served by the SAJHA Net agent'})
        return 200, js, json.dumps(out, ensure_ascii=False).encode('utf-8')


def _error_result(text: str) -> Dict[str, Any]:
    return {'content': [{'type': 'text', 'text': text}], 'isError': True}
