# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The agent's rule evaluator (protocol §15.4 steps 3, 6, 8, 9 and §16, §17 residency; design §11, §12):
the export policy of the command line, and from the configuration file the blocks, import rules,
residency rules and re-export rules. The rule names are those the core asks
(:mod:`sajha.net.routing`, :mod:`sajha.net.catalog`); the decisions mirror SAJHA's.

* **Blocks** (design §11.4), enforced here only and published (``/sajhanet/v1/blocks``): ``instance``
  and ``inbound`` refuse a sender (step 3), ``user`` a remote user (step 6), ``tool`` with direction
  ``inbound`` a host tool (step 8); ``instance``, ``outbound`` and ``tool`` with direction ``outbound``
  hide a host or a remote tool from this agent's callers and are never called.
* **Import rules** (home): ``{tools, instances, for_roles}``; nothing is imported unless a rule allows it,
  and a rule with an empty ``instances`` imports its tools from nobody. Without an ``import`` section the
  agent imports every tool.
* **Residency** (feature ``residency``): data classes from the tools' schema marks
  (``x-sajha-data-class``), the catalog's ``data_classes`` and the file's ``residency.tools`` overlay;
  rules of the shape of SAJHA's residency rules (deny overrides, then ``require_approval``, then allow
  and redact; ``default_effect``). At the home before arguments leave (destination: the host), at the
  host before a result leaves (destination: the home) and at the home as a result arrives (here). The
  agent has no approval surface, so ``require_approval`` refuses: arguments with
  ``residency_arguments`` and a detail saying a person's approval is needed and the agent cannot ask
  for one; results with ``residency_result``.
* **Re-export** (feature ``reexport``): ``{tools, from_instances, to_instances, for_roles}``; a rule with
  an empty ``to_instances`` re-exports its tools to nobody.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.net import EXTENSION_ID
from sajha.net import blocks as nblocks
from sajha.net import residency as R
from sajha.net.library import ExportPolicy, key_ceiling
from sajha.net.plugins import Decision, RuleEvaluator

from sajhanet_agent.config import match_any

logger = logging.getLogger('sajhanet_agent')

NO_APPROVAL = ('needs a person\'s approval (residency rule {rule}), and this SAJHA Net agent has no approval '
               'surface: the call is refused. Call the tool from a SAJHA server, where an administrator can '
               'approve it, or change the rule')


def _roles_ok(roles: Optional[List[str]], wanted: Any) -> bool:
    w = list(wanted or [])
    if not w or roles is None:
        return True
    return '*' in w or bool(set(w) & set(roles or []))


def structured(result: Dict[str, Any]) -> Any:
    if isinstance(result.get('structuredContent'), (dict, list)):
        return result['structuredContent']
    for b in result.get('content') or []:
        if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str):
            try:
                v = json.loads(b['text'])
            except ValueError:
                continue
            if isinstance(v, (dict, list)):
                return v
    return None


class AgentRules(RuleEvaluator):
    """See the module docstring. ``policy()`` is the current configuration; ``node()`` the net node;
    ``local_tool(name)`` an own tool's definition (for the result's data classes); ``audit`` gets
    residency decisions."""
    name = 'agent_rules'

    def __init__(self, export: ExportPolicy, policy: Callable[[], Any], node: Callable[[], Any],
                 local_tool: Callable[[str], Optional[Dict[str, Any]]] = lambda name: None,
                 reexport_row: Callable[[str], Optional[Dict[str, Any]]] = lambda qn: None,
                 importing: Callable[[], bool] = lambda: True,
                 audit: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.export = export
        self.importing = importing
        self.policy = policy
        self.node = node
        self.local_tool = local_tool
        self.reexport_row = reexport_row
        self.audit = audit
        self.version = 1

    @property
    def blocks(self) -> List[Dict[str, Any]]:
        return list(self.policy().blocks)

    def _now(self) -> float:
        return self.node().clock()

    def decide(self, rule, subject):
        s = subject or {}
        bl, now = self.blocks, self._now()
        peer = str(s.get('peer') or s.get('host') or '')
        if rule == 'block_peer':
            direction = str(s.get('direction') or 'inbound')
            b = (nblocks.match_inbound(bl, now, peer) if direction == 'inbound'
                 else nblocks.match_outbound(bl, now, peer) if direction == 'outbound'
                 else next((x for x in nblocks.active(bl, now) if x.get('level') == 'instance'
                            and x.get('target_instance') in (peer, '*')), None))
            return Decision(b is None, b['level'] if b else 'not_blocked')
        if rule == 'block_user':
            u = s.get('user')
            name = u.get('name') if isinstance(u, dict) else str(u or '')
            b = nblocks.match_user(bl, now, name) if name else None
            return Decision(b is None, 'user' if b else 'not_blocked')
        if rule == 'block_tool':
            b = next((x for x in (nblocks.match_tool(bl, now, peer, n)
                                  for n in [str(s.get('tool') or '')] + list(s.get('tool_names') or []))
                      if x is not None), None)
            return Decision(b is None, 'tool' if b else 'not_blocked')
        if rule == 'export':
            if peer and nblocks.match_inbound(bl, now, peer):
                return Decision(False, 'export')
            return self.export.decide(rule, s)
        if rule == 'service_call':
            return self.export.decide(rule, s)
        if rule == 'pull':                              # only a home (or a re-exporter) pulls catalogs
            return Decision(self.importing() and not nblocks.blocked_entirely(bl, now, peer), rule)
        if rule == 'offer':
            return Decision(nblocks.match_outbound(bl, now, peer, self._qualified(s)) is None, rule)
        if rule == 'import':
            if not self.importing():
                return Decision(False, 'import')
            if nblocks.match_outbound(bl, now, peer, self._qualified(s)) is not None:
                return Decision(False, 'import')
            u = s.get('user') if isinstance(s.get('user'), dict) else None
            return self._import(peer, str(s.get('tool') or ''), list(u.get('roles') or []) if u else None)
        if rule == 'reexport':
            return self._reexport_call(s)
        if rule in ('residency_offer', 'residency_arguments'):
            return self._residency_out(rule, s)
        if rule == 'residency_result':
            return self._residency_result(s)
        if rule == 'residency_events':
            return Decision(True, rule)
        return Decision(True, rule)

    def _qualified(self, s: Dict[str, Any]) -> Optional[str]:
        if s.get('qualified_name'):
            return str(s['qualified_name'])
        try:
            from sajha.net import names
            return names.qualified_name(self.node().net, str(s.get('host') or s.get('peer') or ''),
                                        str(s.get('tool') or ''))
        except Exception:
            return None

    # ── import and re-export ───────────────────────────────────────

    def _import(self, host: str, tool: str, roles: Optional[List[str]]) -> Decision:
        rules = self.policy().import_rules
        for r in rules:
            if match_any(tool, r.get('tools')) and 'instances' in r and not r['instances']:
                return Decision(False, 'import')
        for r in rules:
            if match_any(tool, r.get('tools')) and match_any(host, r.get('instances') or ['*']) \
                    and _roles_ok(roles, r.get('for_roles')):
                return Decision(True, 'import')
        return Decision(False, 'import')

    def reexport_rule(self, row: Dict[str, Any], peer: Optional[str], roles: Optional[List[str]] = None):
        """The first re-export rule letting ``row`` (a host and tool table row) go to ``peer`` (None: any)."""
        hit = None
        for r in self.policy().reexport_rules:
            if not (match_any(row['host_tool'], r.get('tools')) or match_any(row['part'], r.get('tools'))):
                continue
            if not match_any(row['host_instance'], r.get('from_instances') or ['*']):
                continue
            if 'to_instances' in r and not r['to_instances']:
                return None
            if peer is not None and not match_any(peer, r.get('to_instances') or ['*']):
                continue
            if not _roles_ok(roles, r.get('for_roles')):
                continue
            hit = hit or r
        return hit

    def _reexport_call(self, s: Dict[str, Any]) -> Decision:
        src = s.get('source') or {}
        row = self.reexport_row(str(src.get('qualified_name') or ''))
        if row is None:
            return Decision(False, 'export')
        u = s.get('user') if isinstance(s.get('user'), dict) else None
        if self.reexport_rule(row, str(s.get('peer') or ''), list(u.get('roles') or []) if u else None) is None:
            return Decision(False, 'export')
        node = self.node()
        if u is not None and not key_ceiling(u, node.net, node.name, str(s.get('tool') or '')):
            return Decision(False, 'access')
        return Decision(True, 'reexport')

    # ── residency ──────────────────────────────────────────────────

    def facts(self, instance: Optional[str] = None) -> Dict[str, Any]:
        node = self.node()
        if instance is None or instance == node.name:
            return {'net': node.net, 'instance': node.name, 'region': node.cfg.region or None,
                    'labels': dict(node.cfg.labels or {}), 'here': True}
        rec = ((node.member(instance) or {}).get('record')) or {}
        return {'net': node.net, 'instance': instance, 'region': str(rec.get('region') or '') or None,
                'labels': dict(rec.get('labels') or {}), 'here': False}

    def entry_marks(self, entry: Any, host_tool: str, qualified: str) -> Tuple[R.Marks, R.Marks]:
        """A host and tool table entry's (arguments, results) marks: the schemas' marks, the net metadata's
        ``data_classes`` (for the whole value where no field carries them) and the file's overlay."""
        e = entry if isinstance(entry, dict) else {}
        d = e.get('definition') if isinstance(e.get('definition'), dict) else {}
        meta = e.get('meta') if isinstance(e.get('meta'), dict) else {}
        oa, orr = self.policy().residency.marks([host_tool, qualified])
        a = R.merge_marks(R.schema_marks(d.get('inputSchema')), oa)
        r = R.merge_marks(R.schema_marks(d.get('outputSchema')), orr)
        dc = meta.get('data_classes') if isinstance(meta.get('data_classes'), dict) else {}
        for marks, k in ((a, 'arguments'), (r, 'results')):
            have = {c for v in marks.values() for c in v}
            extra = [x for x in R.as_classes(dc.get(k)) if x not in have]
            if extra:
                marks[R.WHOLE] = list(dict.fromkeys((marks.get(R.WHOLE) or []) + extra))
        return a, r

    def own_marks(self, tool: str) -> Tuple[R.Marks, R.Marks]:
        t = self.local_tool(tool) or {}
        oa, orr = self.policy().residency.marks([tool, str(t.get('name') or '')])
        return (R.merge_marks(R.schema_marks(t.get('inputSchema')), oa),
                R.merge_marks(R.schema_marks(t.get('outputSchema')), orr))

    def _audit(self, flow: str, other: str, tool: str, classes: List[str], outcome: str, rule: str = '',
               fields: Optional[List[str]] = None, trace_id: str = '', side: str = 'home') -> None:
        d = {'net': self.node().net, 'instance': other, 'tool': tool, 'flow': flow, 'data_classes': sorted(classes),
             'outcome': outcome, 'rule': rule, 'side': side}
        if fields:
            d['fields'] = fields
        if trace_id:
            d['trace_id'] = trace_id
        logger.info(f'SAJHA Net residency: {json.dumps(d, sort_keys=True)}')
        if self.audit is not None:
            try:
                self.audit('net.residency', d)
            except Exception:
                pass

    def _residency_out(self, rule: str, s: Dict[str, Any]) -> Decision:
        host = str(s.get('host') or '')
        tool = str(s.get('qualified_name') or s.get('tool') or '')
        a, _r = self.entry_marks(s.get('entry'), str(s.get('tool') or ''), str(s.get('qualified_name') or ''))
        if rule == 'residency_offer':
            ins = ((s.get('entry') or {}).get('definition') or {}).get('inputSchema') \
                if isinstance(s.get('entry'), dict) else None
            classes = R.necessary_classes(ins, a.get(R.WHOLE) or [], {k: v for k, v in a.items() if k != R.WHOLE})
        else:
            classes = R.classes_present(s.get('arguments') or {}, a)
        if not classes:
            return Decision(True, rule)
        res = self.policy().residency
        d = res.decide(classes, 'arguments', self.facts(host), self.facts())
        trace = str(s.get('trace_id') or '')
        if rule == 'residency_offer':                     # a tool whose calls need approval is still listed
            ok = d.effect in ('allow', 'require_approval')
            if not ok and s.get('audit_refusal'):
                self._audit('arguments', host, tool, classes, 'refused', d.rule, trace_id=trace)
            return Decision(ok, rule if ok else 'residency_arguments')
        if d.effect == 'require_approval':
            self._audit('arguments', host, tool, classes, 'refused', d.rule, trace_id=trace)
            return Decision(False, 'residency_arguments',
                            value={'detail': f'The arguments of {tool} ' + NO_APPROVAL.format(rule=d.rule)})
        if d.effect != 'allow':
            self._audit('arguments', host, tool, classes, 'refused', d.rule, trace_id=trace)
            return Decision(False, 'residency_arguments')
        if d.redact:
            red, touched, _ = R.redact_fields(s.get('arguments') or {}, a, d.redact)
            if R.WHOLE in touched:
                self._audit('arguments', host, tool, classes, 'refused', d.rule, ['*'], trace)
                return Decision(False, 'residency_arguments')
            if touched:
                self._audit('arguments', host, tool, classes, 'redacted', d.rule, touched, trace)
                return Decision(True, rule, value=red)
        self._audit('arguments', host, tool, classes, 'allowed', d.rule, trace_id=trace)
        return Decision(True, rule)

    def _residency_result(self, s: Dict[str, Any]) -> Decision:
        """At the host (step 12 of §15.4): the result of an own tool before it leaves for the home."""
        tool = str(s.get('tool') or '')
        result = s.get('result') if isinstance(s.get('result'), dict) else {}
        _a, marks = self.own_marks(tool)
        value = structured(result)
        classes = R.classes_present(value, marks) if value is not None else list(marks.get(R.WHOLE) or [])
        if R.WHOLE in marks and value is None and result.get('content'):
            classes = list(dict.fromkeys(classes + marks[R.WHOLE]))
        if not classes or result.get('isError'):
            return Decision(True, 'residency_result')
        peer = str(s.get('peer') or '')
        trace = str(s.get('trace_id') or '')
        d = self.policy().residency.decide(classes, 'results', self.facts(peer), self.facts())
        if d.effect != 'allow':
            self._audit('results', peer, tool, classes, 'refused', d.rule, trace_id=trace, side='host')
            return Decision(False, 'residency_result')
        if d.redact:
            red, touched = R.redact_result(result, marks, d.redact)
            if R.WHOLE in touched:
                self._audit('results', peer, tool, classes, 'refused', d.rule, ['*'], trace, 'host')
                return Decision(False, 'residency_result')
            if touched:
                left = R.classes_present(structured(red), {k: v for k, v in marks.items() if k not in touched})
                self._audit('results', peer, tool, classes, 'redacted', d.rule, touched, trace, 'host')
                return Decision(True, 'residency_result', value=with_classes(red, left, touched))
        self._audit('results', peer, tool, classes, 'allowed', d.rule, trace_id=trace, side='host')
        return Decision(True, 'residency_result', value=with_classes(result, classes))

    def on_arrival(self, row: Optional[Dict[str, Any]], result: Dict[str, Any]) -> Dict[str, Any]:
        """The home's rules on a result as it arrives (flow ``results``, destination here): redact fields or
        refuse with ``residency_result`` (side home, executed)."""
        if not isinstance(result, dict) or result.get('isError'):
            return result
        meta = (result.get('_meta') or {}).get(EXTENSION_ID) or {}
        qn = str(meta.get('qualified_name') or (row or {}).get('qualified_name') or '')
        _a, marks = self.entry_marks((row or {}).get('entry'), str((row or {}).get('host_tool') or ''), qn)
        value = structured(result)
        classes = R.classes_present(value, marks) if value is not None else list(marks.get(R.WHOLE) or [])
        told = R.as_classes((meta.get('data_classes') or {}).get('results')) \
            if isinstance(meta.get('data_classes'), dict) else []
        classes = list(dict.fromkeys(told + classes))
        if not classes:
            return result
        here = self.facts()
        host = str(meta.get('instance') or '')
        d = self.policy().residency.decide(classes, 'results', here, here)
        out = with_classes(result, classes)
        trace = str(meta.get('trace_id') or '')
        if d.effect == 'allow' and not d.redact:
            return out
        if d.effect == 'allow':
            red, touched = R.redact_result(out, marks, d.redact)
            if touched and R.WHOLE not in touched:
                self._audit('results', host, qn, classes, 'redacted', d.rule, touched, trace)
                m = dict((red.get('_meta') or {}).get(EXTENSION_ID) or {})
                m['redacted'] = sorted(set((m.get('redacted') or []) + touched))
                return dict(red, _meta=dict(red.get('_meta') or {}, **{EXTENSION_ID: m}))
            if not touched:
                return out
        self._audit('results', host, qn, classes, 'refused', d.rule, trace_id=trace)
        from sajha.net.routing import RPC_RESIDENCY, SAFE_WORDS, refusal
        node = self.node()
        data = refusal(RPC_RESIDENCY, 'residency_result', 'home', node.net, node.name, qn, trace,
                       executed=True)['data'][EXTENSION_ID]
        return {'content': [{'type': 'text', 'text': f'This server refused the result of {qn}: '
                                                     f'{SAFE_WORDS["residency_result"]}.'}],
                'isError': True, '_meta': {EXTENSION_ID: dict(meta, refusal=data)}}


def with_classes(result: Dict[str, Any], classes: List[str], redacted: Optional[List[str]] = None) -> Dict[str, Any]:
    out = dict(result)
    rm = dict((out.get('_meta') or {}).get(EXTENSION_ID) or {})
    if classes:
        rm['data_classes'] = {'results': sorted(classes)}
    if redacted:
        rm['redacted'] = redacted
    if rm:
        out['_meta'] = dict(out.get('_meta') or {}, **{EXTENSION_ID: rm})
    return out
