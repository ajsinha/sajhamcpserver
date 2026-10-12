# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
An approval flow for residency rules (SAJHA Net §12; policy approvals).

A residency rule with ``effect: require_approval`` on arguments: the tool is still offered; a call whose
arguments it holds is refused at the home (``approval_required``, side home, not executed) with a pending
approval, the same one while it waits; once an administrator approves, that exact call goes ahead once.
"""

from __future__ import annotations

import textwrap

from sajha.net import EXTENSION_ID
from sajha.net.integration import residency as NR
from sajha.net.integration import set_service
from sajha.policy import approvals
from sajha.policy.engine import PolicyEngine, set_engine
from sajha.policy.loader import PolicySet
from sajha.policy.model import parse_text
from tests.net.test_net_residency import LABELS, NET, _call, label, tools_for
from tests.net.test_net_three_instances import isolate  # noqa: F401

RULES = """
rules:
  - id: eu-personal-outside-eu-needs-approval
    match: {data_classes: [eu-personal], flow: arguments, destination: {labels.jurisdiction: {ne: EU}}}
    effect: require_approval
    reason: EU personal data leaves the EU only with approval
"""


def use(text):
    ps = PolicySet()
    ps.set_policies([parse_text(textwrap.dedent(text), 'p0', 'p0.yaml')])
    eng = PolicyEngine(ps)
    set_engine(eng)
    return eng


def test_engine_gives_require_approval():
    eng = use(RULES)
    try:
        d = eng.residency(_call(['eu-personal'], 'arguments', {'jurisdiction': 'US'}))
        assert d.effect == 'require_approval' and d.kind == 'approval_required'
        assert eng.residency(_call(['eu-personal'], 'arguments', {'jurisdiction': 'EU'})).effect == 'allow'
    finally:
        set_engine(None)


def test_residency_approval_end_to_end(tmp_path, isolate):  # noqa: F811
    from tests.net.test_net_integration import ClientConnector
    from tests.net.test_net_three_instances import Instance, as_user, settle
    use(RULES)
    insts = []
    try:
        conn = ClientConnector()
        a = Instance(tmp_path, 'risk-eu', conn, [], founder=True)
        a.svc.start(run_agents=False)
        from sajha.net.integration import ServiceError
        try:
            a.svc.ca_init(NET)
        except ServiceError:
            pass
        label(a)
        assert a.node.try_join()
        n = Instance(tmp_path, 'cust-na', conn, tools_for('cust-na'))
        n.svc.start(run_agents=False)
        n.svc.enroll(NET, 'https://risk-eu.test', a.svc.ca_token(NET, 'cust-na')['token'], by='test')
        label(n)
        assert n.node.try_join()
        insts = [a, n]
        for i in insts:
            i.user('alice', tools='customer_lookup')
        kid, raw = a.key('alice')
        settle(insts, 6)
        set_service(a.svc)
        assert LABELS['cust-na'][1]['jurisdiction'] == 'US'
        # still offered: a call can be approved
        res = a.svc.catalogs.router.resolve('customer_lookup', {'user_id': 'alice', 'roles': ['user']})
        assert [c.host for c in res.candidates] == ['cust-na']
        lookup = n.reg.get_tool('customer_lookup')

        def call():
            return as_user('alice', raw, kid, lambda: a.reg.get_tool('acme-net__cust-na__customer_lookup')
                           .execute_with_tracking({'customer_id': 'C-991'}))
        r = call()
        ref = r['_meta'][EXTENSION_ID]['refusal']
        assert r['isError'] and ref['reason'] == 'approval_required' and ref['side'] == 'home', r
        assert ref['executed'] is False and ref['approval_id'] and ref['approval_id'] in r['content'][0]['text']
        assert lookup.received == []
        again = call()['_meta'][EXTENSION_ID]['refusal']
        assert again['approval_id'] == ref['approval_id']                      # the same pending approval
        rec = approvals.get(ref['approval_id'])
        assert rec['status'] == 'pending' and rec['tool'] == 'sajhanet.residency:acme-net__cust-na__customer_lookup'
        approvals.decide(ref['approval_id'], True, by_user='admin')
        r = call()
        assert not r.get('isError'), r
        assert lookup.received == [{'customer_id': 'C-991'}]
        assert call()['_meta'][EXTENSION_ID]['refusal']['reason'] == 'approval_required'   # once only
    finally:
        set_engine(None)
        NR.set_settings(None)
        for i in insts:
            i.svc.stop()
