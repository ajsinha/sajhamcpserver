# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Adversarial QA Plan 3.4 (authorization and policy), P0: a denied tool is denied under every name it
answers to: the plain alias and the qualified ``<net>__<instance>__<tool>`` of a SAJHA Net tool, the
published ``<vendor>__<tool>`` and a renamed name of an external server's tool, and as a step of a
composite or a workflow.

Found by this suite and fixed: a policy rule naming a SAJHA Net tool's plain alias did not match a call
by its qualified name (or the other way round), so ``deny find`` was bypassed by calling
``acme-net__risk-eu__find`` (F1); caller tool access (roles, API-key lists) had the same gap (F2). Rules
and access patterns now match any of a tool's names (``sajha.policy.engine.tool_aliases``).

Covered elsewhere and cited in the plan: composite steps check the caller's access
(tests/test_api_keys_identity.py), workflow steps the run-as identity's (tests/test_workflows.py), and
net blocks accept either name (tests/net/test_net_vendors.py).
"""

import pytest

from sajha.net import EXTENSION_ID
from sajha.policy.errors import PolicyDenied
from tests.net.test_net_vendors import Q, _call, _net
from tests.net.test_net_three_instances import isolate  # noqa: F401
from tests.test_policy import ALICE, Echo, _isolate, as_caller, use  # noqa: F401


def _refused(result) -> bool:
    if isinstance(result, Exception):
        return isinstance(result, PermissionError)
    return bool(isinstance(result, dict) and result.get('isError'))


def _try(home, kid, raw, name):
    try:
        return _call(home, kid, raw, name)
    except Exception as e:                               # noqa: BLE001 — a refusal may be raised or returned
        return e


@pytest.fixture
def net(tmp_path, isolate):  # noqa: F811
    """home calls risk-eu, which defines the external server acme (vendor acme) with search renamed find,
    and the external server glx (vendor globex) under its published name."""
    conn, fed, home, (a,), kid, raw = _net(tmp_path, [('risk-eu', [('acme', 'acme', Q, {'search': 'find'}, 'search'),
                                                                   ('glx', 'globex', Q, None, 'search')])])
    yield home, a, kid, raw
    for p in (home, a):
        p.svc.stop()


def test_net_tools_answer_to_several_names(net):
    home, a, kid, raw = net
    assert {'find', 'acme-net__risk-eu__find', 'globex__search', 'acme-net__risk-eu__globex__search'} <= set(home.reg.tools)
    assert not _refused(_try(home, kid, raw, 'find')) and not _refused(_try(home, kid, raw, 'globex__search'))


@pytest.mark.parametrize('denied', ['find', 'acme-net__risk-eu__find', 'acmefed__search'])
def test_a_policy_deny_holds_under_every_name_of_a_renamed_tool(net, denied):
    home, a, kid, raw = net
    use(f'rules: [{{id: no, match: {{tools: ["{denied}"]}}, effect: deny, reason: denied by name}}]')
    for name in ('find', 'acme-net__risk-eu__find'):
        assert _refused(_try(home, kid, raw, name)), (denied, name)
    assert not _refused(_try(home, kid, raw, 'globex__search'))            # the rule hits only that tool


@pytest.mark.parametrize('denied', ['globex__search', 'acme-net__risk-eu__globex__search', 'glxfed__search'])
def test_a_policy_deny_holds_under_the_published_and_qualified_names(net, denied):
    home, a, kid, raw = net
    use(f'rules: [{{id: no, match: {{tools: ["{denied}"]}}, effect: deny, reason: denied by name}}]')
    for name in ('globex__search', 'acme-net__risk-eu__globex__search'):
        assert _refused(_try(home, kid, raw, name)), (denied, name)


def test_a_host_block_on_the_local_name_holds_under_every_name(net):
    home, a, kid, raw = net
    from tests.net.test_net_vendors import M
    a.svc.authz.add_block(M, 'tool', '*', 'adversarial', by='admin', tool='acmefed__search')
    for name in ('find', 'acme-net__risk-eu__find'):
        r = _try(home, kid, raw, name)
        assert _refused(r), name
        if isinstance(r, dict):
            assert r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'tool', r


# ── the policy rule itself, without a net ─────────────────────────────

class _Aliased(Echo):
    """A tool that answers to a qualified name and an alias, as a SAJHA Net proxy does."""

    def __init__(self, name, qualified, alias):
        super().__init__(name)
        self.meta = {'qualified_name': qualified, 'alias': alias}
        self.namespaced_name = True


@pytest.mark.parametrize('pattern', ['calc', 'n__inst__calc', 'n__*__calc', 'calc*'])
def test_a_rule_naming_any_alias_decides_for_every_name(pattern):
    use(f'rules: [{{id: no, match: {{tools: ["{pattern}"]}}, effect: deny, reason: no}}]')
    for name in ('calc', 'n__inst__calc'):
        with as_caller(ALICE), pytest.raises(PolicyDenied):
            _Aliased(name, 'n__inst__calc', 'calc').execute_with_tracking({})


def test_exclusions_also_see_every_name():
    use('rules: [{id: all, match: {tools: ["*"], exclude_tools: ["calc"]}, effect: deny, reason: no}]')
    with as_caller(ALICE):
        assert _Aliased('n__inst__calc', 'n__inst__calc', 'calc').execute_with_tracking({})['ok']
        with pytest.raises(PolicyDenied):
            Echo('other').execute_with_tracking({})


def test_a_composite_step_named_by_alias_is_denied():
    from sajha.core.composition import execute_step
    use('rules: [{id: no, match: {tools: [calc]}, effect: deny, reason: inner blocked}]')
    res = execute_step(_Aliased('n__inst__calc', 'n__inst__calc', 'calc'), {})
    assert res.error and 'inner blocked' in res.error


def test_a_key_deny_list_naming_an_alias_covers_the_qualified_name(web):
    """Finding F2 (fixed): caller tool access matched only the name called."""
    from sajha.app import tools_registry
    from sajha.auth.access import SessionToolAccess, ToolPolicy, apikey_policy
    tools = [_Aliased('zz_adv_n__inst__calc', 'zz_adv_n__inst__calc', 'zz_adv_calc'),
             _Aliased('zz_adv_calc', 'zz_adv_n__inst__calc', 'zz_adv_calc')]
    for t in tools:
        tools_registry.register_tool(t)
    try:
        access = SessionToolAccess()
        for listed in ('zz_adv_calc', 'zz_adv_n__inst__calc'):
            deny = {'user_id': 'k', 'authenticated': True, **apikey_policy('denylist', [listed]).to_session()}
            allow = {'user_id': 'k', 'authenticated': True, **apikey_policy('allowlist', [listed]).to_session()}
            for name in ('zz_adv_calc', 'zz_adv_n__inst__calc'):
                assert not access.has_tool_access(deny, name), (listed, name)
                assert not access.can_see(deny, name), (listed, name)
                assert access.has_tool_access(allow, name), (listed, name)      # one decision either way
            assert access.has_tool_access(deny, 'calc_percentage_change')
        assert not ToolPolicy(['*'], ['*'], ['calc']).can_execute('n__inst__calc', aliases=['calc'])
    finally:
        for t in tools:
            tools_registry.unregister_tool(t.name)
